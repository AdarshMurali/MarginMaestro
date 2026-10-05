"""Inbound WhatsApp webhook (G6, MM-133, ADR-0016).

Meta calls `POST /webhooks/whatsapp` with delivery `statuses` for the
notices we sent and with the client's `messages`. Everything here is
deterministic code; no LLM ever acts on a client message.

**Trust.** The endpoint is public (Meta can't sign in), so nothing is read
before the `X-Hub-Signature-256` HMAC of the raw body (WHATSAPP_APP_SECRET)
checks out, compared in constant time. An Acknowledge tap is then only
honoured if the sender is the counterparty's contact, the button belongs to
the call's latest notice, and the call is waiting for a response.

**Processing: inline, exactly once.** Each status (`wa-status:<id>:<status>`)
and each message (`wa-msg:<id>`) is claimed in `processed_events` before it
is handled, so a redelivery from Meta -- including one sent because a slow
escalation made Meta time out -- is skipped. Handled outcomes (applied, or
deliberately ignored) keep their claim. An unexpected error releases the
claim and returns 500, so Meta redelivers and the item is tried again.
Pub/Sub was considered (the roadmap's first sketch) and not used: the claim
already gives idempotency, the work per event is small (an audit row, at most
one graph resume), and an extra hop would add a topic, a push subscription
and a second place for the same claim.

- **statuses** `sent` / `delivered` / `read` / `failed` go on the call's
  audit trail. `failed` for the call's current notice, while the call waits
  for the client, resumes the run with `delivery_failed`: the SLA can't be
  met, so the call escalates through the normal path (ServiceNow incident,
  internal Slack post). There is no fallback to another client channel.
- **Acknowledge** quick-reply: the same as `POST /margin-calls/{id}/respond`
  -- the SLA is met.
- **Free text** (and any other message): screened by the guardrail pipeline,
  masked by the redactor, recorded on the audit trail, and flagged to Slack
  for a person. A reply mentioning "dispute" is flagged as a possible
  dispute; there is no client-dispute path in the graph to route it to, so a
  person handles it.
"""

import hashlib
import hmac
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from adapters.whatsapp_adapter import normalize_phone
from agents import internal_notifications as internal
from agents.client_notice import call_reference, thread_from_ack_payload
from agents.internal_notifications import InternalNotifier
from config.settings import Settings
from persistence.audit import record_audit_event
from persistence.claims import claim_once, release_claim
from persistence.db.models import AuditLogORM
from ports.guardrail import Guardrail, GuardrailError, Verdict
from ports.redactor import Redactor

logger = structlog.get_logger()

SIGNATURE_PREFIX = "sha256="
# Free-text replies posted to Slack are cut to this length.
MAX_REPLY_CHARS = 500
# How far back to look for the notice a reply quotes (audit rows).
NOTICE_LOOKUP_ROWS = 500
INBOUND_CORRELATION_ID = "whatsapp-inbound"


def verify_signature(raw_body: bytes, header: str | None, app_secret: str) -> bool:
    """Meta's `X-Hub-Signature-256: sha256=<hex HMAC-SHA256 of the raw body>`."""
    if not header or not header.startswith(SIGNATURE_PREFIX) or not app_secret:
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len(SIGNATURE_PREFIX) :].strip().lower())


# --- payload (only the fields we use; Meta adds more over time) -------------


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class StatusError(_Model):
    code: int | None = None
    title: str | None = None


class Status(_Model):
    id: str
    status: str
    recipient_id: str | None = None
    biz_opaque_callback_data: str | None = None
    errors: list[StatusError] = []


class Text(_Model):
    body: str = ""


class Button(_Model):
    payload: str | None = None
    text: str | None = None


class ButtonReply(_Model):
    id: str | None = None
    title: str | None = None


class Interactive(_Model):
    type: str | None = None
    button_reply: ButtonReply | None = None


class Context(_Model):
    id: str | None = None


class Message(_Model):
    id: str
    sender: str = Field(alias="from")
    type: str
    text: Text | None = None
    button: Button | None = None
    interactive: Interactive | None = None
    context: Context | None = None


class Value(_Model):
    statuses: list[Status] = []
    messages: list[Message] = []


class Change(_Model):
    field: str = ""
    value: Value = Value()


class Entry(_Model):
    changes: list[Change] = []


