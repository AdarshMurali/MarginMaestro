import base64
import binascii
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.orm import Session, sessionmaker

from adapters.factory import get_event_bus
from adapters.pubsub_admin import topic_for_subscription
from agents.orchestrator import build_orchestrator_graph, resume_run
from api.audit_log import get_margin_call_audit_log
from api.auth import (
    Identity,
    require_approver,
    require_internal_caller,
    require_manager,
    require_user,
    verify_credentials,
)
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
from api.rate_limit import ACTION_LIMITER
from api.schemas import (
    ApprovalRequest,
    ApprovalResponse,
    AuditLogResponse,
    AuthVerifyRequest,
    AuthVerifyResponse,
    CounterpartyExposure,
    CounterpartyHistoryResponse,
    CounterpartyListResponse,
    EodLoadResponse,
    ExposureBoardResponse,
    HealthResponse,
    ManagerApprovalRequest,
    ManagerApprovalResponse,
    MarginCallBucketFeedResponse,
    MarginCallFeedResponse,
    MarginCallTraceResponse,
    MarketUniverseResponse,
    PriceHistoryResponse,
    PriceRefreshResponse,
    PublicStatsResponse,
    PubSubPushEnvelope,
    SimulateEventRequest,
    SimulateEventResponse,
    SlaResponse,
)
from api.simulate import trigger_simulation
from config.settings import get_settings
from observability.tracing import configure_tracing
from persistence.daily_close import load_daily_closes, refresh_reference_rates
from persistence.db.engine import get_session_factory
from persistence.db.rls import RLS_SCOPE_KEY, can_see, scope_for
from ports.event_bus import EventBus
from streaming.inbound import PubSubInbound
from streaming.live_feed_publisher import publish_live_prices
from streaming.market_feed import MarketDataUnavailableError
from streaming.pubsub_dispatch import dispatch
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


@lru_cache
def get_push_event_bus() -> EventBus:
    """One publisher per process for the push endpoint (impact sets, dead letters)."""
    return get_event_bus(get_settings())


def approver_action(approver: str = Depends(require_approver)) -> str:
    """Approver-only action, rate limited per user (MM-117)."""
    ACTION_LIMITER.check(approver, get_settings().rate_limit_per_minute)
    return approver


def manager_action(manager: str = Depends(require_manager)) -> str:
    """Manager-only action, rate limited per user (MM-117)."""
    ACTION_LIMITER.check(manager, get_settings().rate_limit_per_minute)
    return manager


def user_session(identity: Identity) -> Session:
    """A DB session scoped to the caller (MM-106): on Postgres, row-level
    security then returns only the counterparties this user may see. The
    scope lookup itself runs firm-wide (the default for internal sessions)."""
    session_factory = get_db_session_factory()
    with session_factory() as lookup:
        scope = scope_for(identity.role, identity.username, lookup)
    return session_factory(info={RLS_SCOPE_KEY: scope})


def _require_thread_visible(identity: Identity, thread_id: str) -> None:
    """For reads that fetch one run straight from the orchestrator (not via a
    scoped session): 404 -- not 403 -- when the run's counterparty is outside
    the caller's scope, so the run's existence isn't revealed."""
    session_factory = get_db_session_factory()
    with session_factory() as lookup:
        scope = scope_for(identity.role, identity.username, lookup)
    if not can_see(scope, thread_id.rsplit(":", 1)[-1]):
        raise HTTPException(status_code=404, detail=f"No run found for thread_id {thread_id!r}")


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
    manager-role check ever ran.

    Checks `snapshot.tasks` (which task names have a real pending
    interrupt), not `snapshot.next` -- found live: `.next` goes empty `()`
    for `await_sla_response` once it's resumed and re-loops back to its own
    internal `interrupt()` call a second time (its `while True` polling
    design, see agents/orchestrator.py's `await_sla_response`), even though
    the thread is genuinely still paused there. `.next` reflects the graph's
    own routing schedule, not "is there a live interrupt right now" -- for
    a node that re-enters its own interrupt() in a loop rather than being
    re-scheduled via a graph edge, only `.tasks` stays reliable across every
    resume. Confirmed `.next` *does* work for the simple, non-looped nodes
    (await_approval, await_manager_approval) -- this bug is specific to
    await_sla_response's polling design, but `.tasks` is correct for both,
    so it's now the single check used everywhere.

    Raises 409 if the thread isn't currently paused at expected_node;
    returns the snapshot's values dict so callers that also need it (e.g.
    the same-person check below) don't fetch state twice."""
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    snapshot = graph.get_state(config)
    pending_names = {task.name for task in snapshot.tasks if task.interrupts}
    if expected_node not in pending_names:
        pending = next(iter(pending_names), None)
        detail = _PENDING_NODE_DESCRIPTIONS.get(
            pending, f"This margin call is not currently awaiting this step (pending: {pending!r})."
        )
        raise HTTPException(status_code=409, detail=detail)
    return snapshot.values


