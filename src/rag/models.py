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
