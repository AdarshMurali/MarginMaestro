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

from api.schemas import (
    CounterpartyHistoryResponse,
    MarginCallBucket,
    MarginCallBucketFeedResponse,
    MarginCallFeedResponse,
    MarginCallLifecycleStatus,
    MarginCallSummary,
)
from calc.models import BreachResult
from config.settings import Settings, get_settings
from persistence.db.models import CheckpointORM
from persistence.queries import get_counterparty, list_counterparties

# Lower rank = more urgent = shown first (MM-63) -- awaiting_approval and
# escalated sit in a human's queue right now; awaiting_sla_response is
# time-sensitive but not yet actionable; everything else is resolved and
# only recency (not urgency) distinguishes them.
_URGENCY_RANK: dict[MarginCallLifecycleStatus, int] = {
    MarginCallLifecycleStatus.AWAITING_APPROVAL: 0,
    MarginCallLifecycleStatus.ESCALATED: 1,
    MarginCallLifecycleStatus.AWAITING_SLA_RESPONSE: 2,
    MarginCallLifecycleStatus.EVALUATING: 3,
    MarginCallLifecycleStatus.REJECTED: 4,
    MarginCallLifecycleStatus.SLA_MET: 4,
    MarginCallLifecycleStatus.NO_BREACH: 4,
}


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


def _all_summaries(
    graph: CompiledStateGraph, session: Session, settings: Settings
) -> list[MarginCallSummary]:
    """Every orchestrator run, most recent first -- shared by the flat feed,
    the per-counterparty bucketed view, and the per-counterparty filter
    (MM-63), so there's exactly one place that reads checkpoints and derives
    lifecycle status."""
    thread_ids = session.execute(select(CheckpointORM.thread_id).distinct()).scalars().all()

    summaries = []
    for thread_id in thread_ids:
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        values = graph.get_state(config).values
        if not values:
            continue
        summaries.append(_summarize(thread_id, values, settings))

    summaries.sort(key=lambda s: s.occurred_at, reverse=True)
    return summaries


def list_margin_calls(
    graph: CompiledStateGraph, session: Session, settings: Settings | None = None
) -> MarginCallFeedResponse:
    settings = settings or get_settings()
    summaries = _all_summaries(graph, session, settings)
    return MarginCallFeedResponse(as_of=datetime.now(UTC), margin_calls=summaries)


def list_margin_calls_for_counterparty(
    graph: CompiledStateGraph,
    session: Session,
    counterparty_id: str,
    settings: Settings | None = None,
) -> MarginCallFeedResponse:
    """Full history for one counterparty (MM-63) -- for the counterparty
    profile page's margin-call-history section."""
    settings = settings or get_settings()
    summaries = [
        s for s in _all_summaries(graph, session, settings) if s.counterparty_id == counterparty_id
    ]
    return MarginCallFeedResponse(as_of=datetime.now(UTC), margin_calls=summaries)


def list_margin_call_buckets(
    graph: CompiledStateGraph, session: Session, settings: Settings | None = None
) -> MarginCallBucketFeedResponse:
    """One row per counterparty (MM-63): whichever call is most urgent for
    that counterparty, plus how many calls they have in total. Bucket order
    is itself urgency-first (then most-recent-first) so the counterparties
    needing attention right now surface at the top of the whole list, not
    just within their own row."""
    settings = settings or get_settings()
    summaries = _all_summaries(graph, session, settings)  # already most-recent-first
    names = {cp.id: cp.name for cp in list_counterparties(session)}

    calls_by_counterparty: dict[str, list[MarginCallSummary]] = {}
    for summary in summaries:
        calls_by_counterparty.setdefault(summary.counterparty_id, []).append(summary)

    buckets = []
    for counterparty_id, calls in calls_by_counterparty.items():
        # calls are already most-recent-first, so min() -- which returns the
        # first minimal element it sees -- picks the most urgent call,
        # tie-broken by recency, with no separate sort needed.
        most_urgent = min(calls, key=lambda c: _URGENCY_RANK[c.status])
        buckets.append(
            MarginCallBucket(
                counterparty_id=counterparty_id,
                counterparty_name=names.get(counterparty_id, counterparty_id),
                latest=most_urgent,
                total_count=len(calls),
            )
        )

    buckets.sort(key=lambda b: (_URGENCY_RANK[b.latest.status], -b.latest.occurred_at.timestamp()))
    return MarginCallBucketFeedResponse(as_of=datetime.now(UTC), buckets=buckets)


def counterparty_history(
    graph: CompiledStateGraph,
    session: Session,
    counterparty_id: str,
    days: int | None = None,
    settings: Settings | None = None,
) -> CounterpartyHistoryResponse | None:
    """Business-facing rollup (Phase 9 scope addition): how many margin
    calls this counterparty has had, what fraction breached, and the
    average size of the ones that did, over the trailing `days` (None =
    all-time). An aggregation over list_margin_calls_for_counterparty's
    same underlying data, not a new logging mechanism -- see
    docs/PROGRESS.md's handoff entry. Returns None if the counterparty
    doesn't exist (the caller's cue to 404), distinct from a real
    counterparty that simply has zero calls on record."""
    settings = settings or get_settings()
    counterparty = get_counterparty(session, counterparty_id)
    if counterparty is None:
        return None

    summaries = [
        s for s in _all_summaries(graph, session, settings) if s.counterparty_id == counterparty_id
    ]
    if days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        summaries = [s for s in summaries if s.occurred_at >= cutoff]

    # EVALUATING never persists in practice (see MarginCallLifecycleStatus's
    # own docstring) but is excluded defensively -- it isn't a resolved
    # outcome yet, so it shouldn't count toward either total_calls or a
    # breach rate.
    resolved = [s for s in summaries if s.status != MarginCallLifecycleStatus.EVALUATING]
    breached = [s for s in resolved if s.status != MarginCallLifecycleStatus.NO_BREACH]

    total_calls = len(resolved)
    breached_calls = len(breached)
    average_call_amount = (
        sum(s.call_amount for s in breached if s.call_amount is not None) / breached_calls
        if breached_calls
        else None
    )

    return CounterpartyHistoryResponse(
        counterparty_id=counterparty_id,
        counterparty_name=counterparty.name,
        as_of=datetime.now(UTC),
        period_days=days,
        total_calls=total_calls,
        breached_calls=breached_calls,
        breach_rate=(breached_calls / total_calls) if total_calls else 0.0,
        average_call_amount=average_call_amount,
        currency=resolved[0].currency if resolved else "USD",
    )
