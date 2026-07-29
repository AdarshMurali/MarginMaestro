from datetime import date

from pydantic import BaseModel


class CSATermsDocument(BaseModel):
    counterparty_id: str
    counterparty_name: str
    threshold: float
    mta: float
    currency: str
    eligible_collateral: list[str]
    haircuts: dict[str, float]
    rating_triggers: list[str]
    effective_date: date


class Citation(BaseModel):
    source_file: str
    section: str


class CSATermsResult(BaseModel):
    counterparty_id: str
    threshold: float
    mta: float
    currency: str
    eligible_collateral: list[str]
    haircuts: dict[str, float]
    rating_triggers: list[str]
    citations: list[Citation]
