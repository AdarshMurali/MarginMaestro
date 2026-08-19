"""Immutable audit-log view (MM-91, Phase 9): reads audit_log directly --
a plain insert-only SQL table (persistence/audit.py) written by every real
lifecycle step in agents/orchestrator.py -- rather than reconstructing
history from LangGraph's own checkpoints the way api/margin_call_trace.py
(MM-54) does. Deliberately a separate, parallel view: the checkpoint-based
trace is unaffected by this story and stays exactly as it was. This one is
the reliable record when it matters, since AzureSQLSaver can silently drop
a checkpoint row under concurrent writes (see docs/PROGRESS.md's tech-debt
notes) but audit_log has no such failure mode -- it's a normal table."""

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.orm import Session

from api.schemas import AuditLogEntry, AuditLogResponse
from persistence.audit import list_audit_events


def get_margin_call_audit_log(
    graph: CompiledStateGraph, session: Session, thread_id: str
) -> AuditLogResponse | None:
    """None means no run exists for this thread_id at all (the caller's cue
    to 404) -- distinct from a real run that simply has no audit events yet
    (shouldn't happen in practice, since compute_exposure -- the first
    node -- always writes one, but a run that's still mid-first-step could
    theoretically be caught between invoke() and that first commit).

    Filters by (correlation_id, counterparty_id) together, not
    correlation_id alone -- see persistence/audit.py's docstring: one
    triggering event's correlation_id is shared across every counterparty
    it fanned out to (api/simulate.py), so correlation_id alone would
    return other counterparties' events mixed in with this thread's own.
    """
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    values = graph.get_state(config).values
    if not values:
        return None

    correlation_id = values["correlation_id"]
    counterparty_id = values["counterparty_id"]
    entries = [
        AuditLogEntry(event_type=row.event_type, payload=row.payload, created_at=row.created_at)
        for row in list_audit_events(session, correlation_id, counterparty_id)
    ]
    return AuditLogResponse(thread_id=thread_id, correlation_id=correlation_id, entries=entries)
