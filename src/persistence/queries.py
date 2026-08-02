"""Read-only query helpers shared across API/agent consumers. Deliberately
NOT a refactor of agents/orchestrator.py's own (near-identical, private)
_load_positions/_collateral_held/_latest_vix -- those are already tested and
shipped as part of the orchestrator's run-a-single-counterparty flow, and
this module's actual new need (list every counterparty for a board) has a
different shape (list_counterparties). Moving the orchestrator's helpers
here too would touch a large, already-verified test file for no behavior
change; if a third consumer needs this exact logic, consolidate then."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from calc.models import PricingError
from persistence.db.models import (
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    ReferenceRateORM,
)
from persistence.models import AssetClass, Counterparty, CounterpartyType, Position


def list_counterparties(session: Session) -> list[Counterparty]:
    rows = session.execute(select(CounterpartyORM)).scalars().all()
    return [
        Counterparty(id=row.id, name=row.name, type=CounterpartyType(row.type), country=row.country)
        for row in rows
    ]


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
