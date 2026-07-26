from pydantic import BaseModel, Field

from persistence.models import AssetClass


class PricingError(Exception):
    """Raised when a calculation can't proceed due to missing/invalid input data."""


class PositionMTM(BaseModel):
    position_id: str
    ticker: str
    asset_class: AssetClass
    quantity: float
    price: float
    mtm: float


class PortfolioMTM(BaseModel):
    portfolio_id: str
    positions: list[PositionMTM]
    total_mtm: float


class VariationMargin(BaseModel):
    portfolio_id: str
    mtm_today: float
    mtm_prior: float
    variation_margin: float


class InitialMargin(BaseModel):
    portfolio_id: str
    vix_level: float
    vix_multiplier: float
    initial_margin: float


class CSATerms(BaseModel):
    threshold: float = Field(ge=0)
    mta: float = Field(ge=0)
    currency: str = "USD"


class BreachResult(BaseModel):
    breached: bool
    call_amount: float
