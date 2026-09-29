from typing import Protocol

from pydantic import BaseModel


class EventBus(Protocol):
    """Publishes one Pydantic model per message. Delivery is at-least-once on
    every backend, so consumers must stay idempotent (CLAUDE.md)."""

    def publish(self, topic: str, value: BaseModel, key: str | None = None) -> None:
        """Queue a message. `key` keeps ordering per key (e.g. counterparty)."""
        ...

    def flush(self, timeout: float = 10.0) -> int:
        """Block until queued messages are delivered; raise if any failed.
        Returns the number still undelivered."""
        ...
