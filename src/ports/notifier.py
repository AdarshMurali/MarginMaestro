"""Client notifier port (MM-102; structured notice added in G6, MM-118).

A notifier only ever sends a notice a human has already approved (CLAUDE.md
golden rule 5), and every value in it was computed and formatted by code
(ADR-0005): the WhatsApp template has no free text at all, and the Slack path
fills the model's placeholders from code (MM-116)."""

from typing import Literal, Protocol

from pydantic import BaseModel


class DeliveryReceipt(BaseModel):
    text: str
    channel: str
    message_id: str
    # "accepted": the provider took the message, delivery is confirmed later
    # (WhatsApp `statuses` webhook, ADR-0016 amendment). "sent": the provider
    # confirmed it synchronously (Slack).
    status: Literal["accepted", "sent"] = "sent"


class ClientNotice(BaseModel):
    """One margin-call notice for a counterparty, every field already
    formatted by code. The WhatsApp template fills its four body variables
    in this order: reference, counterparty_name, amount, deadline."""

    counterparty_id: str
    reference: str  # e.g. "MC-1A2B3C4D", see agents.client_notice.call_reference
    counterparty_name: str  # display name, with the synthetic-data label in the demo
    amount: str  # e.g. "USD 2,500,000.00"
    deadline: str  # communication.format_deadline
    # The quick-reply button's payload, returned on the webhook when the
    # client taps "Acknowledge" (agents.client_notice.ack_payload).
    reply_payload: str
    # Echoed back on every `statuses` webhook event for this message, so a
    # delivery status maps to its call without a lookup (the thread id).
    callback_data: str
    # Plain-text rendering, for channels without a template (Slack, and
    # WhatsApp free-form inside the 24-hour window).
    text: str


class ClientDeliveryError(Exception):
    """The notice could not be handed to the client channel (not configured,
    rejected, or the provider is down). Never retried on another channel: the
    call escalates instead (ADR-0016, "no silent fallback")."""


class Notifier(Protocol):
    """Sends an already-drafted, already-approved notice. Never called before
    the human approval gate (CLAUDE.md golden rule 5)."""

    def send(self, text: str) -> DeliveryReceipt:
        """Deliver `text`; raise if the channel isn't configured or delivery fails."""
        ...

    def send_notice(self, notice: ClientNotice) -> DeliveryReceipt:
        """Deliver a structured margin-call notice; raise on failure."""
        ...
