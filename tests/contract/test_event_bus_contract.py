"""EventBus contract (MM-102). Kafka needs a running broker (docker compose),
so it's marked `live`. Pub/Sub (MM-119) runs against the Pub/Sub emulator
when PUBSUB_EMULATOR_HOST is set (CI's `pubsub` job sets it and REQUIRE_PUBSUB=1
so a missing emulator fails instead of skipping); otherwise it skips."""

import os
import uuid

import pytest
from pydantic import BaseModel

from adapters.in_memory import InMemoryEventBus
from config.settings import Settings

PROJECT = "marginmaestro-demo"
CONTRACT_TOPIC = "contract.test"


class _Event(BaseModel):
    event_id: str
    counterparty_id: str


def _kafka():
    from streaming.producer import EventProducer

    return EventProducer(Settings(_env_file=None))


def _require_emulator() -> None:
    if not os.environ.get("PUBSUB_EMULATOR_HOST"):
        if os.environ.get("REQUIRE_PUBSUB") == "1":
            raise RuntimeError("REQUIRE_PUBSUB=1 but PUBSUB_EMULATOR_HOST is not set")
        pytest.skip("Pub/Sub contract needs PUBSUB_EMULATOR_HOST (docker compose up -d pubsub)")


def _pubsub():
    _require_emulator()
    from adapters.pubsub_adapter import PubSubEventBus
    from adapters.pubsub_admin import ensure_topics

    ensure_topics(PROJECT, [CONTRACT_TOPIC])
    return PubSubEventBus(PROJECT)


@pytest.fixture(
    params=[
        pytest.param(InMemoryEventBus, id="in-memory"),
        pytest.param(_kafka, id="kafka", marks=pytest.mark.live),
        pytest.param(_pubsub, id="pubsub"),
    ]
)
def bus(request):
    return request.param()


def test_publish_then_flush_delivers_everything(bus):
    bus.publish(CONTRACT_TOPIC, _Event(event_id="e1", counterparty_id="CP-3"), key="CP-3")
    bus.publish(CONTRACT_TOPIC, _Event(event_id="e2", counterparty_id="CP-4"))

    assert bus.flush(timeout=10.0) == 0


def test_flush_with_nothing_queued_is_a_no_op(bus):
    assert bus.flush(timeout=1.0) == 0


def test_in_memory_bus_records_topic_key_and_json_body():
    bus = InMemoryEventBus()
    bus.publish("margin.calls", _Event(event_id="e1", counterparty_id="CP-3"), key="CP-3")

    assert bus.delivered == []
    bus.flush()

    assert bus.delivered == [
        ("margin.calls", "CP-3", '{"event_id":"e1","counterparty_id":"CP-3"}'),
    ]
    assert bus.pending == []


def test_pubsub_messages_arrive_as_json_in_order_per_key():
    """End to end on the emulator: what we publish is what a subscriber gets,
    with the ordering key set and one key's messages in publish order."""
    _require_emulator()
    from google.cloud.pubsub_v1 import PublisherClient, SubscriberClient

    from adapters.pubsub_adapter import PubSubEventBus
    from adapters.pubsub_admin import ensure_topics

    topic = f"contract.order.{uuid.uuid4().hex[:8]}"
    ensure_topics(PROJECT, [topic])
    subscriber = SubscriberClient()
    subscription = subscriber.subscription_path(PROJECT, f"{topic}.sub")
    subscriber.create_subscription(
        request={
            "name": subscription,
            "topic": PublisherClient.topic_path(PROJECT, topic),
            "enable_message_ordering": True,
        }
    )

    bus = PubSubEventBus(PROJECT)
    for i in range(5):
        bus.publish(topic, _Event(event_id=f"e{i}", counterparty_id="CP-3"), key="CP-3")
    assert bus.flush() == 0

    received = []
    for _ in range(10):
        response = subscriber.pull(request={"subscription": subscription, "max_messages": 10})
        for message in response.received_messages:
            received.append((message.message.ordering_key, message.message.data.decode()))
        if response.received_messages:
            subscriber.acknowledge(
                request={
                    "subscription": subscription,
                    "ack_ids": [m.ack_id for m in response.received_messages],
                }
            )
        if len(received) >= 5:
            break

    assert [key for key, _ in received] == ["CP-3"] * 5
    assert [body for _, body in received] == [
        f'{{"event_id":"e{i}","counterparty_id":"CP-3"}}' for i in range(5)
    ]
