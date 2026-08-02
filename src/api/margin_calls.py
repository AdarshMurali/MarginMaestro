"""Margin-call feed (MM-53): lists every orchestrator run discovered from
persisted checkpoints, with a lifecycle status derived from
agents.orchestrator's actual graph routing -- not a separately-maintained
state machine, so it can't drift from what the orchestrator really does.
The orchestrator itself has no "list runs" concept (MM-38's checkpointer
only supports get/put by thread_id); this reads the checkpoint table
directly for thread discovery, then reuses graph.get_state() per thread,
same call get_or_start_run already makes for a single thread."""

from datetime import UTC, datetime, timedelta

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.schemas import MarginCallFeedResponse, MarginCallLifecycleStatus, MarginCallSummary
from calc.models import BreachResult
from config.settings import Settings, get_settings
from persistence.db.models import CheckpointORM


def _lifecycle_status(values: dict) -> MarginCallLifecycleStatus:
    if values.get("escalation_result") is not None:
        return MarginCallLifecycleStatus.ESCALATED
    sla_outcome = values.get("sla_outcome")
    if sla_outcome == "met":
        return MarginCallLifecycleStatus.SLA_MET
    if sla_outcome == "breached":
        # escalate() runs synchronously right after sla_outcome resolves to
        # "breached" (a plain node, not its own interrupt), so
        # escalation_result should already be set by the time this is
        # observable at rest -- defensive fallback, not the expected steady
        # state.
        return MarginCallLifecycleStatus.ESCALATED
    if values.get("notification_sent_at") is not None:
        return MarginCallLifecycleStatus.AWAITING_SLA_RESPONSE
    if values.get("approval_decision") == "rejected":
        return MarginCallLifecycleStatus.REJECTED
    breach_result = values.get("breach_result")
    if breach_result is not None:
        if breach_result.breached:
            return MarginCallLifecycleStatus.AWAITING_APPROVAL
        return MarginCallLifecycleStatus.NO_BREACH
    return MarginCallLifecycleStatus.EVALUATING


def _effective_call_amount(values: dict, breach_result: BreachResult | None) -> float | None:
    """Mirrors agents.orchestrator._effective_call_amount's logic (adjusted
    amount wins once the approval decision is "adjusted", else the raw
    breach amount) -- reimplemented against this dict-shaped snapshot rather
    than imported, since that helper takes a full MarginCallState, not a
    checkpoint's raw values. Found live (MM-55): without this, an adjusted
    call still displayed its original, no-longer-accurate breach amount."""
    if breach_result is None:
        return None
    if (
        values.get("approval_decision") == "adjusted"
        and values.get("adjusted_call_amount") is not None
    ):
        return values["adjusted_call_amount"]
    return breach_result.call_amount


def _summarize(thread_id: str, values: dict, settings: Settings) -> MarginCallSummary:
    breach_result = values.get("breach_result")
    csa_terms = values.get("csa_terms")
    impact = values["impact"]
    notification_sent_at = values.get("notification_sent_at")
    sla_deadline = (
        notification_sent_at + timedelta(minutes=settings.margin_call_sla_minutes)
        if notification_sent_at is not None
        else None
    )
    return MarginCallSummary(
        thread_id=thread_id,
        correlation_id=values["correlation_id"],
        counterparty_id=values["counterparty_id"],
        event_type=impact.event_type.value,
        reason=impact.reason,
        occurred_at=impact.occurred_at,
        status=_lifecycle_status(values),
        call_amount=_effective_call_amount(values, breach_result),
        currency=csa_terms.currency if csa_terms is not None else "USD",
        approval_decision=values.get("approval_decision"),
        sla_outcome=values.get("sla_outcome"),
        notification_sent_at=notification_sent_at,
        sla_deadline=sla_deadline,
    )


def list_margin_calls(
    graph: CompiledStateGraph, session: Session, settings: Settings | None = None
) -> MarginCallFeedResponse:
    settings = settings or get_settings()
    thread_ids = session.execute(select(CheckpointORM.thread_id).distinct()).scalars().all()

    summaries = []
    for thread_id in thread_ids:
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        values = graph.get_state(config).values
        if not values:
            continue
        summaries.append(_summarize(thread_id, values, settings))

    summaries.sort(key=lambda s: s.occurred_at, reverse=True)
    return MarginCallFeedResponse(as_of=datetime.now(UTC), margin_calls=summaries)
