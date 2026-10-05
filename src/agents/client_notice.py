"""The structured client notice (G6, MM-118): every value is computed and
formatted here, in code (ADR-0005). The WhatsApp template has four body
variables -- reference, counterparty, amount, deadline -- and an Acknowledge
quick-reply button whose payload identifies the call.

- **Reference** (`MC-1A2B3C4D`): a short, stable id derived from the thread
  id, quoted to the client and in every internal post, so people can talk
  about one call.
- **Reply payload** (`ack:<thread_id>`): returned by Meta when the client taps
  Acknowledge. It is only trusted together with the webhook's signature, the
  sender's number and the call being at the SLA step (api.whatsapp_webhook).
"""

import hashlib
from datetime import datetime

from agents.communication import format_deadline, money
from ports.notifier import ClientNotice

ACK_PREFIX = "ack:"
# Meta caps a quick-reply payload; stay well inside it.
MAX_PAYLOAD_CHARS = 128


def call_reference(thread_id: str) -> str:
    """`MC-` + the first 8 hex digits of the thread id's SHA-256, upper case."""
    return "MC-" + hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:8].upper()


def ack_payload(thread_id: str) -> str:
    payload = ACK_PREFIX + thread_id
    if len(payload) > MAX_PAYLOAD_CHARS:
        raise ValueError(f"thread id too long for a quick-reply payload: {thread_id!r}")
    return payload


def thread_from_ack_payload(payload: str) -> str | None:
    """The thread id an Acknowledge payload names, or None if it isn't one."""
    if not payload.startswith(ACK_PREFIX):
        return None
    thread_id = payload[len(ACK_PREFIX) :]
    return thread_id if ":" in thread_id else None


def display_name(name: str, label: str) -> str:
    """The counterparty as the client sees it, with the synthetic-data label
    (ADR-0016: test sends say so), e.g. "Acme Capital (TEST)"."""
    return f"{name} {label}".strip() if label else name


def build_client_notice(
    *,
    thread_id: str,
    counterparty_id: str,
    counterparty_name: str,
    call_amount: float,
    currency: str,
    deadline: datetime,
    label: str,
) -> ClientNotice:
    reference = call_reference(thread_id)
    name = display_name(counterparty_name, label)
    amount = money(call_amount, currency)
    deadline_text = format_deadline(deadline)
    text = (
        f"Margin call {reference} for {name}: {amount} is due by {deadline_text}. "
        "Please acknowledge this notice."
    )
    if label:
        text += " Synthetic data -- demo only."
    return ClientNotice(
        counterparty_id=counterparty_id,
        reference=reference,
        counterparty_name=name,
        amount=amount,
        deadline=deadline_text,
        reply_payload=ack_payload(thread_id),
        callback_data=thread_id,
        text=text,
    )
