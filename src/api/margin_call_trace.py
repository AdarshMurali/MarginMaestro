"""Agent activity / orchestration trace (MM-54, the Phase 8 showpiece):
reconstructs a real step-by-step trace of one margin-call run purely from
persisted checkpoint data -- no new write path needed. Reads the
checkpointer's own list() directly (via graph.checkpointer) rather than
LangGraph's graph.get_state_history() convenience wrapper: get_state_history
was found, empirically, to silently truncate history to only the last couple
of steps once a thread has been resumed more than once (reproduced against
this project's own AzureSQLSaver -- calling saver.list() directly for the
same thread_id returns the full, correct history every time). Each
checkpoint's raw channel_values carries a `branch:to:<node>` marker for
whichever node is queued to run next -- the same signal get_state_history is
supposed to expose as `.next`, read here straight from the source instead.
Pairing consecutive checkpoints (older's branch:to: marker -> what ran,
newer's channel_values -> what it produced, newer's ts -> when it finished)
reconstructs exactly which agent ran, in what order, with what result,
including real elapsed time across a human-in-the-loop pause (interrupt()
doesn't write its own checkpoint -- the next checkpoint only appears once
resume completes, so the gap between two timestamps is the real wait, not an
artifact)."""

from datetime import datetime
from itertools import pairwise

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from api.schemas import MarginCallTraceResponse, TraceStep, TraceStepStatus

NODE_LABELS = {
    "__start__": "Event received",
    "compute_exposure": "Compute exposure",
    "fetch_csa_terms": "Fetch CSA terms",
    "evaluate_breach": "Evaluate breach",
    "await_approval": "Await human approval",
    "await_manager_approval": "Await second sign-off",
    "send_notification": "Send notification",
    "await_sla_response": "Await SLA response",
    "send_sla_met_notification": "Send SLA-met notification",
    "escalate": "Escalate",
}

_BRANCH_PREFIX = "branch:to:"


def _pending_node(channel_values: dict) -> str | None:
    for key in channel_values:
        if key.startswith(_BRANCH_PREFIX):
            return key.removeprefix(_BRANCH_PREFIX)
    return None


def _summarize_step(node: str, values: dict) -> str:
    if node == "__start__":
        impact = values.get("impact")
        return f"Event received: {impact.reason}" if impact is not None else "Event received"

    if node == "compute_exposure":
        vm = values.get("variation_margin")
        im = values.get("initial_margin")
        if vm is not None and im is not None:
            return f"VM {vm.variation_margin:,.0f}, IM {im.initial_margin:,.0f}"
        return "Exposure computed"

    if node == "fetch_csa_terms":
        csa = values.get("csa_terms")
        return (
            f"Threshold {csa.threshold:,.0f} {csa.currency}"
            if csa is not None
            else "CSA terms fetched"
        )

    if node == "evaluate_breach":
        result = values.get("breach_result")
        if result is None:
            return "Breach evaluated"
        return f"Breached -- call {result.call_amount:,.0f}" if result.breached else "No breach"

    if node == "await_approval":
        decision = values.get("approval_decision")
        adjusted = values.get("adjusted_call_amount")
        if decision == "adjusted" and adjusted is not None:
            return f"Decision: adjusted to {adjusted:,.0f}"
        return f"Decision: {decision}" if decision else "Awaiting approval"

    if node == "await_manager_approval":
        decision = values.get("manager_decision")
        if decision is None:
            return "Awaiting second sign-off"
        return (
            f"Second sign-off: {decision}" if decision == "approved" else "Disputed -- overturned"
        )

    if node == "send_notification":
        result = values.get("notification_result")
        return (
            f"Slack notice sent to {result.slack_channel}"
            if result is not None
            else "Notification sent"
        )

    if node == "await_sla_response":
        outcome = values.get("sla_outcome")
        return f"SLA {outcome}" if outcome else "Awaiting SLA response"

    if node == "send_sla_met_notification":
        result = values.get("sla_met_notification_result")
        return (
            f"Slack confirmation sent to {result.slack_channel}"
            if result is not None
            else "SLA-met confirmation sent"
        )

    if node == "escalate":
        result = values.get("escalation_result")
        return (
            f"ServiceNow incident {result.incident_number}" if result is not None else "Escalated"
        )

    return NODE_LABELS.get(node, node)


def get_margin_call_trace(
    graph: CompiledStateGraph, thread_id: str
) -> MarginCallTraceResponse | None:
    """None means no checkpoint exists for this thread_id at all (the
    caller's cue to 404) -- distinct from a real run whose trace is simply
    short (e.g. no-breach ends after 3 steps)."""
    checkpointer = graph.checkpointer
    assert isinstance(checkpointer, BaseCheckpointSaver)  # always true for this project's graphs
    checkpoints = list(checkpointer.list({"configurable": {"thread_id": thread_id}}))
    if not checkpoints:
        return None
    checkpoints.reverse()  # list() returns newest-first; walk chronologically

    steps: list[TraceStep] = []
    for older, newer in pairwise(checkpoints):
        node = _pending_node(older.checkpoint.get("channel_values", {})) or "__start__"
        metadata = newer.metadata or {}
        ts = newer.checkpoint.get("ts")
        steps.append(
            TraceStep(
                step=metadata.get("step", len(steps)),
                node=NODE_LABELS.get(node, node),
                status=TraceStepStatus.COMPLETED,
                completed_at=datetime.fromisoformat(ts) if ts else None,
                summary=_summarize_step(node, newer.checkpoint.get("channel_values", {})),
            )
        )

    latest = checkpoints[-1]
    pending_node = _pending_node(latest.checkpoint.get("channel_values", {}))
    if pending_node is not None:
        steps.append(
            TraceStep(
                step=(steps[-1].step + 1) if steps else 0,
                node=NODE_LABELS.get(pending_node, pending_node),
                status=TraceStepStatus.IN_PROGRESS,
                completed_at=None,
                summary=f"Waiting on {NODE_LABELS.get(pending_node, pending_node).lower()}...",
            )
        )

    return MarginCallTraceResponse(thread_id=thread_id, steps=steps)
