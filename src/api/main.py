from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.orm import Session, sessionmaker

from agents.orchestrator import build_orchestrator_graph, resume_run
from api.exposure import build_exposure_board, get_price_history
from api.logging_config import configure_logging
from api.margin_calls import list_margin_calls
from api.middleware import CorrelationIdMiddleware
from api.schemas import (
    ApprovalRequest,
    ApprovalResponse,
    ExposureBoardResponse,
    HealthResponse,
    MarginCallFeedResponse,
    PriceHistoryResponse,
    SlaResponse,
)
from config.settings import get_settings
from persistence.db.engine import get_session_factory
from streaming.market_feed import MarketDataUnavailableError, get_market_feed

configure_logging()

app = FastAPI(title="MarginMaestro API")
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache
def get_orchestrator_graph() -> CompiledStateGraph:
    """Module-level singleton so the (currently in-memory, MM-38 makes this
    persisted) checkpointer is shared across requests within this process."""
    return build_orchestrator_graph()


@lru_cache
def get_db_session_factory() -> sessionmaker[Session]:
    return get_session_factory()


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


@app.get("/margin-calls", response_model=MarginCallFeedResponse)
async def margin_call_feed() -> MarginCallFeedResponse:
    session_factory = get_db_session_factory()
    graph = get_orchestrator_graph()
    with session_factory() as session:
        return list_margin_calls(graph, session)


@app.get("/exposure", response_model=ExposureBoardResponse)
async def exposure_board() -> ExposureBoardResponse:
    session_factory = get_db_session_factory()
    market_feed = get_market_feed()
    with session_factory() as session:
        return build_exposure_board(session, market_feed)


@app.get("/prices/{ticker}/history", response_model=PriceHistoryResponse)
async def price_history(ticker: str, days: int = 30) -> PriceHistoryResponse:
    try:
        return get_price_history(ticker, days=days)
    except MarketDataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/margin-calls/{thread_id}/check-sla", response_model=SlaResponse)
async def check_margin_call_sla(thread_id: str) -> SlaResponse:
    """PROVISIONAL (MM-42): re-evaluates whether the SLA deadline has passed.
    A no-op (stays pending) if called before the deadline -- there's no real
    scheduler calling this periodically yet; a human or a future cron would
    call it. See docs/ROADMAP.md's Phase 6 note."""
    result = resume_run(get_orchestrator_graph(), thread_id, {"check": True})
    return SlaResponse(thread_id=thread_id, sla_outcome=result.get("sla_outcome"))
