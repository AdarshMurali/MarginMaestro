from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import httpx
import pandas as pd
import pytest

from config.settings import Settings
from streaming.market_feed import (
    CoinGeckoFeed,
    CompositeMarketFeed,
    MarketDataUnavailableError,
    PriceQuote,
    YFinanceFeed,
    _coingecko_history,
    _get_with_retry,
    get_market_feed,
    get_price_history,
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


def _sequenced_transport(
    responses: list[tuple[int, dict]],
) -> tuple[httpx.MockTransport, MagicMock]:
    """Returns responses in order, repeating the last one -- lets tests
    script "429 then 429 then 200" without a stateful fixture per test."""
    calls = MagicMock()

    def handler(request: httpx.Request) -> httpx.Response:
        calls(request)
        index = min(calls.call_count - 1, len(responses) - 1)
        status_code, body = responses[index]
        headers = {}
        return httpx.Response(status_code, json=body, headers=headers)

    return httpx.MockTransport(handler), calls


class TestGetWithRetry:
    def test_succeeds_immediately_without_retrying(self) -> None:
        client = httpx.Client(transport=_mock_transport({"ok": True}))
        sleep = MagicMock()

        response = _get_with_retry(client, "http://x/y", params={}, sleep=sleep)

        assert response.status_code == 200
        sleep.assert_not_called()

    def test_retries_on_429_then_succeeds(self) -> None:
        transport, calls = _sequenced_transport([(429, {}), (429, {}), (200, {"ok": True})])
        client = httpx.Client(transport=transport)
        sleep = MagicMock()

        response = _get_with_retry(client, "http://x/y", params={}, sleep=sleep)

        assert response.status_code == 200
        assert calls.call_count == 3
        assert sleep.call_count == 2
        # Exponential: backoff_seconds * 2**0, then * 2**1
        assert sleep.call_args_list[0].args[0] == pytest.approx(1.0)
        assert sleep.call_args_list[1].args[0] == pytest.approx(2.0)

    def test_gives_up_after_max_retries_and_returns_the_429(self) -> None:
        transport, calls = _sequenced_transport([(429, {})])
        client = httpx.Client(transport=transport)
        sleep = MagicMock()

        response = _get_with_retry(client, "http://x/y", params={}, max_retries=2, sleep=sleep)

        assert response.status_code == 429
        assert calls.call_count == 3  # initial + 2 retries
        assert sleep.call_count == 2

    def test_non_429_status_is_not_retried(self) -> None:
        transport, calls = _sequenced_transport([(500, {})])
        client = httpx.Client(transport=transport)
        sleep = MagicMock()

        response = _get_with_retry(client, "http://x/y", params={}, sleep=sleep)

        assert response.status_code == 500
        assert calls.call_count == 1
        sleep.assert_not_called()

    def test_retry_after_header_overrides_exponential_backoff(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(429, headers={"Retry-After": "5"}, json={})
            return httpx.Response(200, json={"ok": True})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        sleep = MagicMock()

        response = _get_with_retry(client, "http://x/y", params={}, sleep=sleep)

        assert response.status_code == 200
        sleep.assert_called_once_with(5.0)


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

    def test_retries_a_transient_429_and_still_returns_prices(self) -> None:
        transport, calls = _sequenced_transport([(429, {}), (200, {"bitcoin": {"usd": 65000.0}})])
        client = httpx.Client(transport=transport)

        with patch("streaming.market_feed.time.sleep") as mock_sleep:
            result = CoinGeckoFeed(client=client).get_prices(["BTC-USD"])

        assert result["BTC-USD"].price == 65000.0
        assert calls.call_count == 2
        mock_sleep.assert_called_once()


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


class TestGetPriceHistory:
    def test_equity_ticker_routes_to_yfinance(self) -> None:
        fake_history = pd.DataFrame(
            {"Close": [210.5, 212.0]},
            index=pd.DatetimeIndex([date(2026, 7, 1), date(2026, 7, 2)]),
        )
        fake_ticker = MagicMock()
        fake_ticker.history.return_value = fake_history
        with patch("streaming.market_feed.yf.Ticker", return_value=fake_ticker) as mock_ticker:
            result = get_price_history("AAPL", days=5)

        mock_ticker.assert_called_once_with("AAPL")
        assert [p.price for p in result] == [210.5, 212.0]
        assert result[0].date == date(2026, 7, 1)

    def test_yfinance_empty_history_raises(self) -> None:
        fake_ticker = MagicMock()
        fake_ticker.history.return_value = pd.DataFrame()
        with (
            patch("streaming.market_feed.yf.Ticker", return_value=fake_ticker),
            pytest.raises(MarketDataUnavailableError, match="BADTICKER"),
        ):
            get_price_history("BADTICKER", days=5)

    def test_crypto_ticker_routes_to_coingecko(self) -> None:
        client = httpx.Client(
            transport=_mock_transport(
                {
                    "prices": [
                        [1785715200000, 65000.0],
                        [1785801600000, 66000.0],
                    ]
                }
            )
        )
        result = get_price_history("BTC-USD", days=5, client=client)

        assert [p.price for p in result] == [65000.0, 66000.0]

    def test_crypto_unmapped_ticker_raises(self) -> None:
        """Only reachable if CRYPTO_TICKERS and COINGECKO_ID_MAP ever drift --
        today the two sets are identical, so this guard is exercised directly
        rather than through get_price_history's asset-class routing."""
        with pytest.raises(MarketDataUnavailableError, match="DOGE-USD"):
            _coingecko_history("DOGE-USD", days=5)

    def test_crypto_non_200_status_raises(self) -> None:
        client = httpx.Client(transport=_mock_transport({}, status_code=500))
        with pytest.raises(MarketDataUnavailableError, match="500"):
            get_price_history("BTC-USD", days=5, client=client)

    def test_crypto_empty_prices_raises(self) -> None:
        client = httpx.Client(transport=_mock_transport({"prices": []}))
        with pytest.raises(MarketDataUnavailableError, match="BTC-USD"):
            get_price_history("BTC-USD", days=5, client=client)

    def test_crypto_retries_a_transient_429(self) -> None:
        transport, calls = _sequenced_transport(
            [(429, {}), (200, {"prices": [[1785715200000, 65000.0]]})]
        )
        client = httpx.Client(transport=transport)

        with patch("streaming.market_feed.time.sleep") as mock_sleep:
            result = get_price_history("BTC-USD", days=5, client=client)

        assert [p.price for p in result] == [65000.0]
        assert calls.call_count == 2
        mock_sleep.assert_called_once()


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
