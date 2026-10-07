from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str


class CounterpartySummary(BaseModel):
    """Names-only listing (MM-62) -- deliberately excludes status, which
    requires the same expensive per-counterparty price/CSA/VIX computation
    as the full exposure board. The list page shows names only; status only
    ever appears on the (already fast, MM-61) per-counterparty detail page."""

    counterparty_id: str
    counterparty_name: str


class CounterpartyListResponse(BaseModel):
    counterparties: list[CounterpartySummary]


class ExposureStatus(StrEnum):
    """Drives the dashboard's status-light color (docs/ROADMAP.md Phase 8
    design note): HEALTHY=green, AT_RISK=amber, BREACHED=red. UNAVAILABLE
    (no status-light color -- rendered neutrally) covers a counterparty this
    board genuinely can't evaluate this request (e.g. no CSA document
    ingested for it, or a position's ticker can't be priced) -- distinct
    from a real breach, never silently coerced into one of the real states."""

    HEALTHY = "healthy"
    AT_RISK = "at_risk"
    BREACHED = "breached"
    UNAVAILABLE = "unavailable"


class PositionExposure(BaseModel):
    ticker: str
    asset_class: str
    quantity: float
    price: float
    mtm: float


class CounterpartyExposure(BaseModel):
    counterparty_id: str
    counterparty_name: str
    positions: list[PositionExposure]
    exposure: float | None = None
    threshold: float | None = None
    collateral_held: float | None = None
    call_amount: float | None = None
    status: ExposureStatus
    currency: str = "USD"
    # Human-readable reason when status is UNAVAILABLE; None otherwise.
    detail: str | None = None


class ExposureBoardResponse(BaseModel):
    as_of: datetime
    counterparties: list[CounterpartyExposure]


class PricePoint(BaseModel):
    date: date
    price: float


class PriceHistoryResponse(BaseModel):
    ticker: str
    currency: str = "USD"
    points: list[PricePoint]


class MarginCallLifecycleStatus(StrEnum):
    """Mirrors agents.orchestrator's actual graph routing (docs/AGENTS.md's
    lifecycle), not an independent state machine -- see api/margin_calls.py's
    _lifecycle_status for exactly how each value maps to MarginCallState
    fields. EVALUATING never persists in practice (the graph runs straight
    through to its first interrupt or NO_BREACH/END before any checkpoint
    write completes) but is kept as a defensive fallback, not a real steady
    state a run sits in."""

    EVALUATING = "evaluating"
    NO_BREACH = "no_breach"
    AWAITING_APPROVAL = "awaiting_approval"
    # MM-79 follow-up: elite-tier counterparties (MM-70's two-person sign-off)
    # have a second gate distinct from AWAITING_APPROVAL -- previously both
    # gates collapsed onto AWAITING_APPROVAL, so the frontend had no way to
    # tell a "needs an approver" call apart from a "needs a manager" one,
    # found live when a manager couldn't see any actionable card for a run
    # actually waiting on them.
    AWAITING_MANAGER_APPROVAL = "awaiting_manager_approval"
    REJECTED = "rejected"
    # A manager overturning an already-approved first decision -- distinct
    # from REJECTED (which means nobody ever approved it). Previously fell
    # through to AWAITING_APPROVAL incorrectly (a real, adjacent bug fixed
    # alongside AWAITING_MANAGER_APPROVAL above), since nothing checked for
    # approval_decision == "disputed" before falling back to breach_result.
    DISPUTED = "disputed"
    AWAITING_SLA_RESPONSE = "awaiting_sla_response"
    SLA_MET = "sla_met"
    ESCALATED = "escalated"
    # MM-125: a breach the intraday materiality gate held -- the event alone
    # didn't move exposure by more than the MTA, so no call; the standing
    # breach is the daily margin run's job.
    BELOW_MATERIALITY = "below_materiality"


