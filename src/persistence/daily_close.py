"""Daily end-of-day load (MM-124): appends each ticker's official daily
closes to `price_history` and refreshes the FRED reference rates (VIX for
initial margin, the rate curve). Scheduled by Cloud Scheduler after the US
close; `POST /internal/prices/eod` runs it.

`price_history` is what the Event Agent's shock check compares against
("moved >= 7% vs the previous close") and what initial-margin volatility and
the price charts read. Before this job it was only loaded once, at
bootstrap, so it went stale day by day. `latest_prices` (the 5-minute ticks)
can't replace it: it keeps only the current price per ticker.

Fetches a short window, not just today, so days the app was offline
(demo_online = false) are back-filled on the next run. Idempotent: rows are
keyed by (ticker, date) and merged.
"""

import structlog
from sqlalchemy.orm import Session

from config.settings import Settings
from persistence.db.models import PriceHistoryORM
from persistence.fred_feed import FredFeed, RateDataUnavailableError
from streaming.market_feed import MarketDataUnavailableError, get_price_history

logger = structlog.get_logger()

EOD_WINDOW_DAYS = 7
EOD_SOURCE = "eod"


def load_daily_closes(
    session: Session, tickers: list[str], days: int = EOD_WINDOW_DAYS
) -> dict[str, list[str]]:
    """Merges the last `days` of daily closes per ticker. A ticker the feed
    can't price is reported, not fatal -- one bad symbol shouldn't stop the
    rest of the book's history from updating."""
    loaded, failed = [], []
    for ticker in tickers:
        try:
            points = get_price_history(ticker, days=days)
        except MarketDataUnavailableError as exc:
            logger.warning("eod_close_unavailable", ticker=ticker, error=str(exc))
            failed.append(ticker)
            continue
        for point in points:
            session.merge(
                PriceHistoryORM(
                    ticker=ticker,
                    price_date=point.date,
                    price=point.price,
                    currency="USD",
                    source=EOD_SOURCE,
                )
            )
        loaded.append(ticker)
    session.commit()
    return {"loaded": loaded, "failed": failed}


def refresh_reference_rates(session: Session, settings: Settings) -> int:
    """FRED rates (VIXCLS etc.). Needs FRED_API_KEY; without it this is
    skipped with a warning rather than failing the price load."""
    from persistence.batch_loader import load_reference_rates

    try:
        feed = FredFeed(settings)
    except RateDataUnavailableError as exc:
        logger.warning("eod_reference_rates_skipped", error=str(exc))
        return 0
    from datetime import UTC, datetime

    count = load_reference_rates(session, feed, datetime.now(UTC).date())
    session.commit()
    return count
