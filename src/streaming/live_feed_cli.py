import argparse

from config.settings import get_settings
from streaming.live_feed_publisher import publish_live_prices


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish real (or, per MARKET_FEED_MODE, simulated) prices onto market.prices."
    )
    parser.add_argument(
        "--tickers",
        help="Comma-separated tickers (defaults to the curated MARKET_UNIVERSE).",
    )
    args = parser.parse_args()
    tickers = (
        [t.strip() for t in args.tickers.split(",")]
        if args.tickers
        else get_settings().market_universe_list
    )
    count = publish_live_prices(tickers)
    print(f"published {count} price tick(s)")


if __name__ == "__main__":
    main()
