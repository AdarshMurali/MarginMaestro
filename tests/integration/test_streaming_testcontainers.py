"""Streaming integration tests (MM-33) against a real, ephemeral Redpanda
broker via testcontainers -- not marked `live` (that marker is for tests
hitting real external network APIs like yfinance/CoinGecko); this needs only
a local Docker daemon, which GitHub-hosted runners already provide, so it
runs as part of the normal CI suite. Skips gracefully if Docker itself isn't
reachable (e.g. Docker Desktop not started locally).
"""

import time
from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from config.settings import Settings
from persistence.db.models import Base, CounterpartyORM, PortfolioORM, PositionORM, PriceHistoryORM
from streaming.consumer import ConsumerError, EventConsumer, decode
from streaming.event_agent import handle_price_message
from streaming.market_feed import PriceQuote
from streaming.producer import EventProducer
from streaming.schemas import ImpactSet, MarketEventType
from streaming.simulator import run_scenario


@pytest.fixture(scope="module")
def redpanda():
    try:
        from testcontainers.community.kafka import RedpandaContainer
    except ImportError:
        pytest.skip("testcontainers[kafka] is not installed")

    from docker.errors import DockerException

    try:
        container = RedpandaContainer()
        container.start()
    except DockerException as exc:
        pytest.skip(f"Docker not reachable for testcontainers: {exc}")

    yield container
    container.stop()


@pytest.fixture
def settings(redpanda) -> Settings:
    # Unique topic names per test -- the broker is module-scoped (shared across
    # tests for speed), so a fresh consumer group's auto.offset.reset=earliest
    # would otherwise replay another test's leftover messages on a shared topic.
    suffix = uuid4().hex[:8]
    return Settings(
        _env_file=None,
        kafka_bootstrap_servers=redpanda.get_bootstrap_server(),
        kafka_topic_prices=f"test.market.prices.{suffix}",
        kafka_topic_events=f"test.market.events.{suffix}",
        kafka_topic_impact=f"test.market.impact.{suffix}",
    )


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _poll_until_message(
    consumer: EventConsumer, deadline_seconds: float = 30.0, timeout: float = 1.0
):
    """Retries past the transient "unknown topic" error librdkafka can surface
    right after a topic is auto-created but before metadata has propagated to
    this consumer -- not a real broker fault, so not something EventConsumer
    itself should swallow (a genuinely missing topic later should still raise).
    Bounded by wall-clock time rather than attempt count, since those retries
    shouldn't eat into the budget for the real message to arrive."""
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            msg = consumer.poll(timeout)
        except ConsumerError as exc:
            if "UNKNOWN_TOPIC_OR_PART" in str(exc):
                continue
            raise
        if msg is not None:
            return msg
    raise AssertionError("no message arrived within the polling window")


class TestProducerConsumerRoundTrip:
    def test_produced_message_is_consumed_with_identical_content(self, settings: Settings) -> None:
        quote = PriceQuote(ticker="AAPL", price=200.0, as_of=datetime.now(UTC), source="yfinance")
        producer = EventProducer(settings)
        producer.publish(settings.kafka_topic_prices, quote, key="AAPL")
        producer.flush()

        with EventConsumer(
            topics=[settings.kafka_topic_prices], group_id="test-roundtrip", settings=settings
        ) as consumer:
            msg = _poll_until_message(consumer)
            consumer.commit(msg)

        assert decode(msg, PriceQuote) == quote


class TestExitCriteria:
    def test_price_shock_scenario_produces_an_impact_set_on_the_stream(
        self, settings: Settings, db_session: Session
    ) -> None:
        # Ground truth an Event Agent needs to classify + map the scenario.
        db_session.add(
            CounterpartyORM(id="CP-1", name="CP-1", type="Bank", country="United States")
        )
        db_session.add(PortfolioORM(id="PF-CP-1", counterparty_id="CP-1", currency="USD"))
        db_session.add(
            PositionORM(
                id="POS-CP-1-TSLA",
                portfolio_id="PF-CP-1",
                ticker="TSLA",
                asset_class="equity",
                quantity=100,
                trade_date=date(2026, 1, 1),
            )
        )
        db_session.add(
            PriceHistoryORM(
                ticker="TSLA",
                price_date=date(2026, 7, 30),
                price=100.0,
                currency="USD",
                source="yfinance",
            )
        )
        db_session.commit()

        base_feed = MagicMock()
        base_feed.get_prices.return_value = {
            "TSLA": PriceQuote(
                ticker="TSLA", price=100.0, as_of=datetime.now(UTC), source="yfinance"
            ),
            "NVDA": PriceQuote(
                ticker="NVDA", price=50.0, as_of=datetime.now(UTC), source="yfinance"
            ),
        }
        run_scenario(
            MarketEventType.PRICE_SHOCK,
            producer=EventProducer(settings),
            base_feed=base_feed,
            settings=settings,
        )

        with EventConsumer(
            topics=[settings.kafka_topic_prices],
            group_id="test-exit-criteria-prices",
            settings=settings,
        ) as price_consumer:
            msg = _poll_until_message(price_consumer)
            quote = decode(msg, PriceQuote)
            price_consumer.commit(msg)

        impact = handle_price_message(db_session, quote, EventProducer(settings), settings)
        assert impact is not None
        assert impact.event_type == MarketEventType.PRICE_SHOCK
        assert impact.counterparty_ids == ["CP-1"]

        with EventConsumer(
            topics=[settings.kafka_topic_impact],
            group_id="test-exit-criteria-impact",
            settings=settings,
        ) as impact_consumer:
            msg = _poll_until_message(impact_consumer)
            on_stream = decode(msg, ImpactSet)
            impact_consumer.commit(msg)

        assert on_stream == impact


class TestIdempotencyUnderRedelivery:
    def test_uncommitted_offset_redelivers_and_handler_does_not_double_publish(
        self, settings: Settings, db_session: Session
    ) -> None:
        db_session.add(
            PriceHistoryORM(
                ticker="TSLA",
                price_date=date(2026, 7, 30),
                price=100.0,
                currency="USD",
                source="yfinance",
            )
        )
        db_session.commit()

        quote = PriceQuote(ticker="TSLA", price=88.0, as_of=datetime.now(UTC), source="yfinance")
        EventProducer(settings).publish(settings.kafka_topic_prices, quote, key="TSLA")
        EventProducer(settings).flush()

        group_id = "test-idempotency"
        handler_producer = MagicMock()

        # First delivery: handle it, but never commit -- simulates a crash
        # between "did the work" and "told Redpanda I did the work".
        with EventConsumer(
            topics=[settings.kafka_topic_prices], group_id=group_id, settings=settings
        ) as consumer:
            msg = _poll_until_message(consumer)
            first = handle_price_message(
                db_session, decode(msg, PriceQuote), handler_producer, settings
            )

        # Reconnecting with the same group id: Redpanda redelivers the
        # uncommitted message from scratch.
        with EventConsumer(
            topics=[settings.kafka_topic_prices], group_id=group_id, settings=settings
        ) as consumer:
            msg = _poll_until_message(consumer)
            second = handle_price_message(
                db_session, decode(msg, PriceQuote), handler_producer, settings
            )
            consumer.commit(msg)

        assert first is not None
        assert second is None
        handler_producer.publish.assert_called_once()
