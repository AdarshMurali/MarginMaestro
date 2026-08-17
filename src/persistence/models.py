from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CounterpartyType(StrEnum):
    BANK = "Bank"
    HEDGE_FUND = "Hedge Fund"
    ASSET_MANAGER = "Asset Manager"


class CounterpartyTier(StrEnum):
    """Standard tier keeps the single-approver gate (MM-37); elite tier
    requires a second, different approver's sign-off (Phase 9 scope
    addition) -- deterministic config, not an LLM judgment call, per
    CLAUDE.md golden rule 1."""

    STANDARD = "standard"
    ELITE = "elite"


class Counterparty(BaseModel):
    id: str
    name: str
    type: CounterpartyType
    country: str
    tier: CounterpartyTier = CounterpartyTier.STANDARD


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


# Best-to-worst credit quality order -- lets code compare two RatingGrade
# values ("is X below Y?") without relying on the enum's declaration order
# (StrEnum has no built-in ordering).
RATING_ORDER: list[RatingGrade] = [
    RatingGrade.AAA,
    RatingGrade.AA,
    RatingGrade.A,
    RatingGrade.BBB,
    RatingGrade.BB,
    RatingGrade.B,
    RatingGrade.CCC,
    RatingGrade.D,
]


class RatingTrigger(BaseModel):
    """A CSA clause: if the counterparty's rating falls below `below_grade`,
    the Threshold is reduced to `reduced_threshold` (deterministic clause
    application -- CLAUDE.md golden rule 1; the LLM only ever extracts what
    the document says, never decides the number)."""

    below_grade: RatingGrade
    reduced_threshold: float = Field(ge=0)


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


class LatestPrice(BaseModel):
    ticker: str
    price: float
    currency: str = "USD"
    source: str
    as_of: datetime


class PriceHistoryEntry(BaseModel):
    date: date
    price: float
