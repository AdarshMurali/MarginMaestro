"""Read-only query helpers shared across API/agent consumers. Deliberately
NOT a refactor of agents/orchestrator.py's own (near-identical, private)
_load_positions/_collateral_held/_latest_vix -- those are already tested and
shipped as part of the orchestrator's run-a-single-counterparty flow, and
this module's actual new need (list every counterparty for a board) has a
different shape (list_counterparties). Moving the orchestrator's helpers
here too would touch a large, already-verified test file for no behavior
change; if a third consumer needs this exact logic, consolidate then."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from calc.models import PricingError
from persistence.db.models import (
    CollateralItemORM,
    CounterpartyORM,
    LatestPriceORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    ReferenceRateORM,
)
from persistence.models import (
    AssetClass,
    Counterparty,
    CounterpartyType,
    LatestPrice,
    Position,
    PriceHistoryEntry,
)


def list_counterparties(session: Session) -> list[Counterparty]:
    rows = session.execute(select(CounterpartyORM)).scalars().all()
    return [
        Counterparty(id=row.id, name=row.name, type=CounterpartyType(row.type), country=row.country)
        for row in rows
    ]


def get_counterparty(session: Session, counterparty_id: str) -> Counterparty | None:
    """Single-counterparty lookup by primary key (MM-61) -- for the
    per-counterparty detail endpoint, so it doesn't need list_counterparties'
    full-table scan just to find one row."""
    row = session.get(CounterpartyORM, counterparty_id)
    if row is None:
        return None
    return Counterparty(
        id=row.id, name=row.name, type=CounterpartyType(row.type), country=row.country
    )


def load_positions(session: Session, counterparty_id: str) -> list[Position]:
    """Relies on the data model's one-portfolio-per-counterparty invariant
    (Phase 1/MM-11) -- compute_mtm() requires every position to share one
    portfolio_id."""
    rows = (
        session.execute(
            select(PositionORM)
            .join(PortfolioORM, PositionORM.portfolio_id == PortfolioORM.id)
            .where(PortfolioORM.counterparty_id == counterparty_id)
        )
        .scalars()
        .all()
    )
    return [
        Position(
            id=row.id,
            portfolio_id=row.portfolio_id,
            ticker=row.ticker,
            asset_class=AssetClass(row.asset_class),
            quantity=row.quantity,
            trade_date=row.trade_date,
        )
        for row in rows
    ]


def collateral_held(session: Session, counterparty_id: str) -> float:
    rows = session.execute(
        select(CollateralItemORM.value_usd, CollateralItemORM.haircut_pct).where(
            CollateralItemORM.counterparty_id == counterparty_id
        )
    ).all()
    return sum(value_usd * (1 - haircut_pct) for value_usd, haircut_pct in rows)


def load_positions_for_counterparties(
    session: Session, counterparty_ids: list[str]
) -> dict[str, list[Position]]:
    """Batched sibling of load_positions (MM-66) -- one query for every
    requested counterparty's positions, instead of one round trip per
    counterparty. Used by build_exposure_board's whole-board path; the
    per-counterparty detail path (get_counterparty_exposure, MM-61) keeps
    using load_positions, since fetching one counterparty was never the N+1
    problem."""
    if not counterparty_ids:
        return {}
    rows = session.execute(
        select(PortfolioORM.counterparty_id, PositionORM)
        .join(PortfolioORM, PositionORM.portfolio_id == PortfolioORM.id)
        .where(PortfolioORM.counterparty_id.in_(counterparty_ids))
    ).all()
    result: dict[str, list[Position]] = {}
    for counterparty_id, row in rows:
        result.setdefault(counterparty_id, []).append(
            Position(
                id=row.id,
                portfolio_id=row.portfolio_id,
                ticker=row.ticker,
                asset_class=AssetClass(row.asset_class),
                quantity=row.quantity,
                trade_date=row.trade_date,
            )
        )
    return result


def collateral_held_for_counterparties(
    session: Session, counterparty_ids: list[str]
) -> dict[str, float]:
    """Batched sibling of collateral_held (MM-66) -- one query for every
    requested counterparty's collateral, instead of one round trip per
    counterparty. Counterparties with no collateral rows still get a 0.0
    entry so callers can index without a fallback."""
    result: dict[str, float] = {cp_id: 0.0 for cp_id in counterparty_ids}
    if not counterparty_ids:
        return result
    rows = session.execute(
        select(
            CollateralItemORM.counterparty_id,
            CollateralItemORM.value_usd,
            CollateralItemORM.haircut_pct,
        ).where(CollateralItemORM.counterparty_id.in_(counterparty_ids))
    ).all()
    for counterparty_id, value_usd, haircut_pct in rows:
        result[counterparty_id] += value_usd * (1 - haircut_pct)
    return result


def latest_vix(session: Session) -> float:
    value = session.execute(
        select(ReferenceRateORM.value)
        .where(ReferenceRateORM.series_id == "VIXCLS")
        .order_by(ReferenceRateORM.rate_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if value is None:
        raise PricingError("No VIXCLS reference rate available to compute Initial Margin")
    return value


def latest_prices(session: Session, tickers: list[str]) -> dict[str, LatestPrice]:
    """Read-only source for /exposure's current-price lookup (MM-59) -- the
    rows here come from the live-feed poller's ticks via the Event Agent's
    unconditional upsert, never from a request-time yfinance call."""
    if not tickers:
        return {}
    rows = (
        session.execute(select(LatestPriceORM).where(LatestPriceORM.ticker.in_(tickers)))
        .scalars()
        .all()
    )
    return {
        row.ticker: LatestPrice(
            ticker=row.ticker,
            price=row.price,
            currency=row.currency,
            source=row.source,
            as_of=row.as_of,
        )
        for row in rows
    }


def latest_closes_before(
    session: Session, tickers: list[str], before: datetime
) -> dict[str, float]:
    """Batched sibling of streaming.event_agent.latest_close_before (MM-60)
    -- one query for every requested ticker's most recent close strictly
    before `before`, instead of one round trip per ticker. Used by
    /exposure's board-building path, which was doing this per ticker per
    counterparty (~10 round trips x ~11 counterparties). event_agent's own
    per-tick classification stays on the single-ticker function -- that's a
    different, inherently single-ticker context (one Kafka message), not
    something to batch."""
    if not tickers:
        return {}
    cutoff = before.date()
    latest_date_per_ticker = (
        select(PriceHistoryORM.ticker, func.max(PriceHistoryORM.price_date).label("max_date"))
        .where(PriceHistoryORM.ticker.in_(tickers), PriceHistoryORM.price_date < cutoff)
        .group_by(PriceHistoryORM.ticker)
        .subquery()
    )
    rows = session.execute(
        select(PriceHistoryORM.ticker, PriceHistoryORM.price).join(
            latest_date_per_ticker,
            (PriceHistoryORM.ticker == latest_date_per_ticker.c.ticker)
            & (PriceHistoryORM.price_date == latest_date_per_ticker.c.max_date),
        )
    ).all()
    return {ticker: price for ticker, price in rows}


def price_history(session: Session, ticker: str, days: int = 30) -> list[PriceHistoryEntry]:
    """Read-only source for the price chart (MM-59) -- reads the EOD series
    batch-loaded/backfilled into price_history, never a request-time
    yfinance call."""
    cutoff = datetime.now(UTC).date() - timedelta(days=days)
    rows = session.execute(
        select(PriceHistoryORM.price_date, PriceHistoryORM.price)
        .where(PriceHistoryORM.ticker == ticker, PriceHistoryORM.price_date >= cutoff)
        .order_by(PriceHistoryORM.price_date.asc())
    ).all()
    return [PriceHistoryEntry(date=price_date, price=price) for price_date, price in rows]
