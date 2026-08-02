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
