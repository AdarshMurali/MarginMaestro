from functools import lru_cache

from fastapi import FastAPI
from langgraph.graph.state import CompiledStateGraph

from agents.orchestrator import build_orchestrator_graph, resume_run
from api.logging_config import configure_logging
from api.middleware import CorrelationIdMiddleware
from api.schemas import ApprovalRequest, ApprovalResponse, HealthResponse, SlaResponse

configure_logging()

app = FastAPI(title="MarginMaestro API")
app.add_middleware(CorrelationIdMiddleware)


@lru_cache
def get_orchestrator_graph() -> CompiledStateGraph:
    """Module-level singleton so the (currently in-memory, MM-38 makes this
    persisted) checkpointer is shared across requests within this process."""
    return build_orchestrator_graph()


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/ready", response_model=HealthResponse)
async def ready() -> HealthResponse:
    return HealthResponse(status="ready")


@app.post("/margin-calls/{thread_id}/approve", response_model=ApprovalResponse)
async def approve_margin_call(thread_id: str, body: ApprovalRequest) -> ApprovalResponse:
    """PROVISIONAL (see MM-37 note in docs/ROADMAP.md): no auth, no audit
    trail yet. Revisit before treating as final."""
    graph = get_orchestrator_graph()
    resume_payload = {"decision": body.decision, "adjusted_call_amount": body.adjusted_call_amount}
    result = resume_run(graph, thread_id, resume_payload)
    return ApprovalResponse(
        thread_id=thread_id,
        approval_decision=result.get("approval_decision"),
        adjusted_call_amount=result.get("adjusted_call_amount"),
    )


@app.post("/margin-calls/{thread_id}/respond", response_model=SlaResponse)
async def respond_to_margin_call(thread_id: str) -> SlaResponse:
    """PROVISIONAL (MM-42): stands in for a real counterparty-facing response
    channel, which doesn't exist in this demo -- simulates the counterparty
    fulfilling the call within the SLA window. See docs/ROADMAP.md's Phase 6
    note; revisit before treating as final."""
    result = resume_run(get_orchestrator_graph(), thread_id, {"responded": True})
    return SlaResponse(thread_id=thread_id, sla_outcome=result.get("sla_outcome"))


@app.post("/margin-calls/{thread_id}/check-sla", response_model=SlaResponse)
async def check_margin_call_sla(thread_id: str) -> SlaResponse:
    """PROVISIONAL (MM-42): re-evaluates whether the SLA deadline has passed.
    A no-op (stays pending) if called before the deadline -- there's no real
    scheduler calling this periodically yet; a human or a future cron would
    call it. See docs/ROADMAP.md's Phase 6 note."""
    result = resume_run(get_orchestrator_graph(), thread_id, {"check": True})
    return SlaResponse(thread_id=thread_id, sla_outcome=result.get("sla_outcome"))
