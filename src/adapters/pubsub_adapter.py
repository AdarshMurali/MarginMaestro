"""`EventBus` over Google Cloud Pub/Sub (MM-119, ADR-0012) -- the GCP
counterpart to the Kafka `EventProducer`. Same topic names (`market.prices`,
`market.impact`, ...), so callers don't change; `EVENT_BUS=pubsub` selects it.

- One JSON message per Pydantic model, like Kafka.
- `key` becomes the Pub/Sub **ordering key**, so one ticker's / counterparty's
  events stay in order (subscriptions enable message ordering, G5).
- `flush()` waits for every publish and raises if any failed -- fail loud,
  same contract as the Kafka producer. A failed ordered publish pauses that
  key in the client, so the key is resumed for the next attempt.
- Local dev and CI use the Pub/Sub emulator (`PUBSUB_EMULATOR_HOST`).
"""

from typing import Any

import structlog
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


class PubSubDeliveryError(Exception):
    """Raised on flush() if one or more messages failed to publish."""


class PubSubEventBus:
    def __init__(self, project_id: str, publisher: Any | None = None) -> None:
        self._project_id = project_id
        self._publisher = publisher if publisher is not None else _ordered_publisher()
        self._pending: list[tuple[Any, str, str]] = []  # (future, topic_path, ordering_key)

    def publish(self, topic: str, value: BaseModel, key: str | None = None) -> None:
        topic_path = self._publisher.topic_path(self._project_id, topic)
        future = self._publisher.publish(
            topic_path,
            value.model_dump_json().encode("utf-8"),
            ordering_key=key or "",
        )
        self._pending.append((future, topic_path, key or ""))

    def flush(self, timeout: float = 10.0) -> int:
        pending, self._pending = self._pending, []
        errors: list[str] = []
        for future, topic_path, key in pending:
            try:
                future.result(timeout=timeout)
            # Every failure is collected, then raised together below.
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{topic_path}: {exc}")
                logger.error("pubsub_publish_failed", topic=topic_path, error=str(exc))
                if key:
                    self._publisher.resume_publish(topic_path, key)
        if errors:
            raise PubSubDeliveryError(f"{len(errors)} message(s) failed to publish: {errors}")
        return 0


def _ordered_publisher() -> Any:
    from google.cloud.pubsub_v1 import PublisherClient
    from google.cloud.pubsub_v1.types import PublisherOptions

    return PublisherClient(publisher_options=PublisherOptions(enable_message_ordering=True))
