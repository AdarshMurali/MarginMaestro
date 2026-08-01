from functools import lru_cache

from fastapi import FastAPI
from langgraph.graph.state import CompiledStateGraph

from agents.orchestrator import build_orchestrator_graph, resume_run
from api.logging_config import configure_logging
from api.middleware import CorrelationIdMiddleware
from api.schemas import ApprovalRequest, ApprovalResponse, HealthResponse

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
    """PROVISIONAL (see MM-37 note in docs/ROADMAP.md): no auth, no audit trail
    yet, and only resumes a run paused in this same process (in-memory
    checkpointer) until MM-38 persists it. Revisit before treating as final."""
    graph = get_orchestrator_graph()
    resume_payload = {"decision": body.decision, "adjusted_call_amount": body.adjusted_call_amount}
    result = resume_run(graph, thread_id, resume_payload)
    return ApprovalResponse(
        thread_id=thread_id,
        approval_decision=result.get("approval_decision"),
        adjusted_call_amount=result.get("adjusted_call_amount"),
    )