class WebhookPayload(_Model):
    object: str = ""
    entry: list[Entry] = []


# --- processing ----------------------------------------------------------------


@dataclass
class WebhookDeps:
    graph: CompiledStateGraph
    session_factory: sessionmaker[Session]
    settings: Settings
    guardrail: Guardrail
    redactor: Redactor
    internal_notifier: InternalNotifier
    resume: Callable[[CompiledStateGraph, str, dict], dict]


def process_webhook(payload: WebhookPayload, deps: WebhookDeps) -> list[str]:
    """Handles every status and message in the payload, each exactly once.
    Returns one outcome per item (for logs and tests)."""
    outcomes: list[str] = []
    for entry in payload.entry:
        for change in entry.changes:
            for status in change.value.statuses:
                outcomes.append(
                    _once(deps, f"wa-status:{status.id}:{status.status}", _handle_status, status)
                )
            for message in change.value.messages:
                outcomes.append(_once(deps, f"wa-msg:{message.id}", _handle_message, message))
    return outcomes


def _once(
    deps: WebhookDeps, key: str, handler: Callable[[Any, WebhookDeps], str], item: Any
) -> str:
    if not claim_once(deps.session_factory, key):
        logger.info("whatsapp_webhook_duplicate", key=key)
        return "duplicate"
    try:
        outcome = handler(item, deps)
    except Exception:
        release_claim(deps.session_factory, key)  # Meta redelivers on our 500
        logger.exception("whatsapp_webhook_item_failed", key=key)
        raise
    logger.info("whatsapp_webhook_item", key=key, outcome=outcome)
    return outcome


def _values(deps: WebhookDeps, thread_id: str) -> tuple[dict, set[str]]:
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    snapshot = deps.graph.get_state(config)
    pending = {task.name for task in snapshot.tasks if task.interrupts}
    return dict(snapshot.values or {}), pending


def _audit(deps: WebhookDeps, values: dict, event_type: str, payload: dict) -> None:
    with deps.session_factory() as session:
        record_audit_event(
            session,
            values["correlation_id"],
            event_type,
            payload,
            counterparty_id=values["counterparty_id"],
        )


def thread_for_message(session: Session, message_id: str) -> str | None:
    """The call whose notice had WhatsApp id `message_id`, from the audit row
    send_notification writes (it records the thread id for WhatsApp sends)."""
    rows = session.execute(
        select(AuditLogORM.payload)
        .where(AuditLogORM.event_type == "send_notification")
        .order_by(AuditLogORM.id.desc())
        .limit(NOTICE_LOOKUP_ROWS)
    ).scalars()
    for payload in rows:
        result = (payload or {}).get("notification_result") or {}
        if result.get("message_id") == message_id and payload.get("thread_id"):
            return str(payload["thread_id"])
    return None


def _handle_status(status: Status, deps: WebhookDeps) -> str:
    thread_id = status.biz_opaque_callback_data
    if not thread_id:
        with deps.session_factory() as session:
            thread_id = thread_for_message(session, status.id)
    values, pending = _values(deps, thread_id) if thread_id else ({}, set())
    if not thread_id or not values:
        logger.warning("whatsapp_status_unmatched", message_id=status.id, status=status.status)
        return "status_unmatched"

    errors = [e.model_dump(exclude_none=True) for e in status.errors]
    notification = values.get("notification_result")
    current = notification is not None and notification.message_id == status.id
    _audit(
        deps,
        values,
        "client_delivery_status",
        {
            "channel": "whatsapp",
            "message_id": status.id,
            "status": status.status,
            "errors": errors,
            "current_notice": current,
        },
    )
    if status.status != "failed":
        return f"status_{status.status}"
    if not current:
        return "failed_for_older_notice"
    if "await_sla_response" not in pending:
        return "failed_after_resolution"
    reason = "WhatsApp reported the notice failed" + (
        f" ({'; '.join(_error_text(e) for e in status.errors)})" if status.errors else ""
    )
    deps.resume(deps.graph, thread_id, {"delivery_failed": True, "reason": reason})
    return "failed_escalated"


def _error_text(error: StatusError) -> str:
    return f"{error.code}: {error.title}" if error.title else str(error.code)