@app.post("/margin-calls/{thread_id}/approve", response_model=ApprovalResponse)
async def approve_margin_call(
    thread_id: str, body: ApprovalRequest, approver: str = Depends(approver_action)
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
    thread_id: str, body: ManagerApprovalRequest, manager: str = Depends(manager_action)
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
    thread_id: str, _approver: str = Depends(approver_action)
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
async def margin_call_feed(identity: Identity = Depends(require_user)) -> MarginCallFeedResponse:
    graph = get_orchestrator_graph()
    with user_session(identity) as session:
        return list_margin_calls(graph, session)


@app.get("/margin-calls/buckets", response_model=MarginCallBucketFeedResponse)
async def margin_call_buckets(
    identity: Identity = Depends(require_user),
) -> MarginCallBucketFeedResponse:
    graph = get_orchestrator_graph()
    with user_session(identity) as session:
        return list_margin_call_buckets(graph, session)


@app.get("/margin-calls/counterparty/{counterparty_id}", response_model=MarginCallFeedResponse)
async def margin_calls_for_counterparty(
    counterparty_id: str, identity: Identity = Depends(require_user)
) -> MarginCallFeedResponse:
    graph = get_orchestrator_graph()
    with user_session(identity) as session:
        return list_margin_calls_for_counterparty(graph, session, counterparty_id)


@app.get("/counterparties/{counterparty_id}/history", response_model=CounterpartyHistoryResponse)
async def counterparty_history_endpoint(
    counterparty_id: str,
    days: int | None = None,
    identity: Identity = Depends(require_user),
) -> CounterpartyHistoryResponse:
    """Business-facing rollup (Phase 9 scope addition) -- how many margin
    calls, breach rate, average size, over the trailing `days` (omit for
    all-time). Distinct from /margin-calls/counterparty/{id}'s raw list."""
    graph = get_orchestrator_graph()
    with user_session(identity) as session:
        result = counterparty_history(graph, session, counterparty_id, days=days)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"No counterparty found for {counterparty_id!r}"
        )
    return result


@app.get("/public/stats", response_model=PublicStatsResponse)
async def public_stats() -> PublicStatsResponse:
    """Unauthenticated aggregate counts for the public landing page (MM-106):
    no counterparty names, ids or amounts -- just totals. Every other read
    endpoint requires a login."""
    session_factory = get_db_session_factory()
    graph = get_orchestrator_graph()
    with session_factory() as session:
        counterparty_count = len(list_counterparty_summaries(session).counterparties)
        calls = list_margin_calls(graph, session).margin_calls
    return PublicStatsResponse(
        counterparties=counterparty_count,
        runs_evaluated=len(calls),
        calls_raised=sum(1 for c in calls if c.call_amount is not None and c.call_amount > 0),
    )


@app.get("/market-universe", response_model=MarketUniverseResponse)
async def market_universe() -> MarketUniverseResponse:
    return MarketUniverseResponse(tickers=get_settings().market_universe_list)


