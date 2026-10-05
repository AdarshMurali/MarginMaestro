"""Margin-call policy (MM-125, Phase G5b; ADR-0020): decides what one trigger
does for one counterparty. Every trigger path goes through `dispatch_trigger`:
intraday impact sets (Pub/Sub push, Kafka), the /simulate panel, and the
daily margin run.

- **No open call:** a new run starts. In the graph, an intraday price event
  passes the materiality gate only if *its own* impact on exposure exceeds
  the CSA MTA (agents.orchestrator.evaluate_breach_node); below it, the run
  ends without a call and the standing breach is left to the daily run.
- **An open call awaiting its first approval:** the trigger re-evaluates
  that call in place (orchestrator.reevaluate_run) -- never a second call.
  An intraday trigger must clear the same gate first; the open call's own
  CSA terms supply the MTA, so the pre-check needs no LLM call.
- **An open call already signed or sent** (awaiting the manager's second
  signature, or notified and on the SLA clock): nothing changes. A figure a
  human approved or a client received is never altered by automation; the
  trigger is recorded on that call's audit trail, and the next daily run
  after the call resolves evaluates the counterparty afresh.

Concurrency: two triggers for one counterparty at once (several Cloud Run
instances handle pushes in parallel) could both see "no open call" and raise
two. A short per-counterparty lease (a `processed_events` row) serialises
them; a trigger that finds the lease held raises CounterpartyBusyError so it
is redelivered and retried, by then seeing the other trigger's call.

Idempotency stays with the callers' per-(event, counterparty) claim
(streaming.impact_consumer.claim_run); a replayed trigger never reaches this
module. As a second line, a trigger already applied to the open call is a
no-op here too.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import structlog
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from agents.orchestrator import (
    MarginCallState,
    event_impact_for,
    find_open_call,
    open_call_stage,
    reevaluate_run,
    start_run,
    thread_id_for,
)
from calc.materiality import below_materiality_rationale, is_material
from persistence.audit import record_audit_event
from persistence.db.models import ProcessedEventORM
from streaming.schemas import ImpactSet

logger = structlog.get_logger()

# Longer than one dispatch can take (Cloud Run's request timeout is 600 s),
# so a live lease is never taken over; a lease left by a crashed instance
# expires after this.
LEASE_TTL = timedelta(minutes=15)


class TriggerAction(StrEnum):
    STARTED = "started"  # a new run; it may still end as no-breach / below materiality
    UPDATED = "updated"  # the open call was re-evaluated in place
    UNCHANGED = "unchanged"  # an open call exists and this trigger leaves it as is


class TriggerOutcome(BaseModel):
    counterparty_id: str
    action: TriggerAction
    thread_id: str
    breached: bool | None = None
    call_amount: float | None = None
    # The call's rationale, or why an open call was left unchanged.
    detail: str | None = None


class CounterpartyBusyError(Exception):
    """Another trigger is being dispatched for this counterparty right now."""


def _lease_id(counterparty_id: str) -> str:
    return f"cp-lease:{counterparty_id}"


def _as_utc(value: datetime) -> datetime:
    # SQLite hands back naive datetimes; every timestamp here is written in UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _take_lease(session_factory: sessionmaker[Session], counterparty_id: str) -> bool:
    lease_id = _lease_id(counterparty_id)
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(ProcessedEventORM(event_id=lease_id, processed_at=now))
        try:
            session.commit()
            return True
        except IntegrityError:
            session.rollback()
        held = session.get(ProcessedEventORM, lease_id)
        if held is None or now - _as_utc(held.processed_at) < LEASE_TTL:
            return False
        logger.warning("counterparty_lease_expired", counterparty_id=counterparty_id)
        held.processed_at = now  # take over the expired lease
        session.commit()
        return True


@contextmanager
def counterparty_lease(
    session_factory: sessionmaker[Session], counterparty_id: str
) -> Iterator[None]:
    if not _take_lease(session_factory, counterparty_id):
        raise CounterpartyBusyError(
            f"Another trigger is being dispatched for {counterparty_id}; retry shortly"
        )
    try:
        yield
    finally:
        with session_factory() as session:
            session.execute(
                delete(ProcessedEventORM).where(
                    ProcessedEventORM.event_id == _lease_id(counterparty_id)
                )
            )
            session.commit()


def _outcome(
    counterparty_id: str, action: TriggerAction, thread_id: str, values: dict
) -> TriggerOutcome:
    breach_result = values.get("breach_result")
    # A breach the materiality gate held raised no call, so it has no amount.
    held = values.get("materiality") == "below_mta"
    return TriggerOutcome(
        counterparty_id=counterparty_id,
        action=action,
        thread_id=thread_id,
        breached=breach_result.breached if breach_result is not None else None,
        call_amount=None if breach_result is None or held else breach_result.call_amount,
        detail=values.get("call_rationale"),
    )


def _audit_on_call(
    session_factory: sessionmaker[Session], values: dict, event_type: str, payload: dict
) -> None:
    with session_factory() as session:
        record_audit_event(
            session,
            values["correlation_id"],
            event_type,
            payload,
            counterparty_id=values["counterparty_id"],
        )


def dispatch_trigger(
    graph: CompiledStateGraph,
    impact: ImpactSet,
    counterparty_id: str,
    session_factory: sessionmaker[Session],
) -> TriggerOutcome:
    """Applies the policy above for one (trigger, counterparty). Business
    errors from the run (pricing gaps, missing CSA terms, guardrail blocks)
    propagate to the caller, which already knows how to hold them."""
    with counterparty_lease(session_factory, counterparty_id):
        return _dispatch(graph, impact, counterparty_id, session_factory)


def _dispatch(
    graph: CompiledStateGraph,
    impact: ImpactSet,
    counterparty_id: str,
    session_factory: sessionmaker[Session],
) -> TriggerOutcome:
    log = logger.bind(
        correlation_id=impact.event_id,
        counterparty_id=counterparty_id,
        trigger_event_id=impact.event_id,
    )
    with session_factory() as session:
        open_call = find_open_call(graph, session, counterparty_id)

    if open_call is None:
        state = MarginCallState(
            correlation_id=impact.event_id, impact=impact, counterparty_id=counterparty_id
        )
        result = start_run(graph, state)
        return _outcome(
            counterparty_id, TriggerAction.STARTED, thread_id_for(impact, counterparty_id), result
        )

    thread_id, values = open_call
    stage = open_call_stage(values)
    log = log.bind(open_call_thread_id=thread_id, open_call_stage=stage)
    applied = [values["impact"].event_id, *values.get("updated_by", [])]
    if impact.event_id in applied:
        log.info("trigger_already_applied_to_open_call")
        return _outcome(counterparty_id, TriggerAction.UNCHANGED, thread_id, values)

    trigger_payload = {
        "trigger_event_id": impact.event_id,
        "trigger_event_type": impact.event_type.value,
        "trigger_reason": impact.reason,
        "open_call_stage": stage,
    }

    if impact.price_moves:
        # Intraday: the open call's CSA terms give the MTA -- no LLM call.
        csa_terms = values["csa_terms"]
        with session_factory() as session:
            event_impact = event_impact_for(session, counterparty_id, impact)
        if not is_material(event_impact, csa_terms.mta):
            detail = below_materiality_rationale(
                event_impact, impact.price_moves, csa_terms.mta, csa_terms.currency
            )
            log.info(
                "intraday_trigger_below_materiality",
                event_exposure_change=event_impact.exposure_change,
                mta=csa_terms.mta,
            )
            _audit_on_call(
                session_factory,
                values,
                "trigger_below_materiality",
                {**trigger_payload, "event_impact": event_impact.model_dump(mode="json")},
            )
            return _outcome(counterparty_id, TriggerAction.UNCHANGED, thread_id, values).model_copy(
                update={"detail": detail}
            )

    if stage != "awaiting_approval":
        detail = (
            "This counterparty's open call has already been approved or sent, so its amount "
            "is not changed. The next daily margin run after it resolves evaluates the "
            "counterparty again."
        )
        log.info("trigger_absorbed_by_signed_open_call")
        _audit_on_call(session_factory, values, "trigger_absorbed_by_open_call", trigger_payload)
        return _outcome(counterparty_id, TriggerAction.UNCHANGED, thread_id, values).model_copy(
            update={"detail": detail}
        )

    previous_amount = values["breach_result"].call_amount
    result = reevaluate_run(
        graph, thread_id, impact, [*values.get("updated_by", []), impact.event_id]
    )
    breach_result = result.get("breach_result")
    log.info(
        "open_call_updated",
        previous_call_amount=previous_amount,
        call_amount=breach_result.call_amount if breach_result is not None else None,
        still_breached=breach_result.breached if breach_result is not None else None,
    )
    _audit_on_call(
        session_factory,
        values,
        "open_call_updated",
        {
            **trigger_payload,
            "previous_call_amount": previous_amount,
            "call_amount": breach_result.call_amount if breach_result is not None else None,
            "breached": breach_result.breached if breach_result is not None else None,
            "call_rationale": result.get("call_rationale"),
        },
    )
    return _outcome(counterparty_id, TriggerAction.UPDATED, thread_id, result)
