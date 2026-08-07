from unittest.mock import patch

from config.settings import Settings
from streaming.live_feed_poller import run


class TestRun:
    def test_calls_publish_once_per_iteration(self) -> None:
        with (
            patch("streaming.live_feed_poller.time.sleep") as mock_sleep,
            patch("streaming.live_feed_poller.publish_live_prices", return_value=3) as mock_publish,
        ):
            run(interval_seconds=1, tickers=["AAPL"], max_iterations=3)

        assert mock_publish.call_count == 3
        assert mock_sleep.call_count == 3

    def test_a_failed_iteration_does_not_stop_the_loop(self) -> None:
        with (
            patch("streaming.live_feed_poller.time.sleep"),
            patch(
                "streaming.live_feed_poller.publish_live_prices",
                side_effect=[Exception("boom"), 4, 4],
            ) as mock_publish,
        ):
            run(interval_seconds=1, tickers=["AAPL"], max_iterations=3)

        assert mock_publish.call_count == 3

    def test_defaults_come_from_settings_when_not_passed_explicitly(self) -> None:
        settings = Settings(_env_file=None, live_feed_poll_interval_seconds=45)
        with (
            patch("streaming.live_feed_poller.time.sleep") as mock_sleep,
            patch("streaming.live_feed_poller.publish_live_prices", return_value=0) as mock_publish,
        ):
            run(settings=settings, max_iterations=1)

        mock_publish.assert_called_once_with(settings.market_universe_list, settings=settings)
        mock_sleep.assert_called_once_with(45)
