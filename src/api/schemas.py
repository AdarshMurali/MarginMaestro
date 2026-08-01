from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class ApprovalRequest(BaseModel):
    """decision must be one of MarginCallState.approval_decision's literals.
    adjusted_call_amount is only read when decision == "adjusted"."""

    decision: Literal["approved", "rejected", "adjusted"]
    adjusted_call_amount: float | None = None


class ApprovalResponse(BaseModel):
    thread_id: str
    approval_decision: str | None = None
    adjusted_call_amount: float | None = None
