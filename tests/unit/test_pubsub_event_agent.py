"""MM-120: the Event Agent over Pub/Sub pull, with a mocked subscriber and an
in-memory database (the emulator-backed run is in
tests/contract/test_pubsub_event_agent_emulator.py)."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from adapters.in_memory import InMemoryEventBus
from adapters.pubsub_admin import ensure_subscriptions, event_agent_subscription
from config.settings import Settings
from persistence.db.models import (
    Base,
    CounterpartyORM,
    LatestPriceORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
)
from streaming import pubsub_event_agent
from streaming.event_agent import _dead_letter_event
from streaming.inbound import EmptyMessageError, PubSubInbound, decode
from streaming.market_feed import PriceQuote
from streaming.pubsub_event_agent import drain_once

AS_OF = datetime(2026, 10, 2, 15, 0, tzinfo=UTC)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
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


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, event_bus="pubsub", gcp_project_id="proj")


def _received(data: bytes, ordering_key: str = "", ack_id: str = "ack-1"):
    return SimpleNamespace(
        ack_id=ack_id, message=SimpleNamespace(data=data, ordering_key=ordering_key)
    )


def _tick(price: float) -> bytes:
    return (
        PriceQuote(ticker="MU", price=price, currency="USD", source="yfinance", as_of=AS_OF)
        .model_dump_json()
        .encode()
    )


def _subscriber(*batches):
    """A subscriber whose pull() returns the given batches in turn, then empty."""
    subscriber = MagicMock()
    responses = [SimpleNamespace(received_messages=list(batch)) for batch in batches]
    subscriber.pull.side_effect = responses + [SimpleNamespace(received_messages=[])] * 10
    return subscriber


SUBS = {"market.prices": "projects/proj/subscriptions/event-agent.market.prices"}


def test_a_tick_updates_latest_prices_and_is_acked(session_factory, settings):
    subscriber = _subscriber([_received(_tick(101.0), "MU")])
    bus = InMemoryEventBus()

    assert drain_once(subscriber, SUBS, bus, settings, session_factory) == 1

    with session_factory() as session:
        row = session.execute(select(LatestPriceORM)).scalar_one()
    assert (row.ticker, row.price) == ("MU", 101.0)
    assert bus.delivered == []  # a 1% move is not an event
    subscriber.acknowledge.assert_called_once_with(
        request={"subscription": SUBS["market.prices"], "ack_ids": ["ack-1"]}
    )


def test_a_big_move_publishes_one_impact_set_even_when_redelivered(session_factory, settings):
    tick = _tick(80.0)  # -20% vs prior close
    subscriber = _subscriber([_received(tick, "MU", "a1")], [_received(tick, "MU", "a2")])
    bus = InMemoryEventBus()

    drain_once(subscriber, SUBS, bus, settings, session_factory)
    drain_once(subscriber, SUBS, bus, settings, session_factory)

    impacts = [entry for entry in bus.delivered if entry[0] == settings.kafka_topic_impact]
    assert len(impacts) == 1
    assert '"counterparty_ids":["CP-3"]' in impacts[0][2]
    assert subscriber.acknowledge.call_count == 2


def test_a_poison_message_is_dead_lettered_then_acked(session_factory, settings):
    subscriber = _subscriber([_received(b"not json", "MU")])
    bus = InMemoryEventBus()

    with patch("streaming.event_agent.time.sleep"):
        drain_once(subscriber, SUBS, bus, settings, session_factory)

    [(topic, key, body)] = bus.delivered
    assert topic == settings.kafka_topic_dead_letter
    assert key == "market.prices:MU"
    assert '"partition":null' in body and '"value":"not json"' in body
    subscriber.acknowledge.assert_called_once()


def test_a_failed_dead_letter_publish_leaves_the_message_unacked(session_factory, settings):
    subscriber = _subscriber([_received(b"not json", "MU")])
    bus = MagicMock()
    bus.flush.side_effect = RuntimeError("pubsub down")

    with patch("streaming.event_agent.time.sleep"), pytest.raises(RuntimeError):
        drain_once(subscriber, SUBS, bus, settings, session_factory)

    subscriber.acknowledge.assert_not_called()  # redelivered later


def test_an_empty_pull_that_times_out_is_skipped(session_factory, settings):
    from google.api_core.exceptions import DeadlineExceeded

    subscriber = MagicMock()
    subscriber.pull.side_effect = DeadlineExceeded("no messages")

    assert drain_once(subscriber, SUBS, InMemoryEventBus(), settings, session_factory) == 0


def test_run_requires_pubsub_and_a_project():
    with pytest.raises(ValueError, match="EVENT_BUS=pubsub"):
        pubsub_event_agent.run(Settings(_env_file=None), subscriber=MagicMock())


def test_run_pulls_from_both_subscriptions(settings, monkeypatch):
    monkeypatch.delenv("PUBSUB_EMULATOR_HOST", raising=False)
    subscriber = _subscriber()
    subscriber.subscription_path.side_effect = lambda p, s: f"projects/{p}/subscriptions/{s}"

    with (
        patch.object(pubsub_event_agent, "get_session_factory"),
        patch.object(pubsub_event_agent, "get_event_bus"),
        patch.object(pubsub_event_agent.time, "sleep") as sleep,
    ):
        pubsub_event_agent.run(settings, subscriber=subscriber, max_iterations=1)

    pulled = [call.kwargs["request"]["subscription"] for call in subscriber.pull.call_args_list]
    assert pulled == [
        "projects/proj/subscriptions/event-agent.market.prices",
        "projects/proj/subscriptions/event-agent.market.events",
    ]
    sleep.assert_called_once()  # idle: nothing was handled
    subscriber.create_subscription.assert_not_called()  # real GCP: Terraform owns them


def test_run_creates_subscriptions_on_the_emulator(settings, monkeypatch):
    monkeypatch.setenv("PUBSUB_EMULATOR_HOST", "localhost:8085")
    with (
        patch.object(pubsub_event_agent, "ensure_subscriptions") as ensure,
        patch.object(pubsub_event_agent, "get_session_factory"),
        patch.object(pubsub_event_agent, "get_event_bus"),
        patch.object(pubsub_event_agent.time, "sleep"),
    ):
        pubsub_event_agent.run(settings, subscriber=_subscriber(), max_iterations=1)

    assert ensure.call_args.args == ("proj", ["market.prices", "market.events"])


def test_pubsub_inbound_maps_ordering_key_and_has_no_offset():
    inbound = PubSubInbound("market.prices", SimpleNamespace(data=b"{}", ordering_key="MU"))

    assert (inbound.topic(), inbound.key(), inbound.value()) == ("market.prices", b"MU", b"{}")
    assert (inbound.partition(), inbound.offset()) == (None, None)
    no_key = PubSubInbound("t", SimpleNamespace(data=b"", ordering_key=""))
    assert (no_key.key(), no_key.value()) == (None, None)
    with pytest.raises(EmptyMessageError):
        decode(no_key, PriceQuote)


def test_dead_letter_event_from_a_pubsub_message():
    inbound = PubSubInbound("market.prices", SimpleNamespace(data=b"bad", ordering_key="MU"))

    dead_letter = _dead_letter_event(inbound, ValueError("boom"), attempts=3)

    assert (dead_letter.topic, dead_letter.partition, dead_letter.offset) == (
        "market.prices",
        None,
        None,
    )
    assert (dead_letter.key, dead_letter.value) == ("MU", "bad")


def test_ensure_subscriptions_creates_missing_ordered_ones_only():
    from google.api_core.exceptions import AlreadyExists

    subscriber = MagicMock()
    subscriber.subscription_path.side_effect = lambda p, s: f"projects/{p}/subscriptions/{s}"
    subscriber.create_subscription.side_effect = [None, AlreadyExists("exists")]

    created = ensure_subscriptions("p", ["market.prices", "market.events"], subscriber=subscriber)

    assert created == [event_agent_subscription("market.prices")]
    request = subscriber.create_subscription.call_args_list[0].kwargs["request"]
    assert request["enable_message_ordering"] is True
    assert request["topic"] == "projects/p/topics/market.prices"
