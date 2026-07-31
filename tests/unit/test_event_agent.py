from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from config.settings import Settings
from persistence.db.models import (
    Base,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
)
from streaming.event_agent import (
    affected_counterparties,
    classify_price_move,
    handle_market_event_message,
    handle_message,
    handle_price_message,
    is_already_processed,
    latest_close_before,
    price_event_id,
)
from streaming.market_feed import PriceQuote
from streaming.schemas import MarketEvent, MarketEventType


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

    def test_no_prior_close_is_a_safe_no_op(self, session: Session, settings: Settings) -> None:
        quote = _quote("TSLA", 88.0, datetime(2026, 7, 31, 14, 0, tzinfo=UTC))
        producer = MagicMock()

        result = handle_price_message(session, quote, producer, settings)

        assert result is None
        producer.publish.assert_not_called()
        assert is_already_processed(session, price_event_id(quote))

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


class TestHandleMarketEventMessage:
    def test_publishes_impact_set_for_downgrade(self, session: Session, settings: Settings) -> None:
        event = MarketEvent(
            event_id="evt-1",
            event_type=MarketEventType.DOWNGRADE,
            counterparty_id="CP-4",
            description="CP-4 downgraded A -> BBB",
            occurred_at=datetime.now(UTC),
        )
        producer = MagicMock()

        impact = handle_market_event_message(session, event, producer, settings)

        assert impact is not None
        assert impact.counterparty_ids == ["CP-4"]
        producer.publish.assert_called_once_with(settings.kafka_topic_impact, impact, key="evt-1")
        producer.flush.assert_called_once()

    def test_replaying_the_same_event_is_a_no_op(
        self, session: Session, settings: Settings
    ) -> None:
        event = MarketEvent(
            event_id="evt-1",
            event_type=MarketEventType.DOWNGRADE,
            counterparty_id="CP-4",
            description="CP-4 downgraded A -> BBB",
            occurred_at=datetime.now(UTC),
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
