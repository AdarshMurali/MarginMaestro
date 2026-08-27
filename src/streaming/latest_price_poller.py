"""Fixed-interval direct poller for `latest_prices` (MM-102 real-deployment
follow-up): writes straight to the DB via the same `upsert_latest_price` the
Event Agent's Kafka consumer uses, skipping Kafka/Redpanda entirely.

live_feed_poller.py (MM-59) is the Kafka-based equivalent -- it publishes
onto market.prices and relies on the Event Agent consumer to do the actual
upsert. Phase 10's deploy scope deliberately keeps Kafka/Redpanda and the
Event Agent consumer local-only (see docs/ROADMAP.md), which left the
deployed instance's `latest_prices` table permanently empty and /exposure's
board reporting every counterparty "unavailable" -- found live by the user
after MM-103. This poller exists purely to keep that one table fresh in a
Kafka-free deployment; it has no threshold/classification logic and never
triggers a margin-call run (that's still exclusively /simulate's job)."""

import itertools
import time

import structlog

from config.settings import Settings, get_settings
from persistence.db.engine import get_session_factory
from streaming.event_agent import upsert_latest_price
from streaming.market_feed import get_market_feed

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
    feed = get_market_feed(settings)
    session_factory = get_session_factory(settings)

    iterations = range(max_iterations) if max_iterations is not None else itertools.count()
    for _ in iterations:
        try:
            quotes = feed.get_prices(tickers)
            with session_factory() as session:
                for quote in quotes.values():
                    upsert_latest_price(session, quote)
            logger.info("latest_price_poll_published", count=len(quotes))
        except Exception:
            # Same rationale as live_feed_poller.py: a transient yfinance/DB
            # hiccup should log and retry next interval, not take the whole
            # poller down.
            logger.exception("latest_price_poll_failed")
        time.sleep(interval)


if __name__ == "__main__":
    run()
