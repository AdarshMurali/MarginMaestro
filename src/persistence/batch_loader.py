import argparse
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config.settings import get_settings
from persistence.db.bootstrap import ensure_database_exists
from persistence.db.engine import get_session_factory
from persistence.db.models import (
    AuditLogORM,
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    RatingORM,
    ReferenceRateORM,
)
from persistence.fred_feed import REFERENCE_SERIES, FredFeed
from persistence.generators.collateral_calibration import calibrate_collateral_to_exposure
from persistence.generators.run import DEFAULT_SEED, generate_all
from persistence.generators.securities import securities_universe
from streaming.market_feed import MarketDataUnavailableError, MarketFeed, get_market_feed
from streaming.market_feed import get_price_history as fetch_ticker_price_history


def load_synthetic_reference_data(session: Session, seed: int, as_of: date) -> dict[str, int]:
    data = generate_all(seed, as_of)

    for counterparty in data["counterparties"]:
        session.merge(CounterpartyORM(**counterparty.model_dump()))
    for portfolio in data["portfolios"]:
        session.merge(PortfolioORM(**portfolio.model_dump()))
    for position in data["positions"]:
        session.merge(PositionORM(**position.model_dump()))
    for rating in data["ratings"]:
        session.merge(RatingORM(**rating.model_dump()))
    for collateral in data["collateral"]:
        session.merge(CollateralItemORM(**collateral.model_dump()))

    return {name: len(records) for name, records in data.items()}


def load_prices(session: Session, feed: MarketFeed, tickers: list[str], as_of: date) -> int:
    quotes = feed.get_prices(tickers)
    for quote in quotes.values():
        session.merge(
            PriceHistoryORM(
                ticker=quote.ticker,
                price_date=as_of,
                price=quote.price,
                currency=quote.currency,
                source=quote.source,
            )
        )
    return len(quotes)


def backfill_price_history(
    session: Session, tickers: list[str], days: int = 30, min_existing_rows: int = 5
) -> int:
    """One-time-per-ticker deep-history seed (MM-59), so the price chart
    isn't near-empty right after switching it to read SQL only. Skips any
    ticker that already has >= min_existing_rows rows, so this is a cheap
    no-op on every batch-load run after the first real one -- auto-wired
    into run_batch_load rather than a separate manual step, since a
    "remember to run this once" step is exactly the kind of thing that gets
    skipped, leaving the chart visibly sparse indefinitely. Still only ever
    called from this batch/CLI context, never per-request."""
    inserted = 0
    for ticker in tickers:
        existing = session.execute(
            select(func.count())
            .select_from(PriceHistoryORM)
            .where(PriceHistoryORM.ticker == ticker)
        ).scalar_one()
        if existing >= min_existing_rows:
            continue
        try:
            points = fetch_ticker_price_history(ticker, days=days)
        except MarketDataUnavailableError:
            continue
        for point in points:
            session.merge(
                PriceHistoryORM(
                    ticker=ticker,
                    price_date=point.date,
                    price=point.price,
                    currency="USD",
                    source="yfinance-backfill",
                )
            )
            inserted += 1
    return inserted


def load_reference_rates(session: Session, feed: FredFeed, as_of: date) -> int:
    count = 0
    for series_id in REFERENCE_SERIES:
        observation = feed.get_latest(series_id)
        session.merge(
            ReferenceRateORM(
                series_id=series_id,
                rate_date=as_of,
                value=observation.value,
            )
        )
        count += 1
    return count


def run_batch_load(seed: int = DEFAULT_SEED, as_of: date | None = None) -> dict[str, Any]:
    settings = get_settings()
    as_of = as_of or datetime.now(UTC).date()

    # Only local dev's own fresh Azure SQL Edge container needs its database
    # created -- deployed envs reuse an already-existing database via a
    # contained DB user with no `master` access at all (see migrations/env.py
    # for the same guard and the real failure this was found from).
    if settings.app_env == "local":
        ensure_database_exists(settings)
    session_factory = get_session_factory(settings)

    market_feed = get_market_feed(settings)
    fred_feed = FredFeed(settings)

    with session_factory() as session:
        synthetic_counts = load_synthetic_reference_data(session, seed, as_of)
        price_count = load_prices(session, market_feed, securities_universe(), as_of)
        rate_count = load_reference_rates(session, fred_feed, as_of)
        backfill_count = backfill_price_history(session, securities_universe())
        # MM-77: must run after prices/reference rates above -- needs real
        # current+prior prices and VIX already in the DB to compute each
        # counterparty's actual exposure and calibrate collateral to it.
        calibrated_collateral = calibrate_collateral_to_exposure(session, seed, as_of)

        summary = {
            **synthetic_counts,
            "prices": price_count,
            "reference_rates": rate_count,
            "price_history_backfill": backfill_count,
            "collateral_calibrated": len(calibrated_collateral),
        }
        session.add(
            AuditLogORM(
                correlation_id=str(uuid4()),
                event_type="batch_load",
                payload=summary,
                created_at=datetime.now(UTC),
            )
        )
        session.commit()

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh MarginMaestro's local DB")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    summary = run_batch_load(seed=args.seed)
    print(summary)


if __name__ == "__main__":
    main()
