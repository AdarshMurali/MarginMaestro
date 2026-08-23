from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.orm import Session, sessionmaker

from agents.orchestrator import build_orchestrator_graph, resume_run
from api.audit_log import get_margin_call_audit_log
from api.auth import require_approver, require_manager, verify_credentials
from api.exposure import (
    build_exposure_board,
    get_counterparty_exposure,
    get_price_history,
    list_counterparty_summaries,
)
from api.logging_config import configure_logging
from api.margin_call_trace import get_margin_call_trace
from api.margin_calls import (
    counterparty_history,
    list_margin_call_buckets,
    list_margin_calls,
    list_margin_calls_for_counterparty,
)
from api.middleware import CorrelationIdMiddleware
from api.schemas import (
    ApprovalRequest,
    ApprovalResponse,
    AuditLogResponse,
    AuthVerifyRequest,
    AuthVerifyResponse,
    CounterpartyExposure,
    CounterpartyHistoryResponse,
    CounterpartyListResponse,
    ExposureBoardResponse,
    HealthResponse,
    ManagerApprovalRequest,
    ManagerApprovalResponse,
    MarginCallBucketFeedResponse,
    MarginCallFeedResponse,
    MarginCallTraceResponse,
    MarketUniverseResponse,
    PriceHistoryResponse,
    SimulateEventRequest,
    SimulateEventResponse,
    SlaResponse,
)
from api.simulate import trigger_simulation
from config.settings import get_settings
from observability.tracing import configure_tracing
from persistence.db.engine import get_session_factory
from streaming.market_feed import MarketDataUnavailableError
from streaming.schemas import MarketEventType

configure_logging()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """OTel/Jaeger wiring belongs here, not at bare module import time: a
    TestClient(app) used without `with` (this project's convention in
    every endpoint test) never triggers FastAPI's lifespan at all, so
    configure_tracing() -- and its real background OTLP export attempts --
    never runs during tests, only when an actual ASGI server (uvicorn)
    serves the app. Found live: configuring it unconditionally at import
    added ~30s to the whole local test suite from an unreachable-Jaeger
    background exporter."""
    configure_tracing(get_settings())
    yield


app = FastAPI(title="MarginMaestro API", lifespan=_lifespan)
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


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus scrape endpoint (MM-92) -- unauthenticated, matching
    standard Prometheus convention (scraped from within the docker network,
    not exposed to end users)."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/auth/verify", response_model=AuthVerifyResponse)
async def auth_verify(body: AuthVerifyRequest) -> AuthVerifyResponse:
    """Called server-side by the frontend's NextAuth Credentials provider --
    never called directly by a browser. The only place this backend sees a
    plaintext password."""
    session_factory = get_db_session_factory()
    with session_factory() as session:
        role = verify_credentials(body.username, body.password, session)
    if role is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return AuthVerifyResponse(username=body.username, role=role)


# Human-readable description of what's actually happening at each pending
# node, keyed by node name (or None for a finished run) -- used to build a
# real explanation in _require_pending_node's 409, not just a technical
# node-name dump. Copy lives here, not in the frontend, per CLAUDE.md's
# "keep the frontend thin" rule -- it visualizes state, it doesn't own the
# wording for what that state means.
_PENDING_NODE_DESCRIPTIONS: dict[str | None, str] = {
    "await_approval": "This margin call is awaiting first-level approval.",
    "await_manager_approval": (
        "This margin call already has a first-level approval and is now waiting on a "
        "second sign-off from a manager -- no further approver action is needed here."
    ),
    "await_sla_response": (
        "This margin call has already been approved and notified; it's now waiting on "
        "the SLA response window, not an approval action."
    ),
    "escalate": "This margin call has already been escalated.",
    None: "This margin call has already finished its lifecycle -- no further action is possible.",
}


