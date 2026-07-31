from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from config.settings import get_settings
from persistence.models import RatingGrade
from streaming.market_feed import CompositeMarketFeed, MarketFeed, PriceQuote
from streaming.producer import EventProducer
from streaming.schemas import MarketEvent, MarketEventType


@dataclass(frozen=True)
class PriceScenario:
    event_type: MarketEventType
    ticker_deltas: dict[str, float]  # ticker -> pct change applied to a real baseline price


# Price-driven scenarios: a scripted % move layered on a real baseline price
# (per project convention -- synthetic mimics real shape, not fabricated from
# scratch). Tickers are drawn from the curated MARKET_UNIVERSE.
_PRICE_SCENARIOS: dict[MarketEventType, PriceScenario] = {
    MarketEventType.PRICE_SHOCK: PriceScenario(
        MarketEventType.PRICE_SHOCK, {"TSLA": -0.12, "NVDA": -0.10}
    ),
    MarketEventType.VOL_SPIKE: PriceScenario(
        MarketEventType.VOL_SPIKE, {"BTC-USD": -0.18, "ETH-USD": -0.16, "SOL-USD": -0.20}
    ),
}

# Downgrade is not price-driven -- a rating change has no tick to derive it from,
# so it's authored directly as a MarketEvent. Fixed to one curated demo
# counterparty/pair (golden rule: curated demo universe, not open-world).
_DOWNGRADE_COUNTERPARTY_ID = "CP-4"
_DOWNGRADE_FROM = RatingGrade.A
_DOWNGRADE_TO = RatingGrade.BBB


class SimulatedMarketFeed:
    """Satisfies the MarketFeed protocol. With no scenario, it's a pure pass-through
    over a real feed (used by get_market_feed()'s MARKET_FEED_MODE=simulated branch,
    e.g. for the batch loader). With a scenario, it applies that scenario's scripted
    % deltas on top of real baseline prices (used by the Kafka producer CLI)."""

    def __init__(
        self, scenario: MarketEventType | None = None, base_feed: MarketFeed | None = None
    ) -> None:
        self._scenario = _PRICE_SCENARIOS.get(scenario) if scenario is not None else None
        self._base_feed = base_feed or CompositeMarketFeed()

    def get_prices(self, tickers: list[str]) -> dict[str, PriceQuote]:
        base_prices = self._base_feed.get_prices(tickers)
        if self._scenario is None:
            return base_prices

        results: dict[str, PriceQuote] = {}
        for ticker, quote in base_prices.items():
            delta = self._scenario.ticker_deltas.get(ticker, 0.0)
            results[ticker] = quote.model_copy(
                update={
                    "price": quote.price * (1 + delta),
                    "source": f"simulated:{self._scenario.event_type}",
                }
            )
        return results


def _build_downgrade_event() -> MarketEvent:
    return MarketEvent(
        event_id=str(uuid4()),
        event_type=MarketEventType.DOWNGRADE,
        counterparty_id=_DOWNGRADE_COUNTERPARTY_ID,
        description=(
            f"{_DOWNGRADE_COUNTERPARTY_ID} downgraded {_DOWNGRADE_FROM} -> {_DOWNGRADE_TO}"
        ),
        occurred_at=datetime.now(UTC),
    )


def run_scenario(
    scenario: MarketEventType,
    producer: EventProducer | None = None,
    base_feed: MarketFeed | None = None,
) -> None:
    """Publishes a scripted scenario onto market.prices (price_shock/vol_spike) or
    market.events (downgrade). Used by `make simulate SCENARIO=...`."""
    settings = get_settings()
    producer = producer or EventProducer(settings)

    if scenario is MarketEventType.DOWNGRADE:
        event = _build_downgrade_event()
        producer.publish(settings.kafka_topic_events, event, key=event.counterparty_id)
    else:
        feed = SimulatedMarketFeed(scenario=scenario, base_feed=base_feed)
        tickers = list(_PRICE_SCENARIOS[scenario].ticker_deltas)
        for ticker, quote in feed.get_prices(tickers).items():
            producer.publish(settings.kafka_topic_prices, quote, key=ticker)

    producer.flush()