@app.post("/simulate", response_model=SimulateEventResponse)
async def simulate_event(
    body: SimulateEventRequest, _approver: str = Depends(approver_action)
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


@app.post(
    "/internal/prices/refresh",
    response_model=PriceRefreshResponse,
    dependencies=[Depends(require_internal_caller)],
)
def refresh_prices() -> PriceRefreshResponse:
    """Scheduled every 5 minutes in market hours (MM-120): publishes one tick
    per ticker to market.prices; the Event Agent upserts latest_prices and
    raises an impact set on a big move. Sync so the feed call runs in the
    threadpool, not on the event loop."""
    settings = get_settings()
    try:
        published = publish_live_prices(settings.market_universe_list, settings=settings)
    except MarketDataUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return PriceRefreshResponse(published=published)


@app.post(
    "/internal/prices/eod",
    response_model=EodLoadResponse,
    dependencies=[Depends(require_internal_caller)],
)
def load_end_of_day() -> EodLoadResponse:
    """Scheduled once a day after the US close (MM-124): official daily
    closes into price_history (with a short back-fill window) and FRED
    reference rates. Internal jobs run firm-wide, so no user scope."""
    settings = get_settings()
    session_factory = get_db_session_factory()
    with session_factory() as session:
        closes = load_daily_closes(session, settings.market_universe_list)
        rates = refresh_reference_rates(session, settings)
    return EodLoadResponse(
        tickers_loaded=len(closes["loaded"]), tickers_failed=closes["failed"], reference_rates=rates
    )


@app.post(
    "/internal/pubsub/push",
    status_code=204,
    dependencies=[Depends(require_internal_caller)],
)
def pubsub_push(envelope: PubSubPushEnvelope) -> Response:
    """Pub/Sub push target (MM-121): 2xx acks, anything else makes Pub/Sub
    redeliver (dead-letter after 5 attempts). Same dispatch as the pull
    worker, so prices, events and impact sets are handled identically."""
    settings = get_settings()
    topic = topic_for_subscription(settings, envelope.subscription)
    if topic is None:
        raise HTTPException(status_code=400, detail="Unknown subscription")
    try:
        data = base64.b64decode(envelope.message.data, validate=True)
    except binascii.Error as exc:
        raise HTTPException(status_code=400, detail="Message data is not base64") from exc
    dispatch(
        PubSubInbound(topic, data, envelope.message.ordering_key),
        settings,
        get_db_session_factory(),
        get_push_event_bus(),
    )
    return Response(status_code=204)


@app.post(
    "/internal/sla/{thread_id}/check",
    response_model=SlaResponse,
    dependencies=[Depends(require_internal_caller)],
)
def internal_sla_check(thread_id: str) -> SlaResponse:
    """The SLA timer's target (MM-122): Cloud Tasks calls this at the call's
    deadline. Status codes tell Cloud Tasks what to do:

    - 200: resolved now (met/breached -> escalation), or already resolved
      earlier (e.g. the client responded first) -- nothing to retry.
    - 503: still within the SLA window (the task fired a moment early) --
      Cloud Tasks retries with backoff.
    - 404 / 409: unknown thread, or a thread not at the SLA step."""
    graph = get_orchestrator_graph()
    snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    pending = {task.name for task in snapshot.tasks if task.interrupts}
    if "await_sla_response" not in pending:
        if not snapshot.values:
            raise HTTPException(status_code=404, detail="Unknown margin call")
        outcome = snapshot.values.get("sla_outcome")
        if outcome is None:
            raise HTTPException(status_code=409, detail="Margin call is not at the SLA step")
        return SlaResponse(thread_id=thread_id, sla_outcome=outcome)

    result = resume_run(graph, thread_id, {"check": True})
    if result.get("sla_outcome") is None:
        raise HTTPException(
            status_code=503, detail="SLA deadline not reached yet", headers={"Retry-After": "30"}
        )
    return SlaResponse(thread_id=thread_id, sla_outcome=result["sla_outcome"])


@app.get("/margin-calls/{thread_id}/trace", response_model=MarginCallTraceResponse)
async def margin_call_trace(
    thread_id: str, identity: Identity = Depends(require_user)
) -> MarginCallTraceResponse:
    _require_thread_visible(identity, thread_id)
    graph = get_orchestrator_graph()
    trace = get_margin_call_trace(graph, thread_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"No run found for thread_id {thread_id!r}")
    return trace


@app.get("/margin-calls/{thread_id}/audit-log", response_model=AuditLogResponse)
async def margin_call_audit_log(
    thread_id: str, identity: Identity = Depends(require_user)
) -> AuditLogResponse:
    """Immutable audit trail (MM-91) -- a plain SQL table, distinct from
    /trace's checkpoint-derived view above."""
    _require_thread_visible(identity, thread_id)
    graph = get_orchestrator_graph()
    with user_session(identity) as session:
        audit_log = get_margin_call_audit_log(graph, session, thread_id)
    if audit_log is None:
        raise HTTPException(status_code=404, detail=f"No run found for thread_id {thread_id!r}")
    return audit_log


@app.get("/counterparties", response_model=CounterpartyListResponse)
async def counterparties(identity: Identity = Depends(require_user)) -> CounterpartyListResponse:
    with user_session(identity) as session:
        return list_counterparty_summaries(session)


@app.get("/exposure", response_model=ExposureBoardResponse)
async def exposure_board(identity: Identity = Depends(require_user)) -> ExposureBoardResponse:
    with user_session(identity) as session:
        return build_exposure_board(session)


@app.get("/exposure/{counterparty_id}", response_model=CounterpartyExposure)
async def counterparty_exposure(
    counterparty_id: str, identity: Identity = Depends(require_user)
) -> CounterpartyExposure:
    with user_session(identity) as session:
        result = get_counterparty_exposure(session, counterparty_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"No counterparty found for {counterparty_id!r}"
        )
    return result


@app.get("/prices/{ticker}/history", response_model=PriceHistoryResponse)
async def price_history(
    ticker: str, days: int = 30, _identity: Identity = Depends(require_user)
) -> PriceHistoryResponse:
    # Market data is global (no counterparty rows), but the app is
    # login-only, so reads still require a valid token (MM-106).
    session_factory = get_db_session_factory()
    try:
        with session_factory() as session:
            return get_price_history(session, ticker, days=days)
    except MarketDataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/margin-calls/{thread_id}/check-sla", response_model=SlaResponse)
async def check_margin_call_sla(
    thread_id: str, _approver: str = Depends(approver_action)
) -> SlaResponse:
    """PROVISIONAL (MM-42): re-evaluates whether the SLA deadline has passed.
    A no-op (stays pending) if called before the deadline. The manual path:
    with SLA_SCHEDULER=cloudtasks (MM-122) a timer calls
    /internal/sla/{thread_id}/check at the deadline instead."""
    graph = get_orchestrator_graph()
    _require_pending_node(graph, thread_id, "await_sla_response")
    result = resume_run(graph, thread_id, {"check": True})
    return SlaResponse(thread_id=thread_id, sla_outcome=result.get("sla_outcome"))
