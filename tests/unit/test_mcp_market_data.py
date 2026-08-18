from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest

from mcp_servers.market_data import get_current_prices, get_historical_prices
from streaming.market_feed import MarketDataUnavailableError, PriceHistoryPoint, PriceQuote


class TestGetCurrentPricesTool:
    def test_forwards_tickers_and_serializes_results(self) -> None:
        quotes = {
            "AAPL": PriceQuote(
                ticker="AAPL", price=210.5, as_of=datetime.now(UTC), source="yfinance"
            ),
            "BTC-USD": PriceQuote(
                ticker="BTC-USD", price=65000.0, as_of=datetime.now(UTC), source="coingecko"
            ),
        }
        feed = MagicMock()
        feed.get_prices.return_value = quotes

        with patch("mcp_servers.market_data.get_market_feed", return_value=feed):
            result = get_current_prices(["AAPL", "BTC-USD"])

        feed.get_prices.assert_called_once_with(["AAPL", "BTC-USD"])
        assert result == [q.model_dump() for q in quotes.values()]

    def test_market_data_unavailable_error_propagates_not_swallowed(self) -> None:
        feed = MagicMock()
        feed.get_prices.side_effect = MarketDataUnavailableError(
            "yfinance could not price: BADTICKER"
        )

        with (
            patch("mcp_servers.market_data.get_market_feed", return_value=feed),
            pytest.raises(MarketDataUnavailableError, match="BADTICKER"),
        ):
            get_current_prices(["BADTICKER"])


class TestGetHistoricalPricesTool:
    def test_forwards_ticker_and_days_and_serializes_results(self) -> None:
        points = [
            PriceHistoryPoint(date=date(2026, 7, 30), price=100.0),
            PriceHistoryPoint(date=date(2026, 7, 31), price=101.5),
        ]

        with patch(
            "mcp_servers.market_data.get_price_history", return_value=points
        ) as mock_history:
            result = get_historical_prices("AAPL", days=5)

        mock_history.assert_called_once_with("AAPL", days=5)
        assert result == [p.model_dump() for p in points]

    def test_default_days_is_thirty(self) -> None:
        with patch("mcp_servers.market_data.get_price_history", return_value=[]) as mock_history:
            get_historical_prices("AAPL")

        mock_history.assert_called_once_with("AAPL", days=30)

    def test_market_data_unavailable_error_propagates_not_swallowed(self) -> None:
        with (
            patch(
                "mcp_servers.market_data.get_price_history",
                side_effect=MarketDataUnavailableError("No price history available for AAPL"),
            ),
            pytest.raises(MarketDataUnavailableError, match="AAPL"),
        ):
            get_historical_prices("AAPL")
