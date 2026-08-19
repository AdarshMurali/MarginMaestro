from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import Settings
from persistence.db.models import (
    Base,
    CounterpartyORM,
    LatestPriceORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    RatingORM,
)
from persistence.models import RatingGrade
from streaming.event_agent import (
    _dead_letter_event,
    _handle_with_retry,
    _publish_dead_letter,
    affected_counterparties,
    classify_price_move,
    handle_market_event_message,
    handle_message,
    handle_price_message,
    is_already_processed,
    latest_close_before,
    price_event_id,
    upsert_latest_price,
    upsert_rating_downgrade,
)
from streaming.market_feed import PriceQuote
from streaming.producer import ProducerDeliveryError
from streaming.schemas import ImpactSet, MarketEvent, MarketEventType


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


def _quote(ticker: str, price: float, as_of: datetime, source: str = "yfinance") -> PriceQuote:
    return PriceQuote(ticker=ticker, price=price, as_of=as_of, source=source)


def _seed_position(session: Session, counterparty_id: str, ticker: str) -> None:
    session.add(
        CounterpartyORM(id=counterparty_id, name=counterparty_id, type="Bank", country="US")
    )
    portfolio_id = f"PF-{counterparty_id}"
    session.add(PortfolioORM(id=portfolio_id, counterparty_id=counterparty_id, currency="USD"))
    session.add(
        PositionORM(
            id=f"POS-{counterparty_id}-{ticker}",
            portfolio_id=portfolio_id,
            ticker=ticker,
            asset_class="equity",
            quantity=100,
            trade_date=date(2026, 1, 1),
        )
    )
    session.commit()


class TestClassifyPriceMove:
    def test_below_threshold_is_not_an_event(self) -> None:
        assert classify_price_move(_quote("AAPL", 103.0, datetime.now(UTC)), 100.0) is None

    def test_price_shock_range(self) -> None:
        result = classify_price_move(_quote("AAPL", 88.0, datetime.now(UTC)), 100.0)
        assert result == MarketEventType.PRICE_SHOCK

    def test_vol_spike_range(self) -> None:
        result = classify_price_move(_quote("AAPL", 80.0, datetime.now(UTC)), 100.0)
        assert result == MarketEventType.VOL_SPIKE

    def test_zero_prior_close_is_not_an_event(self) -> None:
        assert classify_price_move(_quote("AAPL", 88.0, datetime.now(UTC)), 0.0) is None


class TestPriceEventId:
    def test_deterministic_for_identical_message_content(self) -> None:
        as_of = datetime(2026, 7, 31, 14, 30, tzinfo=UTC)
        a = _quote("TSLA", 88.0, as_of)
        b = _quote("TSLA", 88.0, as_of)
        assert price_event_id(a) == price_event_id(b)

    def test_differs_when_as_of_differs(self) -> None:
        a = _quote("TSLA", 88.0, datetime(2026, 7, 31, 14, 30, tzinfo=UTC))
        b = _quote("TSLA", 88.0, datetime(2026, 7, 31, 14, 31, tzinfo=UTC))
        assert price_event_id(a) != price_event_id(b)


class TestLatestCloseBefore:
    def test_returns_most_recent_close_before_cutoff(self, session: Session) -> None:
        session.add_all(
            [
                PriceHistoryORM(
                    ticker="TSLA",
                    price_date=date(2026, 7, 29),
                    price=95.0,
                    currency="USD",
                    source="yfinance",
                ),
                PriceHistoryORM(
                    ticker="TSLA",
                    price_date=date(2026, 7, 30),
                    price=100.0,
                    currency="USD",
                    source="yfinance",
                ),
            ]
        )
        session.commit()

        result = latest_close_before(session, "TSLA", datetime(2026, 7, 31, tzinfo=UTC))

        assert result == 100.0

    def test_returns_none_when_no_history(self, session: Session) -> None:
        assert latest_close_before(session, "TSLA", datetime(2026, 7, 31, tzinfo=UTC)) is None


