"""MM-120 end to end on the Pub/Sub emulator: a price tick published to
Pub/Sub is pulled by the Event Agent, lands in `latest_prices`, and a big move
publishes exactly one impact set even when the tick arrives twice.

Runs in CI's `pubsub` job (REQUIRE_PUBSUB=1); skips locally without
PUBSUB_EMULATOR_HOST. The database is in-memory SQLite -- the Postgres path
of the same handlers is covered by the `migrations` job."""

import os
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from config.settings import Settings
from persistence.db.models import (
    Base,
    CounterpartyORM,
    LatestPriceORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
)
from streaming.market_feed import PriceQuote

PROJECT = "marginmaestro-demo"


@pytest.fixture
def emulator() -> None:
    if not os.environ.get("PUBSUB_EMULATOR_HOST"):
        if os.environ.get("REQUIRE_PUBSUB") == "1":
            raise RuntimeError("REQUIRE_PUBSUB=1 but PUBSUB_EMULATOR_HOST is not set")
        pytest.skip("needs PUBSUB_EMULATOR_HOST (docker compose up -d pubsub)")


def _settings() -> Settings:
    run = uuid.uuid4().hex[:8]  # isolated topics per test run
    return Settings(
        _env_file=None,
        event_bus="pubsub",
        gcp_project_id=PROJECT,
        kafka_topic_prices=f"prices.{run}",
        kafka_topic_events=f"events.{run}",
        kafka_topic_impact=f"impact.{run}",
        kafka_topic_dead_letter=f"dead-letter.{run}",
    )


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(CounterpartyORM(id="CP-3", name="Test CP", type="hedge_fund", country="US"))
        session.add(PortfolioORM(id="PF-3", counterparty_id="CP-3"))
        session.add(
            PositionORM(
                id="POS-1",
                portfolio_id="PF-3",
                ticker="MU",
                asset_class="equity",
                quantity=100,
                trade_date=date(2026, 1, 2),
            )
        )
        session.add(
            PriceHistoryORM(ticker="MU", price_date=date(2026, 10, 1), price=100, source="yfinance")
        )
        session.commit()
    return factory


def test_tick_lands_in_latest_prices_and_raises_one_impact_set(emulator):
    from google.cloud.pubsub_v1 import SubscriberClient

    from adapters.pubsub_adapter import PubSubEventBus
    from adapters.pubsub_admin import ensure_subscriptions, ensure_topics, event_agent_subscription
    from streaming.pubsub_event_agent import drain_once

    settings = _settings()
    topics = [settings.kafka_topic_prices, settings.kafka_topic_events]
    ensure_topics(PROJECT, [*topics, settings.kafka_topic_impact, settings.kafka_topic_dead_letter])
    ensure_subscriptions(PROJECT, topics)
    subscriber = SubscriberClient()
    impact_sub = subscriber.subscription_path(PROJECT, f"{settings.kafka_topic_impact}.test")
    subscriber.create_subscription(
        request={
            "name": impact_sub,
            "topic": subscriber.topic_path(PROJECT, settings.kafka_topic_impact),
        }
    )
    subscriptions = {
        topic: subscriber.subscription_path(PROJECT, event_agent_subscription(topic))
        for topic in topics
    }

    # The scheduler's publish, then the same tick again (a duplicate delivery).
    tick = PriceQuote(
        ticker="MU",
        price=80.0,
        currency="USD",
        source="yfinance",
        as_of=datetime(2026, 10, 2, 15, 0, tzinfo=UTC),
    )
    bus = PubSubEventBus(PROJECT)
    bus.publish(settings.kafka_topic_prices, tick, key="MU")
    bus.publish(settings.kafka_topic_prices, tick, key="MU")
    assert bus.flush() == 0

    session_factory = _database()
    handled = 0
    for _ in range(10):
        handled += drain_once(subscriber, subscriptions, bus, settings, session_factory)
        if handled >= 2:
            break
    assert handled == 2

    with session_factory() as session:
        row = session.execute(select(LatestPriceORM)).scalar_one()
    assert (row.ticker, row.price) == ("MU", 80.0)

    impacts = []
    for _ in range(5):
        response = subscriber.pull(request={"subscription": impact_sub, "max_messages": 10})
        impacts += [m.message.data.decode() for m in response.received_messages]
        if impacts:
            break
    assert len(impacts) == 1
    assert '"counterparty_ids":["CP-3"]' in impacts[0]
