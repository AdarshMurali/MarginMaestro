from typing import Protocol

from pydantic import BaseModel


class DeliveryReceipt(BaseModel):
    text: str
    channel: str
    message_id: str


class Notifier(Protocol):
    """Sends an already-drafted, already-approved notice. Never called before
    the human approval gate (CLAUDE.md golden rule 5)."""

    def send(self, text: str) -> DeliveryReceipt:
        """Deliver `text`; raise if the channel isn't configured or delivery fails."""
        ...