class TestAffectedCounterparties:
    def test_returns_distinct_counterparties_holding_the_ticker(self, session: Session) -> None:
        _seed_position(session, "CP-1", "TSLA")
        _seed_position(session, "CP-2", "TSLA")
        _seed_position(session, "CP-3", "AAPL")

        assert affected_counterparties(session, "TSLA") == ["CP-1", "CP-2"]

    def test_returns_empty_list_for_unheld_ticker(self, session: Session) -> None:
        assert affected_counterparties(session, "TSLA") == []


class TestUpsertLatestPrice:
    def test_inserts_a_new_row(self, session: Session) -> None:
        quote = _quote("TSLA", 88.0, datetime(2026, 7, 31, 14, 0, tzinfo=UTC))

        upsert_latest_price(session, quote)

        row = session.get(LatestPriceORM, "TSLA")
        assert row is not None
        assert row.price == 88.0
        assert row.source == "yfinance"

    def test_merge_overwrites_with_the_newer_quote(self, session: Session) -> None:
        upsert_latest_price(session, _quote("TSLA", 88.0, datetime(2026, 7, 31, 14, 0, tzinfo=UTC)))

        upsert_latest_price(session, _quote("TSLA", 91.5, datetime(2026, 7, 31, 14, 1, tzinfo=UTC)))

        row = session.get(LatestPriceORM, "TSLA")
        assert row is not None
        assert row.price == 91.5


class TestHandlePriceMessage:
    def test_publishes_impact_set_on_shock_and_marks_processed(
        self, session: Session, settings: Settings
    ) -> None:
        _seed_position(session, "CP-1", "TSLA")
        session.add(
            PriceHistoryORM(
                ticker="TSLA",
                price_date=date(2026, 7, 30),
                price=100.0,
                currency="USD",
                source="yfinance",
            )
        )
        session.commit()
        quote = _quote(
            "TSLA", 88.0, datetime(2026, 7, 31, 14, 0, tzinfo=UTC), source="simulated:price_shock"
        )
        producer = MagicMock()

        impact = handle_price_message(session, quote, producer, settings)

        assert impact is not None
        assert impact.event_type == MarketEventType.PRICE_SHOCK
        assert impact.counterparty_ids == ["CP-1"]
        producer.publish.assert_called_once_with(
            settings.kafka_topic_impact, impact, key=impact.event_id
        )
        producer.flush.assert_called_once()
        assert is_already_processed(session, impact.event_id)

    def test_replaying_the_same_message_is_a_no_op(
        self, session: Session, settings: Settings
    ) -> None:
        _seed_position(session, "CP-1", "TSLA")
        session.add(
            PriceHistoryORM(
                ticker="TSLA",
                price_date=date(2026, 7, 30),
                price=100.0,
                currency="USD",
                source="yfinance",
            )
        )
        session.commit()
        quote = _quote("TSLA", 88.0, datetime(2026, 7, 31, 14, 0, tzinfo=UTC))
        producer = MagicMock()

        handle_price_message(session, quote, producer, settings)
        result = handle_price_message(session, quote, producer, settings)

        assert result is None
        producer.publish.assert_called_once()
        assert session.get(LatestPriceORM, "TSLA") is not None

    def test_no_prior_close_is_a_safe_no_op(self, session: Session, settings: Settings) -> None:
        quote = _quote("TSLA", 88.0, datetime(2026, 7, 31, 14, 0, tzinfo=UTC))
        producer = MagicMock()

        result = handle_price_message(session, quote, producer, settings)

        assert result is None
        producer.publish.assert_not_called()
        assert is_already_processed(session, price_event_id(quote))
        # Latest price is still recorded -- freshness for /exposure isn't
        # gated on whether a prior close exists to classify the move.
        row = session.get(LatestPriceORM, "TSLA")
        assert row is not None
        assert row.price == 88.0

    def test_below_threshold_move_is_not_published(
        self, session: Session, settings: Settings
    ) -> None:
        session.add(
            PriceHistoryORM(
                ticker="AAPL",
                price_date=date(2026, 7, 30),
                price=200.0,
                currency="USD",
                source="yfinance",
            )
        )
        session.commit()
        quote = _quote("AAPL", 202.0, datetime(2026, 7, 31, 14, 0, tzinfo=UTC))
        producer = MagicMock()

        result = handle_price_message(session, quote, producer, settings)

        assert result is None
        producer.publish.assert_not_called()
        # Below-threshold moves are the vast majority of ticks -- the
        # latest-price table must still update on every one of them, not
        # just the ones that turn into an ImpactSet.
        row = session.get(LatestPriceORM, "AAPL")
        assert row is not None
        assert row.price == 202.0


