"""EventBus contract (MM-102). Pub/Sub joins in G4. Kafka needs a running
broker (docker compose), so it's marked `live`."""

import pytest
from pydantic import BaseModel

from adapters.in_memory import InMemoryEventBus
from config.settings import Settings


class _Event(BaseModel):
    event_id: str
    counterparty_id: str


def _kafka():
    from streaming.producer import EventProducer

    return EventProducer(Settings(_env_file=None))


@pytest.fixture(
    params=[
        pytest.param(InMemoryEventBus, id="in-memory"),
        pytest.param(_kafka, id="kafka", marks=pytest.mark.live),
    ]
)
def bus(request):
    return request.param()


def test_publish_then_flush_delivers_everything(bus):
    bus.publish("contract.test", _Event(event_id="e1", counterparty_id="CP-3"), key="CP-3")
    bus.publish("contract.test", _Event(event_id="e2", counterparty_id="CP-4"))

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