def _require_pending_node(graph: CompiledStateGraph, thread_id: str, expected_node: str) -> dict:
    """Guards every resume_run() call against a real bug found live while
    testing MM-70's two-person sign-off: LangGraph's Command(resume=...)
    resumes *whatever* interrupt() is currently pending for a thread,
    regardless of which endpoint (and therefore which role check) called
    it -- there was previously no check that the thread was actually paused
    at the node an endpoint's own payload shape was meant for. A user
    authenticated only as `approver`, calling /approve a second time on an
    elite-tier thread already paused at await_manager_approval, had that
    call silently delivered into the second gate's interrupt() instead of
    being rejected -- decision="approved" happened to be a key both payload
    shapes share, so it silently satisfied the second signature too, with
    manager_username landing None (confirmed via the audit log) since no
    manager-role check ever ran. Raises 409 if the thread isn't currently
    paused at expected_node; returns the snapshot's values dict so callers
    that also need it (e.g. the same-person check below) don't fetch state
    twice."""
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    snapshot = graph.get_state(config)
    if snapshot.next != (expected_node,):
        pending = snapshot.next[0] if snapshot.next else None
        detail = _PENDING_NODE_DESCRIPTIONS.get(
            pending, f"This margin call is not currently awaiting this step (pending: {pending!r})."
        )
        raise HTTPException(status_code=409, detail=detail)
    return snapshot.values


@app.post("/margin-calls/{thread_id}/approve", response_model=ApprovalResponse)
async def approve_margin_call(
    thread_id: str, body: ApprovalRequest, approver: str = Depends(require_approver)
) -> ApprovalResponse:
    """PROVISIONAL (see MM-37 note in docs/ROADMAP.md): audit trail
    (who/when, not just role-gating) is still Phase 9's MM-91. Revisit
    before treating as final. approver_username comes from the verified JWT
    (require_approver), never the request body -- so a client can't spoof
    who signed."""
    graph = get_orchestrator_graph()
    _require_pending_node(graph, thread_id, "await_approval")
    resume_payload = {
        "decision": body.decision,
        "adjusted_call_amount": body.adjusted_call_amount,
        "approver_username": approver,
    }
    result = resume_run(graph, thread_id, resume_payload)
    return ApprovalResponse(
        thread_id=thread_id,
        approval_decision=result.get("approval_decision"),
        adjusted_call_amount=result.get("adjusted_call_amount"),
    )


@app.post("/margin-calls/{thread_id}/manager-approve", response_model=ManagerApprovalResponse)
async def manager_approve_margin_call(
    thread_id: str, body: ManagerApprovalRequest, manager: str = Depends(require_manager)
) -> ManagerApprovalResponse:
    """Second signature for elite-tier counterparties (Phase 9 scope
    addition) -- only reachable once await_manager_approval is the run's
    paused node, now actually enforced by _require_pending_node (previously
    just assumed, incorrectly -- see that function's docstring for the real
    bug this closes). Enforces the same-person block here too: the same
    username can't provide both signatures on one call."""
    graph = get_orchestrator_graph()
    current_state = _require_pending_node(graph, thread_id, "await_manager_approval")
    if current_state.get("first_approver_username") == manager:
        raise HTTPException(
            status_code=403,
            detail="The same person cannot provide both signatures for this margin call.",
        )

    result = resume_run(graph, thread_id, {"decision": body.decision, "manager_username": manager})
    return ManagerApprovalResponse(
        thread_id=thread_id,
        approval_decision=result.get("approval_decision"),
        manager_decision=result.get("manager_decision"),
    )


@app.post("/margin-calls/{thread_id}/respond", response_model=SlaResponse)
async def respond_to_margin_call(
    thread_id: str, _approver: str = Depends(require_approver)
) -> SlaResponse:
    """PROVISIONAL (MM-42): stands in for a real counterparty-facing response
    channel, which doesn't exist in this demo -- simulates the counterparty
    fulfilling the call within the SLA window. See docs/ROADMAP.md's Phase 6
    note; revisit before treating as final."""
    graph = get_orchestrator_graph()
    _require_pending_node(graph, thread_id, "await_sla_response")
    result = resume_run(graph, thread_id, {"responded": True})
    return SlaResponse(thread_id=thread_id, sla_outcome=result.get("sla_outcome"))


@app.get("/margin-calls", response_model=MarginCallFeedResponse)
async def margin_call_feed() -> MarginCallFeedResponse:
    session_factory = get_db_session_factory()
    graph = get_orchestrator_graph()
    with session_factory() as session:
        return list_margin_calls(graph, session)


@app.get("/margin-calls/buckets", response_model=MarginCallBucketFeedResponse)
async def margin_call_buckets() -> MarginCallBucketFeedResponse:
    session_factory = get_db_session_factory()
    graph = get_orchestrator_graph()
    with session_factory() as session:
        return list_margin_call_buckets(graph, session)


@app.get("/margin-calls/counterparty/{counterparty_id}", response_model=MarginCallFeedResponse)
async def margin_calls_for_counterparty(counterparty_id: str) -> MarginCallFeedResponse:
    session_factory = get_db_session_factory()
    graph = get_orchestrator_graph()
    with session_factory() as session:
        return list_margin_calls_for_counterparty(graph, session, counterparty_id)