class TestUpsertRatingDowngrade:
    def test_inserts_a_new_rating_row(self, session: Session) -> None:
        event = MarketEvent(
            event_id="evt-1",
            event_type=MarketEventType.DOWNGRADE,
            counterparty_id="CP-4",
            description="CP-4 downgraded A -> BBB",
            occurred_at=datetime(2026, 8, 10, tzinfo=UTC),
            new_rating_grade=RatingGrade.BBB,
        )

        upsert_rating_downgrade(session, event)

        row = session.get(RatingORM, "RTG-DG-CP-4")
        assert row is not None
        assert row.counterparty_id == "CP-4"
        assert row.grade == "BBB"
        assert row.rating_date == date(2026, 8, 10)

    def test_replaying_the_same_event_id_re_merges_without_duplicating(
        self, session: Session
    ) -> None:
        event = MarketEvent(
            event_id="evt-1",
            event_type=MarketEventType.DOWNGRADE,
            counterparty_id="CP-4",
            description="CP-4 downgraded A -> BBB",
            occurred_at=datetime(2026, 8, 10, tzinfo=UTC),
            new_rating_grade=RatingGrade.BBB,
        )

        upsert_rating_downgrade(session, event)
        upsert_rating_downgrade(session, event)

        assert session.query(RatingORM).count() == 1

    def test_no_counterparty_or_no_new_grade_is_a_safe_no_op(self, session: Session) -> None:
        no_cp = MarketEvent(
            event_id="evt-2",
            event_type=MarketEventType.DOWNGRADE,
            counterparty_id=None,
            description="unassigned",
            occurred_at=datetime.now(UTC),
            new_rating_grade=RatingGrade.BBB,
        )
        no_grade = MarketEvent(
            event_id="evt-3",
            event_type=MarketEventType.DOWNGRADE,
            counterparty_id="CP-4",
            description="no structured grade",
            occurred_at=datetime.now(UTC),
        )

        upsert_rating_downgrade(session, no_cp)
        upsert_rating_downgrade(session, no_grade)

        assert session.query(RatingORM).count() == 0


class TestHandleMarketEventMessage:
    def test_publishes_impact_set_for_downgrade(self, session: Session, settings: Settings) -> None:
        event = MarketEvent(
            event_id="evt-1",
            event_type=MarketEventType.DOWNGRADE,
            counterparty_id="CP-4",
            description="CP-4 downgraded A -> BBB",
            occurred_at=datetime.now(UTC),
            new_rating_grade=RatingGrade.BBB,
        )
        producer = MagicMock()

        impact = handle_market_event_message(session, event, producer, settings)

        assert impact is not None
        assert impact.counterparty_ids == ["CP-4"]
        producer.publish.assert_called_once_with(settings.kafka_topic_impact, impact, key="evt-1")
        producer.flush.assert_called_once()

    def test_downgrade_event_persists_the_new_rating(
        self, session: Session, settings: Settings
    ) -> None:
        event = MarketEvent(
            event_id="evt-1",
            event_type=MarketEventType.DOWNGRADE,
            counterparty_id="CP-4",
            description="CP-4 downgraded A -> BBB",
            occurred_at=datetime.now(UTC),
            new_rating_grade=RatingGrade.BBB,
        )
        producer = MagicMock()

        handle_market_event_message(session, event, producer, settings)

        row = session.get(RatingORM, "RTG-DG-CP-4")
        assert row is not None
        assert row.grade == "BBB"

    def test_replaying_the_same_event_is_a_no_op(
        self, session: Session, settings: Settings
    ) -> None:
        event = MarketEvent(
            event_id="evt-1",
            event_type=MarketEventType.DOWNGRADE,
            counterparty_id="CP-4",
            description="CP-4 downgraded A -> BBB",
            occurred_at=datetime.now(UTC),
            new_rating_grade=RatingGrade.BBB,
        )
        producer = MagicMock()

        handle_market_event_message(session, event, producer, settings)
        result = handle_market_event_message(session, event, producer, settings)

        assert result is None
        producer.publish.assert_called_once()


