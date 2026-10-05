"""Internal firm traffic on Slack (G6, MM-134, ADR-0016).

Since G6, Slack carries the firm's own traffic and WhatsApp carries the
client's. Each post below is sent **once** -- the key is claimed in
`processed_events` first, so a replayed graph node (LangGraph re-runs a node
from the top on resume) or a redelivered webhook never posts twice:

- approval requested (approver), and the manager's second signature (elite tier)
- client notified on WhatsApp
- client acknowledged (SLA met)
- client notice delivery failed
- SLA breached / escalated, with the ServiceNow incident number
- a client reply that needs a human (free text, possible dispute)
- the daily margin run summary

Every message is built here, by code, from values the run already holds --
no LLM, and nothing the firm doesn't already see in the app.

A failed internal post is logged (error level) and does not fail the margin
call: an approval gate must still arm if Slack is down. The claim is kept, so
a later replay doesn't post a stale message (e.g. "approval requested" after
the approval).
"""

from collections.abc import Callable, Iterable

import structlog
from sqlalchemy.orm import Session, sessionmaker

from agents.communication import money
from persistence.claims import claim_once

logger = structlog.get_logger()


class InternalNotifier:
    def __init__(
        self,
        post: Callable[[str], object] | None,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._post = post
        self._session_factory = session_factory

    @property
    def enabled(self) -> bool:
        return self._post is not None

    def post_once(self, key: str, text: str) -> bool:
        """True if this call posted `text`; False if disabled, already posted,
        or the post failed (logged)."""
        if self._post is None:
            return False
        if self._session_factory is not None and not claim_once(
            self._session_factory, f"notify:{key}"
        ):
            logger.info("internal_notification_already_sent", key=key)
            return False
        try:
            self._post(text)
        except Exception:  # see module docstring: never fail the call over Slack
            logger.exception("internal_notification_failed", key=key)
            return False
        logger.info("internal_notification_sent", key=key)
        return True


def disabled() -> InternalNotifier:
    return InternalNotifier(None)


def mask_phone(number: str) -> str:
    digits = "".join(ch for ch in number if ch.isdigit())
    return f"+…{digits[-4:]}" if len(digits) >= 4 else "+…"


# --- message builders (code only) -------------------------------------------


def approval_requested(
    reference: str, counterparty: str, amount: float, currency: str, rationale: str | None
) -> str:
    text = (
        f":rotating_light: Approval requested -- margin call {reference} for {counterparty}: "
        f"{money(amount, currency)}. An approver must approve, adjust or reject it in "
        "MarginMaestro before anything is sent to the client."
    )
    return f"{text}\nWhy: {rationale}" if rationale else text


def manager_approval_requested(
    reference: str, counterparty: str, amount: float, currency: str, first_approver: str | None
) -> str:
    return (
        f":lock: Second signature needed -- margin call {reference} for {counterparty} "
        f"(elite tier): {money(amount, currency)}, approved by {first_approver or 'an approver'}. "
        "A different manager must sign it in MarginMaestro."
    )


def client_notified(
    reference: str, counterparty: str, amount: str, deadline: str, channel: str, message_id: str
) -> str:
    return (
        f":outbox_tray: Client notified on {channel} -- margin call {reference} for "
        f"{counterparty}: {amount}, due by {deadline}. Accepted by the provider "
        f"(message {message_id}); delivery is confirmed by the webhook."
    )


def client_acknowledged(reference: str, counterparty: str, amount: str) -> str:
    return (
        f":white_check_mark: Client acknowledged margin call {reference} for {counterparty} "
        f"({amount}) within the SLA window. SLA met."
    )


def delivery_failed(reference: str, counterparty: str, reason: str) -> str:
    return (
        f":x: Client notice NOT delivered -- margin call {reference} for {counterparty}: "
        f"{reason}. No other channel was tried; the call is being escalated."
    )


def escalated(
    reference: str, counterparty: str, amount: str, incident_number: str, why: str
) -> str:
    return (
        f":sos: Margin call {reference} for {counterparty} ({amount}) escalated: {why}. "
        f"ServiceNow incident {incident_number}."
    )


def client_reply(
    sender: str, text: str | None, reference: str | None, possible_dispute: bool, note: str
) -> str:
    about = f"margin call {reference}" if reference else "no call identified"
    head = ":warning: Possible DISPUTE" if possible_dispute else ":speech_balloon: Client reply"
    body = f'"{text}"' if text is not None else "(text withheld)"
    return (
        f"{head} on WhatsApp from {sender} ({about}): {body}. {note} "
        "A person must review it; nothing was done automatically."
    )


def daily_run_summary(run_id: str, counterparties: int, outcomes: Iterable[dict]) -> str:
    rows = list(outcomes)
    raised = [o for o in rows if o.get("action") == "started" and o.get("breached")]
    updated = [o for o in rows if o.get("action") == "updated"]
    unchanged = [o for o in rows if o.get("action") == "unchanged"]
    lines = [
        (
            f":bar_chart: Daily margin run {run_id}: {counterparties} counterparties evaluated, "
            f"{len(raised)} call(s) raised for approval, {len(updated)} open call(s) updated, "
            f"{len(unchanged)} left unchanged."
        )
    ]
    for outcome in raised + updated:
        amount = outcome.get("call_amount")
        figure = f"{amount:,.2f}" if isinstance(amount, int | float) else "n/a"
        lines.append(f"• {outcome['counterparty_id']}: {outcome['action']}, call {figure}")
    return "\n".join(lines)
