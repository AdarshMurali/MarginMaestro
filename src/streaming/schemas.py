from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class MarketEventType(StrEnum):
    PRICE_SHOCK = "price_shock"
    VOL_SPIKE = "vol_spike"
    DOWNGRADE = "downgrade"


class MarketEvent(BaseModel):
    """A non-price market event -- currently just rating downgrades, which have
    no price tick for the Event Agent (MM-31) to derive them from."""

    event_id: str
    event_type: MarketEventType
    counterparty_id: str | None = None
    tickers: list[str] = []
    description: str
    occurred_at: datetime


class ImpactSet(BaseModel):
    """The Event Agent's (MM-31) output: which counterparties a classified
    market event affects. Published on its own topic (market.impact), not
    back onto market.events, so the Event Agent never re-consumes its own
    output. event_id ties back to the originating price tick or MarketEvent
    and doubles as the idempotency key."""

    event_id: str
    event_type: MarketEventType
    counterparty_ids: list[str]
    reason: str
    occurred_at: datetime
