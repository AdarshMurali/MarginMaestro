"""MM-119: Pub/Sub EventBus adapter with a mocked publisher (the emulator-backed
contract runs in tests/contract/test_event_bus_contract.py)."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from adapters import factory
from adapters.pubsub_adapter import PubSubDeliveryError, PubSubEventBus
from config.settings import Settings


class _Quote(BaseModel):
    ticker: str
    price: float


def _publisher(failing: set[str] = frozenset()):
    publisher = MagicMock()
    publisher.topic_path.side_effect = lambda project, topic: f"projects/{project}/topics/{topic}"

    def publish(topic_path, data, ordering_key=""):
        future = MagicMock()
        if ordering_key in failing:
            future.result.side_effect = RuntimeError("publish failed")
        else:
            future.result.return_value = "msg-id"
        return future

    publisher.publish.side_effect = publish
    return publisher


def test_publishes_json_with_the_key_as_ordering_key():
    publisher = _publisher()
    bus = PubSubEventBus("proj-x", publisher=publisher)

    bus.publish("market.prices", _Quote(ticker="MU", price=101.5), key="MU")

    args, kwargs = publisher.publish.call_args
    assert args == ("projects/proj-x/topics/market.prices", b'{"ticker":"MU","price":101.5}')
    assert kwargs == {"ordering_key": "MU"}


def test_no_key_means_no_ordering_key():
    publisher = _publisher()
    PubSubEventBus("p", publisher=publisher).publish("t", _Quote(ticker="A", price=1))

    assert publisher.publish.call_args.kwargs == {"ordering_key": ""}


def test_flush_waits_for_every_publish():
    publisher = _publisher()
    bus = PubSubEventBus("p", publisher=publisher)
    bus.publish("t", _Quote(ticker="A", price=1), key="A")
    bus.publish("t", _Quote(ticker="B", price=2), key="B")

    assert bus.flush() == 0
    assert bus.flush() == 0  # nothing left pending


def test_failed_publish_raises_and_resumes_the_ordering_key():
    publisher = _publisher(failing={"B"})
    bus = PubSubEventBus("p", publisher=publisher)
    bus.publish("t", _Quote(ticker="A", price=1), key="A")
    bus.publish("t", _Quote(ticker="B", price=2), key="B")

    with pytest.raises(PubSubDeliveryError, match="1 message"):
        bus.flush()
    publisher.resume_publish.assert_called_once_with("projects/p/topics/t", "B")


def test_factory_builds_pubsub_for_the_project():
    with patch("adapters.pubsub_adapter._ordered_publisher", return_value=_publisher()):
        bus = factory.get_event_bus(
            Settings(_env_file=None, event_bus="pubsub", gcp_project_id="proj-x")
        )
    assert isinstance(bus, PubSubEventBus)


def test_factory_pubsub_requires_a_project():
    with pytest.raises(ValueError, match="GCP_PROJECT_ID"):
        factory.get_event_bus(Settings(_env_file=None, event_bus="pubsub"))


def test_default_publisher_enables_message_ordering():
    with patch("google.cloud.pubsub_v1.PublisherClient") as client_cls:
        from adapters.pubsub_adapter import _ordered_publisher

        _ordered_publisher()

    assert client_cls.call_args.kwargs["publisher_options"].enable_message_ordering is True


def test_admin_creates_missing_topics_only():
    from google.api_core.exceptions import AlreadyExists

    from adapters.pubsub_admin import ensure_topics, event_topics

    publisher = MagicMock()
    publisher.topic_path.side_effect = lambda p, t: f"projects/{p}/topics/{t}"
    publisher.create_topic.side_effect = [None, AlreadyExists("exists")]

    assert ensure_topics("p", ["a", "b"], publisher=publisher) == ["a"]
    assert event_topics(Settings(_env_file=None)) == [
        "market.prices",
        "market.events",
        "market.impact",
        "margin.calls",
        "market.dead-letter",
    ]