class MarginCallSummary(BaseModel):
    thread_id: str
    correlation_id: str
    counterparty_id: str
    event_type: str
    reason: str
    occurred_at: datetime
    status: MarginCallLifecycleStatus
    call_amount: float | None = None
    currency: str = "USD"
    approval_decision: str | None = None
    sla_outcome: str | None = None
    notification_sent_at: datetime | None = None
    # notification_sent_at + Settings.margin_call_sla_minutes -- computed
    # server-side so the frontend doesn't need to know the SLA policy.
    sla_deadline: datetime | None = None
    # MM-125: why the call (or no call), from code; and the later triggers
    # that re-evaluated this call in place instead of raising another.
    rationale: str | None = None
    updated_by: list[str] = Field(default_factory=list)


class MarginCallFeedResponse(BaseModel):
    as_of: datetime
    margin_calls: list[MarginCallSummary]


class CounterpartyHistoryResponse(BaseModel):
    """Business-facing rollup (Phase 9 scope addition), distinct from
    MarginCallFeedResponse's raw per-run list (MM-63) -- how many margin
    calls this counterparty has had, what fraction actually breached, and
    the average size of the ones that did, over `period_days` (None means
    all-time). An aggregation over already-persisted run data, not a new
    logging mechanism -- see docs/PROGRESS.md's handoff entry."""

    counterparty_id: str
    counterparty_name: str
    as_of: datetime
    period_days: int | None
    total_calls: int
    breached_calls: int
    breach_rate: float
    average_call_amount: float | None
    currency: str = "USD"


class MarginCallBucket(BaseModel):
    """One row per counterparty (MM-63) -- `latest` is whichever call is
    most URGENT for this counterparty (awaiting approval > escalated >
    awaiting SLA response > resolved), not necessarily the most recent one
    chronologically, so an older unresolved call never gets silently
    buried under a newer resolved one. `total_count` is every call this
    counterparty has ever had, for a "+N more" indicator."""

    counterparty_id: str
    counterparty_name: str
    latest: MarginCallSummary
    total_count: int


class MarginCallBucketFeedResponse(BaseModel):
    as_of: datetime
    buckets: list[MarginCallBucket]


class TraceStepStatus(StrEnum):
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"


class TraceStep(BaseModel):
    step: int
    node: str
    status: TraceStepStatus
    completed_at: datetime | None = None
    summary: str


class MarginCallTraceResponse(BaseModel):
    thread_id: str
    steps: list[TraceStep]


class AuditLogEntry(BaseModel):
    """One immutable row from audit_log (MM-91) -- distinct from TraceStep
    above: this is read from a plain insert-only SQL table, not
    reconstructed from LangGraph's own checkpoint history, so it's reliable
    independent of the checkpointer's known ability to silently drop a
    checkpoint row under concurrent writes."""

    event_type: str
    payload: dict | None
    created_at: datetime


class AuditLogResponse(BaseModel):
    thread_id: str
    correlation_id: str
    entries: list[AuditLogEntry]


class SimulateEventRequest(BaseModel):
    """A user-chosen single-ticker shock: which of the two price-driven event
    types to label it as, which curated-universe ticker to shock, and a
    signed %% delta on top of that ticker's real current price. MarketEventType
    also has "downgrade", but that's not a %%-delta-on-a-ticker event -- it's
    authored via `make simulate SCENARIO=downgrade` (streaming/simulator.py)
    instead, which now does feed into evaluate_breach via rating_triggers.
    Scoped out of this ticker/%% panel deliberately, not missing. Ticker is
    checked against the curated MARKET_UNIVERSE in the endpoint (golden rule
    #7 -- not validated here since that list lives on Settings, not this
    schema)."""

    event_type: Literal["price_shock", "vol_spike"]
    ticker: str
    # Percent, not fraction -- e.g. -12.5 means -12.5%. Bounds are a sanity
    # guard against fat-fingered input, not a real-world volatility limit.
    pct_change: float = Field(..., ge=-99, le=500)


