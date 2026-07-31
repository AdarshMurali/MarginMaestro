from types import TracebackType
from typing import Self, TypeVar

from confluent_kafka import Consumer, KafkaError, Message
from pydantic import BaseModel

from config.settings import Settings, get_settings

T = TypeVar("T", bound=BaseModel)


class ConsumerError(Exception):
    """Raised when Redpanda reports a non-EOF error while polling."""


class EventConsumer:
    """Thin consumer wrapper: poll() returns a raw Message (or None), so callers
    control exactly when the offset is committed -- only after the message has
    been fully handled, per CLAUDE.md's idempotent-event-processing rule."""

    def __init__(
        self,
        topics: list[str],
        group_id: str,
        settings: Settings | None = None,
        consumer: Consumer | None = None,
    ) -> None:
        settings = settings or get_settings()
        self._consumer = consumer or Consumer(
            {
                "bootstrap.servers": settings.kafka_bootstrap_servers,
                "group.id": group_id,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        self._consumer.subscribe(topics)

    def poll(self, timeout: float = 1.0) -> Message | None:
        msg = self._consumer.poll(timeout)
        if msg is None:
            return None
        error = msg.error()
        if error is not None:
            if error.code() == KafkaError._PARTITION_EOF:
                return None
            raise ConsumerError(str(error))
        return msg

    def commit(self, message: Message) -> None:
        self._consumer.commit(message=message, asynchronous=False)

    def close(self) -> None:
        self._consumer.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def decode(message: Message, model: type[T]) -> T:
    value = message.value()
    if value is None:
        raise ConsumerError("message has no value to decode (tombstone or empty payload)")
    return model.model_validate_json(value)
