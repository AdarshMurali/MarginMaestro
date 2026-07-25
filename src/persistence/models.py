from datetime import date
from enum import StrEnum

from pydantic import BaseModel


class CounterpartyType(StrEnum):
    BANK = "Bank"
    HEDGE_FUND = "Hedge Fund"
    ASSET_MANAGER = "Asset Manager"


class Counterparty(BaseModel):
    id: str
    name: str
    type: CounterpartyType
    country: str


class Portfolio(BaseModel):
    id: str
    counterparty_id: str
    currency: str = "USD"


class AssetClass(StrEnum):
    EQUITY = "equity"
    ETF = "etf"
    CRYPTO = "crypto"


class Position(BaseModel):
    id: str
    portfolio_id: str
    ticker: str
    asset_class: AssetClass
    quantity: float
    trade_date: date


class RatingGrade(StrEnum):
    AAA = "AAA"
    AA = "AA"
    A = "A"
    BBB = "BBB"
    BB = "BB"
    B = "B"
    CCC = "CCC"
    D = "D"


class Rating(BaseModel):
    id: str
    counterparty_id: str
    grade: RatingGrade
    rating_date: date


class CollateralType(StrEnum):
    CASH = "cash"
    SECURITY = "security"


class CollateralItem(BaseModel):
    id: str
    counterparty_id: str
    collateral_type: CollateralType
    ticker: str | None = None
    value_usd: float
    haircut_pct: float
