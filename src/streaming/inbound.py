"""Transport-neutral view of one inbound event (MM-120), so the Event Agent's
handling and dead-lettering run the same over Kafka and Pub/Sub.

A Kafka `confluent_kafka.Message` already has this shape. Pub/Sub messages are
wrapped by `PubSubInbound`; they have no partition or offset, so those are None.
"""

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class InboundMessage(Protocol):
    def topic(self) -> str | None: ...
    def partition(self) -> int | None: ...
    def offset(self) -> int | None: ...
    def key(self) -> bytes | None: ...
    def value(self) -> bytes | None: ...


class EmptyMessageError(Exception):
    """Raised when a message has no body to decode (tombstone or empty payload)."""


def decode(message: InboundMessage, model: type[T]) -> T:
    value = message.value()
    if value is None:
        raise EmptyMessageError("message has no value to decode (tombstone or empty payload)")
    return model.model_validate_json(value)


class PubSubInbound:
    """Wraps a pulled Pub/Sub message. Its ordering key plays the Kafka key's role."""

    def __init__(self, topic: str, message: Any) -> None:
        self._topic = topic
        self._message = message

    def topic(self) -> str | None:
        return self._topic

    def partition(self) -> int | None:
        return None

    def offset(self) -> int | None:
        return None

    def key(self) -> bytes | None:
        ordering_key = self._message.ordering_key
        return ordering_key.encode("utf-8") if ordering_key else None

    def value(self) -> bytes | None:
        return self._message.data or None