def _ack_thread(message: Message) -> str | None:
    payload = None
    if message.type == "button" and message.button is not None:
        payload = message.button.payload
    elif message.type == "interactive" and message.interactive and message.interactive.button_reply:
        payload = message.interactive.button_reply.id
    return thread_from_ack_payload(payload) if payload else None


def _handle_message(message: Message, deps: WebhookDeps) -> str:
    thread_id = _ack_thread(message)
    if thread_id is not None:
        return _handle_ack(message, thread_id, deps)
    return _handle_reply(message, deps)


def _handle_ack(message: Message, thread_id: str, deps: WebhookDeps) -> str:
    values, pending = _values(deps, thread_id)
    if not values:
        logger.warning("whatsapp_ack_unknown_call", message_id=message.id)
        return _handle_reply(message, deps)

    reason: str | None = None
    contact = normalize_phone(deps.settings.whatsapp_recipient or "")
    notification = values.get("notification_result")
    quoted = message.context.id if message.context else None
    if not contact or normalize_phone(message.sender) != contact:
        reason = "the sender is not the counterparty's registered contact"
    elif quoted and notification is not None and quoted != notification.message_id:
        reason = "the button belongs to an older notice"
    elif "await_sla_response" not in pending:
        reason = "the call is not waiting for a client response"

    audit_payload = {
        "channel": "whatsapp",
        "message_id": message.id,
        "sender": internal.mask_phone(message.sender),
    }
    if reason is not None:
        _audit(deps, values, "client_acknowledgement_ignored", {**audit_payload, "reason": reason})
        return "ack_ignored"

    result = deps.resume(
        deps.graph, thread_id, {"responded": True, "via": "whatsapp", "message_id": message.id}
    )
    _audit(
        deps,
        values,
        "client_acknowledged",
        {**audit_payload, "sla_outcome": result.get("sla_outcome")},
    )
    return "acknowledged"


def _screen(text: str, guardrail: Guardrail) -> Verdict:
    """Fail closed: text that can't be screened is treated as blocked."""
    try:
        return guardrail.screen(text, "prompt")
    except GuardrailError as exc:
        return Verdict(allowed=False, guardrail=guardrail.name, reasons=[f"unscreened: {exc}"])


def _handle_reply(message: Message, deps: WebhookDeps) -> str:
    """Free text (or anything that isn't a valid Acknowledge): screened,
    recorded and flagged to a person. Never acted on automatically."""
    if message.text is not None:
        raw_text = message.text.body
    elif message.button is not None:
        raw_text = message.button.text or ""
    else:
        raw_text = ""
    quoted = message.context.id if message.context else None
    thread_id = None
    if quoted:
        with deps.session_factory() as session:
            thread_id = thread_for_message(session, quoted)
    values = _values(deps, thread_id)[0] if thread_id else {}

    verdict = _screen(raw_text, deps.guardrail) if raw_text else None
    shown: str | None = None
    if raw_text and verdict is not None and verdict.allowed:
        try:
            shown = deps.redactor.redact(raw_text)[:MAX_REPLY_CHARS]
        except Exception:  # the redactor fails loud; then the text is withheld
            logger.exception("whatsapp_reply_redaction_failed", message_id=message.id)
    possible_dispute = "dispute" in raw_text.lower()
    sender = internal.mask_phone(message.sender)
    payload = {
        "channel": "whatsapp",
        "message_id": message.id,
        "type": message.type,
        "sender": sender,
        "possible_dispute": possible_dispute,
        "guardrail": verdict.model_dump() if verdict else None,
        "text": shown,
    }
    if values:
        _audit(deps, values, "client_reply_received", payload)
    else:
        with deps.session_factory() as session:
            record_audit_event(session, INBOUND_CORRELATION_ID, "client_reply_received", payload)

    if verdict is None:
        note = f"Message type {message.type!r}, no text."
    elif verdict.allowed:
        note = f"Screened by {verdict.guardrail}: allowed."
    else:
        note = f"Blocked by {verdict.guardrail} ({', '.join(verdict.reasons)}); text withheld."
    deps.internal_notifier.post_once(
        f"client_reply:{message.id}",
        internal.client_reply(
            sender,
            shown,
            call_reference(thread_id) if thread_id else None,
            possible_dispute,
            note,
        ),
    )
    return "reply_flagged_dispute" if possible_dispute else "reply_flagged"