@app.get("/counterparties/{counterparty_id}/history", response_model=CounterpartyHistoryResponse)
async def counterparty_history_endpoint(
    counterparty_id: str, days: int | None = None
) -> CounterpartyHistoryResponse:
    """Business-facing rollup (Phase 9 scope addition) -- how many margin
    calls, breach rate, average size, over the trailing `days` (omit for
    all-time). Distinct from /margin-calls/counterparty/{id}'s raw list."""
    session_factory = get_db_session_factory()
    graph = get_orchestrator_graph()
    with session_factory() as session:
        result = counterparty_history(graph, session, counterparty_id, days=days)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"No counterparty found for {counterparty_id!r}"
        )
    return result


@app.get("/market-universe", response_model=MarketUniverseResponse)
async def market_universe() -> MarketUniverseResponse:
    return MarketUniverseResponse(tickers=get_settings().market_universe_list)


@app.post("/simulate", response_model=SimulateEventResponse)
async def simulate_event(
    body: SimulateEventRequest, _approver: str = Depends(require_approver)
) -> SimulateEventResponse:
    settings = get_settings()
    if body.ticker not in settings.market_universe_list:
        raise HTTPException(
            status_code=400, detail=f"{body.ticker!r} is not in the curated market universe"
        )
    session_factory = get_db_session_factory()
    with session_factory() as session:
        return trigger_simulation(
            MarketEventType(body.event_type),
            body.ticker,
            body.pct_change / 100,
            session,
            session_factory,
            settings,
        )


@app.get("/margin-calls/{thread_id}/trace", response_model=MarginCallTraceResponse)
async def margin_call_trace(thread_id: str) -> MarginCallTraceResponse:
    graph = get_orchestrator_graph()
    trace = get_margin_call_trace(graph, thread_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"No run found for thread_id {thread_id!r}")
    return trace


@app.get("/margin-calls/{thread_id}/audit-log", response_model=AuditLogResponse)
async def margin_call_audit_log(thread_id: str) -> AuditLogResponse:
    """Immutable audit trail (MM-91) -- a plain SQL table, distinct from
    /trace's checkpoint-derived view above."""
    session_factory = get_db_session_factory()
    graph = get_orchestrator_graph()
    with session_factory() as session:
        audit_log = get_margin_call_audit_log(graph, session, thread_id)
    if audit_log is None:
        raise HTTPException(status_code=404, detail=f"No run found for thread_id {thread_id!r}")
    return audit_log


@app.get("/counterparties", response_model=CounterpartyListResponse)
async def counterparties() -> CounterpartyListResponse:
    session_factory = get_db_session_factory()
    with session_factory() as session:
        return list_counterparty_summaries(session)


@app.get("/exposure", response_model=ExposureBoardResponse)
async def exposure_board() -> ExposureBoardResponse:
    session_factory = get_db_session_factory()
    with session_factory() as session:
        return build_exposure_board(session)


@app.get("/exposure/{counterparty_id}", response_model=CounterpartyExposure)
async def counterparty_exposure(counterparty_id: str) -> CounterpartyExposure:
    session_factory = get_db_session_factory()
    with session_factory() as session:
        result = get_counterparty_exposure(session, counterparty_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"No counterparty found for {counterparty_id!r}"
        )
    return result


@app.get("/prices/{ticker}/history", response_model=PriceHistoryResponse)
async def price_history(ticker: str, days: int = 30) -> PriceHistoryResponse:
    session_factory = get_db_session_factory()
    try:
        with session_factory() as session:
            return get_price_history(session, ticker, days=days)
    except MarketDataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/margin-calls/{thread_id}/check-sla", response_model=SlaResponse)
async def check_margin_call_sla(
    thread_id: str, _approver: str = Depends(require_approver)
) -> SlaResponse:
    """PROVISIONAL (MM-42): re-evaluates whether the SLA deadline has passed.
    A no-op (stays pending) if called before the deadline -- there's no real
    scheduler calling this periodically yet; a human or a future cron would
    call it. See docs/ROADMAP.md's Phase 6 note."""
    graph = get_orchestrator_graph()
    _require_pending_node(graph, thread_id, "await_sla_response")
    result = resume_run(graph, thread_id, {"check": True})
    return SlaResponse(thread_id=thread_id, sla_outcome=result.get("sla_outcome"))
