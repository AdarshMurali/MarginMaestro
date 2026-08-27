from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from config.settings import Settings
from streaming.latest_price_poller import run
from streaming.market_feed import PriceQuote


def _quote(ticker: str) -> PriceQuote:
    return PriceQuote(ticker=ticker, price=100.0, as_of=datetime.now(UTC), source="test")


class TestRun:
    def test_upserts_one_price_per_quote_per_iteration(self) -> None:
        session = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = session
        session_context.__exit__.return_value = None
        session_factory = MagicMock(return_value=session_context)

        feed = MagicMock()
        feed.get_prices.return_value = {"AAPL": _quote("AAPL"), "MSFT": _quote("MSFT")}

        with (
            patch("streaming.latest_price_poller.time.sleep") as mock_sleep,
            patch("streaming.latest_price_poller.get_market_feed", return_value=feed),
            patch(
                "streaming.latest_price_poller.get_session_factory", return_value=session_factory
            ),
            patch("streaming.latest_price_poller.upsert_latest_price") as mock_upsert,
        ):
            run(interval_seconds=1, tickers=["AAPL", "MSFT"], max_iterations=2)

        assert mock_upsert.call_count == 4  # 2 quotes x 2 iterations
        assert mock_sleep.call_count == 2

    def test_a_failed_iteration_does_not_stop_the_loop(self) -> None:
        feed = MagicMock()
        feed.get_prices.side_effect = [Exception("boom"), {"AAPL": _quote("AAPL")}, {}]

        with (
            patch("streaming.latest_price_poller.time.sleep"),
            patch("streaming.latest_price_poller.get_market_feed", return_value=feed),
            patch("streaming.latest_price_poller.get_session_factory"),
            patch("streaming.latest_price_poller.upsert_latest_price"),
        ):
            run(interval_seconds=1, tickers=["AAPL"], max_iterations=3)

        assert feed.get_prices.call_count == 3

    def test_defaults_come_from_settings_when_not_passed_explicitly(self) -> None:
        settings = Settings(_env_file=None, live_feed_poll_interval_seconds=45)
        feed = MagicMock()
        feed.get_prices.return_value = {}

        with (
            patch("streaming.latest_price_poller.time.sleep") as mock_sleep,
            patch("streaming.latest_price_poller.get_market_feed", return_value=feed) as mock_feed,
            patch("streaming.latest_price_poller.get_session_factory"),
        ):
            run(settings=settings, max_iterations=1)

        mock_feed.assert_called_once_with(settings)
        feed.get_prices.assert_called_once_with(settings.market_universe_list)
        mock_sleep.assert_called_once_with(45)
