from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from calc.models import PricingError
from persistence.db.models import (
    Base,
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    ReferenceRateORM,
)
from persistence.queries import collateral_held, latest_vix, list_counterparties, load_positions


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


class TestListCounterparties:
    def test_returns_every_counterparty(self, session_factory) -> None:
        with session_factory() as session:
            session.add(CounterpartyORM(id="CP-1", name="Alpha", type="Bank", country="US"))
            session.add(CounterpartyORM(id="CP-2", name="Beta", type="Hedge Fund", country="UK"))
            session.commit()

        with session_factory() as session:
            result = list_counterparties(session)

        assert {cp.id for cp in result} == {"CP-1", "CP-2"}
        assert {cp.name for cp in result} == {"Alpha", "Beta"}

    def test_empty_when_no_counterparties(self, session_factory) -> None:
        with session_factory() as session:
            assert list_counterparties(session) == []


class TestLoadPositions:
    def test_returns_positions_for_the_counterparty(self, session_factory) -> None:
        with session_factory() as session:
            session.add(CounterpartyORM(id="CP-1", name="CP-1", type="Bank", country="US"))
            session.add(PortfolioORM(id="PF-1", counterparty_id="CP-1", currency="USD"))
            session.add(
                PositionORM(
                    id="POS-1",
                    portfolio_id="PF-1",
                    ticker="AAPL",
                    asset_class="equity",
                    quantity=10,
                    trade_date=date(2026, 1, 1),
                )
            )
            session.commit()

        with session_factory() as session:
            result = load_positions(session, "CP-1")

        assert len(result) == 1
        assert result[0].ticker == "AAPL"

    def test_empty_for_unknown_counterparty(self, session_factory) -> None:
        with session_factory() as session:
            assert load_positions(session, "CP-404") == []


class TestCollateralHeld:
    def test_sums_haircut_adjusted_value(self, session_factory) -> None:
        with session_factory() as session:
            session.add(CounterpartyORM(id="CP-1", name="CP-1", type="Bank", country="US"))
            session.add(
                CollateralItemORM(
                    id="COLL-1",
                    counterparty_id="CP-1",
                    collateral_type="cash",
                    value_usd=100_000.0,
                    haircut_pct=0.0,
                )
            )
            session.add(
                CollateralItemORM(
                    id="COLL-2",
                    counterparty_id="CP-1",
                    collateral_type="security",
                    value_usd=50_000.0,
                    haircut_pct=0.1,
                )
            )
            session.commit()

        with session_factory() as session:
            assert collateral_held(session, "CP-1") == 100_000.0 + 45_000.0

    def test_zero_when_no_collateral(self, session_factory) -> None:
        with session_factory() as session:
            assert collateral_held(session, "CP-1") == 0.0


class TestLatestVix:
    def test_returns_most_recent_value(self, session_factory) -> None:
        with session_factory() as session:
            session.add(
                ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 1, 1), value=18.0)
            )
            session.add(
                ReferenceRateORM(series_id="VIXCLS", rate_date=date(2026, 1, 3), value=22.0)
            )
            session.commit()

        with session_factory() as session:
            assert latest_vix(session) == 22.0

    def test_raises_when_no_vix_data(self, session_factory) -> None:
        with session_factory() as session, pytest.raises(PricingError, match="VIXCLS"):
            latest_vix(session)
