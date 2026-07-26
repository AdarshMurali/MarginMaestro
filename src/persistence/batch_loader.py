import argparse
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

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
from persistence.generators.run import DEFAULT_SEED, generate_all
from persistence.generators.securities import securities_universe
from streaming.market_feed import MarketFeed, get_market_feed


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

    ensure_database_exists(settings)
    session_factory = get_session_factory(settings)

    market_feed = get_market_feed(settings)
    fred_feed = FredFeed(settings)

    with session_factory() as session:
        synthetic_counts = load_synthetic_reference_data(session, seed, as_of)
        price_count = load_prices(session, market_feed, securities_universe(), as_of)
        rate_count = load_reference_rates(session, fred_feed, as_of)

        summary = {**synthetic_counts, "prices": price_count, "reference_rates": rate_count}
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
