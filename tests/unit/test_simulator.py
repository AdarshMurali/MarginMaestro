from datetime import UTC, datetime
from unittest.mock import MagicMock

from persistence.models import RatingGrade
from streaming.market_feed import MarketFeed, PriceQuote
from streaming.schemas import MarketEvent, MarketEventType
from streaming.simulator import PriceScenario, SimulatedMarketFeed, run_scenario


class _StubFeed:
    def __init__(self, prices: dict[str, PriceQuote]) -> None:
        self._prices = prices

    def get_prices(self, tickers: list[str]) -> dict[str, PriceQuote]:
        return {t: self._prices[t] for t in tickers if t in self._prices}


def _quote(ticker: str, price: float) -> PriceQuote:
    return PriceQuote(ticker=ticker, price=price, as_of=datetime.now(UTC), source="yfinance")


class TestSimulatedMarketFeed:
    def test_passthrough_when_no_scenario_given(self) -> None:
        base = _StubFeed({"AAPL": _quote("AAPL", 200.0)})
        feed: MarketFeed = SimulatedMarketFeed(price_scenario=None, base_feed=base)

        result = feed.get_prices(["AAPL"])

        assert result["AAPL"].price == 200.0
        assert result["AAPL"].source == "yfinance"

    def test_applies_scenario_delta_on_top_of_real_baseline(self) -> None:
        base = _StubFeed({"TSLA": _quote("TSLA", 100.0), "NVDA": _quote("NVDA", 50.0)})
        scenario = PriceScenario(MarketEventType.PRICE_SHOCK, {"TSLA": -0.12, "NVDA": -0.10})
        feed = SimulatedMarketFeed(price_scenario=scenario, base_feed=base)

        result = feed.get_prices(["TSLA", "NVDA"])

        assert result["TSLA"].price == 88.0  # -12%
        assert result["NVDA"].price == 45.0  # -10%
        assert result["TSLA"].source == "simulated:price_shock"

    def test_ticker_not_in_scenario_is_left_unshocked(self) -> None:
        base = _StubFeed({"AAPL": _quote("AAPL", 200.0)})
        scenario = PriceScenario(MarketEventType.PRICE_SHOCK, {"TSLA": -0.12})
        feed = SimulatedMarketFeed(price_scenario=scenario, base_feed=base)

        result = feed.get_prices(["AAPL"])

        assert result["AAPL"].price == 200.0


class TestRunScenario:
    def test_price_shock_publishes_shocked_prices_to_prices_topic(self) -> None:
        base = _StubFeed({"TSLA": _quote("TSLA", 100.0), "NVDA": _quote("NVDA", 50.0)})
        producer = MagicMock()

        run_scenario(MarketEventType.PRICE_SHOCK, producer=producer, base_feed=base)

        published_topics = {call.args[0] for call in producer.publish.call_args_list}
        assert published_topics == {"market.prices"}
        assert producer.publish.call_count == 2
        producer.flush.assert_called_once()

    def test_vol_spike_publishes_all_scenario_tickers(self) -> None:
        base = _StubFeed(
            {
                "BTC-USD": _quote("BTC-USD", 60000.0),
                "ETH-USD": _quote("ETH-USD", 3000.0),
                "SOL-USD": _quote("SOL-USD", 150.0),
            }
        )
        producer = MagicMock()

        run_scenario(MarketEventType.VOL_SPIKE, producer=producer, base_feed=base)

        assert producer.publish.call_count == 3
        producer.flush.assert_called_once()

    def test_downgrade_publishes_event_to_events_topic_and_skips_price_feed(self) -> None:
        producer = MagicMock()
        base = MagicMock()

        run_scenario(MarketEventType.DOWNGRADE, producer=producer, base_feed=base)

        base.get_prices.assert_not_called()
        producer.publish.assert_called_once()
        args, kwargs = producer.publish.call_args
        assert args[0] == "market.events"
        published_event = args[1]
        assert isinstance(published_event, MarketEvent)
        assert published_event.event_type == MarketEventType.DOWNGRADE
        assert published_event.counterparty_id == "CP-4"
        assert published_event.new_rating_grade == RatingGrade.BBB
        assert kwargs["key"] == "CP-4"
        producer.flush.assert_called_once()