class TestHandleMessage:
    def test_dispatches_prices_topic_to_price_handler(
        self, session: Session, settings: Settings
    ) -> None:
        session.add(
            PriceHistoryORM(
                ticker="AAPL",
                price_date=date(2026, 7, 30),
                price=200.0,
                currency="USD",
                source="yfinance",
            )
        )
        session.commit()
        quote = _quote("AAPL", 202.0, datetime(2026, 7, 31, tzinfo=UTC))
        msg = MagicMock()
        msg.topic.return_value = settings.kafka_topic_prices
        msg.value.return_value = quote.model_dump_json().encode("utf-8")
        producer = MagicMock()

        result = handle_message(session, msg, producer, settings)

        assert result is None  # below threshold, but proves it decoded as a PriceQuote
        producer.publish.assert_not_called()

    def test_dispatches_events_topic_to_market_event_handler(
        self, session: Session, settings: Settings
    ) -> None:
        event = MarketEvent(
            event_id="evt-2",
            event_type=MarketEventType.DOWNGRADE,
            counterparty_id="CP-4",
            description="CP-4 downgraded A -> BBB",
            occurred_at=datetime.now(UTC),
        )
        msg = MagicMock()
        msg.topic.return_value = settings.kafka_topic_events
        msg.value.return_value = event.model_dump_json().encode("utf-8")
        producer = MagicMock()

        result = handle_message(session, msg, producer, settings)

        assert result is not None
        assert result.counterparty_ids == ["CP-4"]


