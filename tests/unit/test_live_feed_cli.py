from unittest.mock import patch

from streaming.live_feed_cli import main


def test_uses_explicit_tickers_when_given() -> None:
    with (
        patch("streaming.live_feed_cli.publish_live_prices", return_value=2) as mock_publish,
        patch("sys.argv", ["live_feed_cli", "--tickers", "AAPL, TSLA"]),
    ):
        main()

    mock_publish.assert_called_once_with(["AAPL", "TSLA"])


def test_defaults_to_curated_market_universe_when_no_tickers_given() -> None:
    with (
        patch("streaming.live_feed_cli.publish_live_prices", return_value=0) as mock_publish,
        patch("sys.argv", ["live_feed_cli"]),
    ):
        main()

    published_tickers = mock_publish.call_args.args[0]
    assert "AAPL" in published_tickers
    assert len(published_tickers) > 10
