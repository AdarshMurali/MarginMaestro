"""Fixed-interval live feed poller (MM-59): publishes onto market.prices on
a timer via the existing publish_live_prices (MM-32/live_feed_publisher.py),
so the Event Agent's unconditional latest-price upsert always has something
fresh to consume. Deliberately no volatility-threshold logic here -- a flat
interval is simpler and this is a ~30-ticker curated universe, not a firehose
that needs gatekeeping before it reaches Kafka. Run via `make live-feed-poller`."""

import itertools
import time

import structlog

from config.settings import Settings, get_settings
from streaming.live_feed_publisher import publish_live_prices

logger = structlog.get_logger()


def run(
    interval_seconds: int | None = None,
    tickers: list[str] | None = None,
    settings: Settings | None = None,
    max_iterations: int | None = None,
) -> None:
    """`max_iterations` exists purely for tests (bounds the loop so it can
    run against a mocked `time.sleep`); production callers leave it None for
    an indefinite loop."""
    settings = settings or get_settings()
    interval = (
        interval_seconds
        if interval_seconds is not None
        else settings.live_feed_poll_interval_seconds
    )
    tickers = tickers if tickers is not None else settings.market_universe_list

    iterations = range(max_iterations) if max_iterations is not None else itertools.count()
    for _ in iterations:
        try:
            count = publish_live_prices(tickers, settings=settings)
            logger.info("live_feed_poll_published", count=count)
        except Exception:
            # A poll iteration has no offset/redelivery semantics (unlike
            # event_agent's consumer, where an exception must propagate to
            # avoid committing an offset for an unprocessed message) -- a
            # transient yfinance hiccup should log and retry next interval,
            # not take the whole poller down.
            logger.exception("live_feed_poll_failed")
        time.sleep(interval)


if __name__ == "__main__":
    run()