class SimulatedCounterpartyResult(BaseModel):
    counterparty_id: str
    thread_id: str | None = None
    breached: bool | None = None
    call_amount: float | None = None
    # Set when this counterparty's run couldn't be evaluated (e.g. no CSA
    # document, missing price history) -- the other counterparties' results
    # still return normally rather than the whole request failing.
    error: str | None = None
    # MM-125: "started" (a new run), "updated" (the counterparty's open call
    # was re-evaluated in place) or "unchanged" (an open call exists and this
    # event leaves it as is); `detail` says why, from code.
    action: str | None = None
    detail: str | None = None


class SimulateEventResponse(BaseModel):
    event_type: str
    reason: str
    affected_counterparties: list[SimulatedCounterpartyResult]


class PriceRefreshResponse(BaseModel):
    published: int


class EodLoadResponse(BaseModel):
    tickers_loaded: int
    tickers_failed: list[str]
    reference_rates: int


class DailyRunOutcome(BaseModel):
    """One counterparty's result in the daily margin run (MM-125): a new run
    started, the open call updated in place, or the open call left as is."""

    counterparty_id: str
    action: Literal["started", "updated", "unchanged"]
    thread_id: str
    breached: bool | None = None
    call_amount: float | None = None
    detail: str | None = None


class DailyMarginRunResponse(BaseModel):
    event_id: str
    counterparties: int
    # Counterparties dispatched by this request; ones already done today, or
    # held (e.g. no CSA document), are not listed.
    outcomes: list[DailyRunOutcome]


class WarehouseLoadResponse(BaseModel):
    """POST /internal/warehouse/daily-load (MM-141): rows written per table
    for the live book's day, and the counterparties that couldn't be priced."""

    as_of: date
    rows: dict[str, int]
    skipped: list[str]


class ReportsStatusResponse(BaseModel):
    """GET /reports/status (MM-142): whether the warehouse is configured and
    which books the caller may see."""

    configured: bool
    books: list[str]
    scoped: bool


class PubSubPushMessage(BaseModel):
    """Pub/Sub push body's `message` (MM-121); `data` is base64."""

    model_config = ConfigDict(populate_by_name=True)

    data: str = ""
    message_id: str = Field(default="", alias="messageId")
    ordering_key: str = Field(default="", alias="orderingKey")


class PubSubPushEnvelope(BaseModel):
    message: PubSubPushMessage
    subscription: str


class MarketUniverseResponse(BaseModel):
    tickers: list[str]


class PublicStatsResponse(BaseModel):
    """Aggregate totals for the public landing page (MM-106) -- no
    counterparty-level data."""

    counterparties: int
    runs_evaluated: int
    calls_raised: int


class RealtimeTokenResponse(BaseModel):
    """A Firebase custom token for the browser's Firestore listener (MM-146).
    `counterparty_ids` / `firm_wide` repeat the token's claims so the browser
    can shape its query to what the security rules will allow."""

    token: str
    collection: str
    firm_wide: bool
    counterparty_ids: list[str]
    expires_in: int


class AuthVerifyRequest(BaseModel):
    username: str
    password: str


class AuthVerifyResponse(BaseModel):
    username: str
    role: str


class ApprovalRequest(BaseModel):
    """decision must be one of MarginCallState.approval_decision's literals.
    adjusted_call_amount is only read when decision == "adjusted"."""

    decision: Literal["approved", "rejected", "adjusted"]
    adjusted_call_amount: float | None = None


class ApprovalResponse(BaseModel):
    thread_id: str
    approval_decision: str | None = None
    adjusted_call_amount: float | None = None


class ManagerApprovalRequest(BaseModel):
    """Second signature for elite-tier counterparties (Phase 9 scope
    addition) -- must be one of MarginCallState.manager_decision's
    literals, intentionally narrower than the first approver's (no
    "adjusted": the manager ratifies or overturns, never re-adjusts)."""

    decision: Literal["approved", "rejected"]


class ManagerApprovalResponse(BaseModel):
    thread_id: str
    approval_decision: str | None = None
    manager_decision: str | None = None


class SlaResponse(BaseModel):
    """sla_outcome is None while the run is still within the SLA window and
    no response signal has arrived yet -- not an error, just not resolved."""

    thread_id: str
    sla_outcome: str | None = None
