from typing import Any

import structlog
from confluent_kafka import Producer
from pydantic import BaseModel

from config.settings import Settings, get_settings

logger = structlog.get_logger()


class ProducerDeliveryError(Exception):
    """Raised on flush() if one or more messages failed to deliver to Redpanda."""


class EventProducer:
    """Thin JSON producer: one Pydantic model in, one Kafka message out.

    Idempotent by construction (`enable.idempotence=True`) -- retries on
    transient broker errors never duplicate a message on the topic.
    """

    def __init__(self, settings: Settings | None = None, producer: Producer | None = None) -> None:
        settings = settings or get_settings()
        self._producer = producer or Producer(
            {
                "bootstrap.servers": settings.kafka_bootstrap_servers,
                "enable.idempotence": True,
                "acks": "all",
            }
        )
        self._delivery_errors: list[str] = []

    def publish(self, topic: str, value: BaseModel, key: str | None = None) -> None:
        self._producer.produce(
            topic,
            key=key.encode("utf-8") if key is not None else None,
            value=value.model_dump_json().encode("utf-8"),
            callback=self._on_delivery,
        )
        self._producer.poll(0)

    def flush(self, timeout: float = 10.0) -> int:
        """Blocks until all queued messages are delivered. Raises if any failed --
        per CLAUDE.md's "fail loud, never silently swallow" rule."""
        remaining = self._producer.flush(timeout)
        if self._delivery_errors:
            errors, self._delivery_errors = self._delivery_errors, []
            raise ProducerDeliveryError(f"{len(errors)} message(s) failed to deliver: {errors}")
        return remaining

    def _on_delivery(self, err: Any, msg: Any) -> None:
        if err is not None:
            logger.error("kafka_delivery_failed", error=str(err))
            self._delivery_errors.append(str(err))
