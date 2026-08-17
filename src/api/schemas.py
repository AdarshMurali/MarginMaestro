from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


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
    REJECTED = "rejected"
    AWAITING_SLA_RESPONSE = "awaiting_sla_response"
    SLA_MET = "sla_met"
    ESCALATED = "escalated"


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


class MarginCallFeedResponse(BaseModel):
    as_of: datetime
    margin_calls: list[MarginCallSummary]


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


class SimulateEventResponse(BaseModel):
    event_type: str
    reason: str
    affected_counterparties: list[SimulatedCounterpartyResult]


class MarketUniverseResponse(BaseModel):
    tickers: list[str]


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


class SlaResponse(BaseModel):
    """sla_outcome is None while the run is still within the SLA window and
    no response signal has arrived yet -- not an error, just not resolved."""

    thread_id: str
    sla_outcome: str | None = None
