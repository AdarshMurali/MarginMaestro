from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


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


class MarginCallFeedResponse(BaseModel):
    as_of: datetime
    margin_calls: list[MarginCallSummary]


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
