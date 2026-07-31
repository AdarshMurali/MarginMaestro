from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest

from config.settings import Settings
from streaming.market_feed import (
    CoinGeckoFeed,
    CompositeMarketFeed,
    MarketDataUnavailableError,
    PriceQuote,
    YFinanceFeed,
    get_market_feed,
)


def _fake_yf_tickers(prices: dict[str, float | None]) -> MagicMock:
    fake = MagicMock()
    ticker_objs = {}
    for ticker, price in prices.items():
        ticker_obj = MagicMock()
        ticker_obj.fast_info = {} if price is None else {"last_price": price}
        ticker_objs[ticker] = ticker_obj
    fake.tickers = ticker_objs
    return fake


class TestYFinanceFeed:
    def test_returns_prices_for_all_tickers(self) -> None:
        with patch(
            "streaming.market_feed.yf.Tickers",
            return_value=_fake_yf_tickers({"AAPL": 210.5, "SPY": 550.1}),
        ):
            result = YFinanceFeed().get_prices(["AAPL", "SPY"])

        assert result["AAPL"].price == 210.5
        assert result["AAPL"].source == "yfinance"
        assert result["SPY"].price == 550.1

    def test_missing_price_raises(self) -> None:
        with (
            patch(
                "streaming.market_feed.yf.Tickers",
                return_value=_fake_yf_tickers({"AAPL": 210.5, "BADTICKER": None}),
            ),
            pytest.raises(MarketDataUnavailableError, match="BADTICKER"),
        ):
            YFinanceFeed().get_prices(["AAPL", "BADTICKER"])

    def test_empty_list_returns_empty_without_calling_yfinance(self) -> None:
        with patch("streaming.market_feed.yf.Tickers") as mock_tickers:
            result = YFinanceFeed().get_prices([])
        assert result == {}
        mock_tickers.assert_not_called()


def _mock_transport(json_body: dict, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=json_body)

    return httpx.MockTransport(handler)


class TestCoinGeckoFeed:
    def test_returns_prices_for_all_tickers(self) -> None:
        client = httpx.Client(
            transport=_mock_transport({"bitcoin": {"usd": 65000.0}, "ethereum": {"usd": 3400.0}})
        )
        result = CoinGeckoFeed(client=client).get_prices(["BTC-USD", "ETH-USD"])

        assert result["BTC-USD"].price == 65000.0
        assert result["BTC-USD"].source == "coingecko"
        assert result["ETH-USD"].price == 3400.0

    def test_unmapped_ticker_raises(self) -> None:
        with pytest.raises(MarketDataUnavailableError, match="DOGE-USD"):
            CoinGeckoFeed().get_prices(["DOGE-USD"])

    def test_non_200_status_raises(self) -> None:
        client = httpx.Client(transport=_mock_transport({}, status_code=500))
        with pytest.raises(MarketDataUnavailableError, match="500"):
            CoinGeckoFeed(client=client).get_prices(["BTC-USD"])

    def test_missing_id_in_response_raises(self) -> None:
        client = httpx.Client(transport=_mock_transport({"bitcoin": {"usd": 65000.0}}))
        with pytest.raises(MarketDataUnavailableError, match="ETH-USD"):
            CoinGeckoFeed(client=client).get_prices(["BTC-USD", "ETH-USD"])

    def test_empty_list_returns_empty_without_calling_api(self) -> None:
        client = MagicMock()
        result = CoinGeckoFeed(client=client).get_prices([])
        assert result == {}
        client.get.assert_not_called()


class TestCompositeMarketFeed:
    def test_routes_tickers_to_correct_sub_feed(self) -> None:
        now = datetime.now(UTC)
        equity_feed = MagicMock()
        equity_feed.get_prices.return_value = {
            "AAPL": PriceQuote(ticker="AAPL", price=210.5, as_of=now, source="yfinance")
        }
        crypto_feed = MagicMock()
        crypto_feed.get_prices.return_value = {
            "BTC-USD": PriceQuote(ticker="BTC-USD", price=65000.0, as_of=now, source="coingecko")
        }
        feed = CompositeMarketFeed(equity_feed=equity_feed, crypto_feed=crypto_feed)

        result = feed.get_prices(["AAPL", "BTC-USD"])

        equity_feed.get_prices.assert_called_once_with(["AAPL"])
        crypto_feed.get_prices.assert_called_once_with(["BTC-USD"])
        assert set(result) == {"AAPL", "BTC-USD"}

    def test_skips_calling_sub_feed_with_no_matching_tickers(self) -> None:
        equity_feed = MagicMock()
        equity_feed.get_prices.return_value = {}
        crypto_feed = MagicMock()

        CompositeMarketFeed(equity_feed=equity_feed, crypto_feed=crypto_feed).get_prices(["AAPL"])

        crypto_feed.get_prices.assert_not_called()


class TestGetMarketFeed:
    def test_live_mode_returns_composite_feed(self) -> None:
        settings = Settings(_env_file=None, market_feed_mode="live")
        assert isinstance(get_market_feed(settings), CompositeMarketFeed)

    def test_simulated_mode_returns_simulated_feed(self) -> None:
        from streaming.simulator import SimulatedMarketFeed

        settings = Settings(_env_file=None, market_feed_mode="simulated")
        assert isinstance(get_market_feed(settings), SimulatedMarketFeed)

    def test_unknown_mode_raises_value_error(self) -> None:
        settings = Settings(_env_file=None, market_feed_mode="bogus")
        with pytest.raises(ValueError, match="bogus"):
            get_market_feed(settings)
