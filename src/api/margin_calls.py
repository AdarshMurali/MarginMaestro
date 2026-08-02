"""Margin-call feed (MM-53): lists every orchestrator run discovered from
persisted checkpoints, with a lifecycle status derived from
agents.orchestrator's actual graph routing -- not a separately-maintained
state machine, so it can't drift from what the orchestrator really does.
The orchestrator itself has no "list runs" concept (MM-38's checkpointer
only supports get/put by thread_id); this reads the checkpoint table
directly for thread discovery, then reuses graph.get_state() per thread,
same call get_or_start_run already makes for a single thread."""

from datetime import UTC, datetime

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.schemas import MarginCallFeedResponse, MarginCallLifecycleStatus, MarginCallSummary
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


def _summarize(thread_id: str, values: dict) -> MarginCallSummary:
    breach_result = values.get("breach_result")
    csa_terms = values.get("csa_terms")
    impact = values["impact"]
    return MarginCallSummary(
        thread_id=thread_id,
        correlation_id=values["correlation_id"],
        counterparty_id=values["counterparty_id"],
        event_type=impact.event_type.value,
        reason=impact.reason,
        occurred_at=impact.occurred_at,
        status=_lifecycle_status(values),
        call_amount=breach_result.call_amount if breach_result is not None else None,
        currency=csa_terms.currency if csa_terms is not None else "USD",
        approval_decision=values.get("approval_decision"),
        sla_outcome=values.get("sla_outcome"),
    )


def list_margin_calls(graph: CompiledStateGraph, session: Session) -> MarginCallFeedResponse:
    thread_ids = session.execute(select(CheckpointORM.thread_id).distinct()).scalars().all()

    summaries = []
    for thread_id in thread_ids:
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        values = graph.get_state(config).values
        if not values:
            continue
        summaries.append(_summarize(thread_id, values))

    summaries.sort(key=lambda s: s.occurred_at, reverse=True)
    return MarginCallFeedResponse(as_of=datetime.now(UTC), margin_calls=summaries)
