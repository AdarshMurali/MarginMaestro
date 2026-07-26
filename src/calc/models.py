from pydantic import BaseModel


class PricingError(Exception):
    """Raised when a calculation can't proceed due to missing/invalid input data."""


class PositionMTM(BaseModel):
    position_id: str
    ticker: str
    quantity: float
    price: float
    mtm: float


class PortfolioMTM(BaseModel):
    portfolio_id: str
    positions: list[PositionMTM]
    total_mtm: float