def _fake_message(
    topic: str = "market.events",
    partition: int = 0,
    offset: int = 42,
    key: bytes | None = b"evt-1",
    value: bytes = b'{"some": "payload"}',
) -> MagicMock:
    msg = MagicMock()
    msg.topic.return_value = topic
    msg.partition.return_value = partition
    msg.offset.return_value = offset
    msg.key.return_value = key
    msg.value.return_value = value
    return msg


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """Unlike the module's `session` fixture (one shared Session), this
    yields a real factory -- _handle_with_retry opens a fresh Session per
    attempt, matching production's get_session_factory(settings) usage."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


class TestDeadLetterEvent:
    def test_builds_from_a_real_message_and_error(self) -> None:
        msg = _fake_message(topic="market.prices", partition=2, offset=7, key=b"AAPL")
        error = ValueError("boom")

        dead_letter = _dead_letter_event(msg, error, attempts=3)

        assert dead_letter.topic == "market.prices"
        assert dead_letter.partition == 2
        assert dead_letter.offset == 7
        assert dead_letter.key == "AAPL"
        assert dead_letter.value == '{"some": "payload"}'
        assert dead_letter.error_type == "ValueError"
        assert dead_letter.error_message == "boom"
        assert dead_letter.attempts == 3

    def test_handles_a_null_key(self) -> None:
        msg = _fake_message(key=None)

        dead_letter = _dead_letter_event(msg, ValueError("boom"), attempts=1)

        assert dead_letter.key is None


class TestPublishDeadLetter:
    def test_publishes_to_the_dead_letter_topic_and_flushes(self, settings: Settings) -> None:
        msg = _fake_message(topic="market.events", partition=0, offset=5)
        producer = MagicMock()

        _publish_dead_letter(
            msg, ValueError("boom"), attempts=3, producer=producer, settings=settings
        )

        producer.publish.assert_called_once()
        (topic, dead_letter), kwargs = producer.publish.call_args
        assert topic == settings.kafka_topic_dead_letter
        assert dead_letter.error_message == "boom"
        assert kwargs["key"] == "market.events:0:5"
        producer.flush.assert_called_once()

    def test_a_broker_failure_propagates_rather_than_being_swallowed(
        self, settings: Settings
    ) -> None:
        msg = _fake_message()
        producer = MagicMock()
        producer.flush.side_effect = ProducerDeliveryError("1 message(s) failed to deliver: []")

        with pytest.raises(ProducerDeliveryError):
            _publish_dead_letter(
                msg, ValueError("boom"), attempts=3, producer=producer, settings=settings
            )


class TestHandleWithRetry:
    def test_succeeds_on_first_attempt_without_retrying(
        self, session_factory: sessionmaker[Session], settings: Settings
    ) -> None:
        msg = _fake_message()
        producer = MagicMock()
        impact = ImpactSet(
            event_id="evt-1",
            event_type=MarketEventType.DOWNGRADE,
            counterparty_ids=["CP-1"],
            reason="test",
            occurred_at=datetime.now(UTC),
        )
        sleep = MagicMock()

        with patch("streaming.event_agent.handle_message", return_value=impact) as mocked:
            result = _handle_with_retry(msg, producer, settings, session_factory, sleep=sleep)

        assert result is impact
        assert mocked.call_count == 1
        sleep.assert_not_called()
        producer.publish.assert_not_called()  # never dead-lettered

    def test_retries_a_transient_failure_then_succeeds(
        self, session_factory: sessionmaker[Session], settings: Settings
    ) -> None:
        msg = _fake_message()
        producer = MagicMock()
        sleep = MagicMock()

        with patch(
            "streaming.event_agent.handle_message",
            side_effect=[RuntimeError("db hiccup"), None],
        ) as mocked:
            result = _handle_with_retry(msg, producer, settings, session_factory, sleep=sleep)

        assert result is None  # the (successful) second call's own return value
        assert mocked.call_count == 2
        sleep.assert_called_once_with(1.0)  # backoff_seconds * 2**0
        producer.publish.assert_not_called()

    def test_exhausts_retries_and_dead_letters_the_message(
        self, session_factory: sessionmaker[Session], settings: Settings
    ) -> None:
        msg = _fake_message(topic="market.events", partition=1, offset=9)
        producer = MagicMock()
        sleep = MagicMock()

        with patch(
            "streaming.event_agent.handle_message", side_effect=RuntimeError("always fails")
        ) as mocked:
            result = _handle_with_retry(
                msg, producer, settings, session_factory, max_attempts=3, sleep=sleep
            )

        assert result is None
        assert mocked.call_count == 3
        # exponential backoff between attempts 1->2 and 2->3, none after the last
        assert sleep.call_args_list == [((1.0,),), ((2.0,),)]
        producer.publish.assert_called_once()
        (topic, dead_letter), _ = producer.publish.call_args
        assert topic == settings.kafka_topic_dead_letter
        assert dead_letter.attempts == 3
        assert dead_letter.error_message == "always fails"
        producer.flush.assert_called_once()

    def test_uses_a_fresh_session_per_attempt(
        self, session_factory: sessionmaker[Session], settings: Settings
    ) -> None:
        """A session that raised mid-transaction must not be reused for the
        next attempt -- assert handle_message actually receives a live,
        usable Session object on every call, not the same broken one twice."""
        msg = _fake_message()
        producer = MagicMock()
        seen_sessions: list[Session] = []

        def fake_handle_message(session: Session, *_args: object, **_kwargs: object) -> None:
            seen_sessions.append(session)
            if len(seen_sessions) < 2:
                raise RuntimeError("first attempt fails")

        with patch("streaming.event_agent.handle_message", side_effect=fake_handle_message):
            _handle_with_retry(msg, producer, settings, session_factory, sleep=MagicMock())

        assert len(seen_sessions) == 2
        assert seen_sessions[0] is not seen_sessions[1]
