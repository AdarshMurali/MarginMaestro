from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from persistence.db.models import (
    Base,
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    PriceHistoryORM,
    ReferenceRateORM,
)
from persistence.generators.collateral_calibration import (
    MAX_FACTOR,
    MIN_COLLATERAL_USD,
    MIN_FACTOR,
    calibrate_collateral_to_exposure,
)

AS_OF = date(2026, 8, 22)
PRIOR = date(2026, 8, 21)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed_counterparty(
    session: Session, cp_id: str, ticker: str, quantity: float, prior_price: float, price: float
) -> None:
    session.add(CounterpartyORM(id=cp_id, name=cp_id, type="Bank", country="US"))
    portfolio_id = f"PF-{cp_id}"
    session.add(PortfolioORM(id=portfolio_id, counterparty_id=cp_id, currency="USD"))
    session.add(
        PositionORM(
            id=f"POS-{cp_id}",
            portfolio_id=portfolio_id,
            ticker=ticker,
            asset_class="equity",
            quantity=quantity,
            trade_date=date(2026, 1, 1),
        )
    )
    session.add(
        PriceHistoryORM(
            ticker=ticker, price_date=PRIOR, price=prior_price, currency="USD", source="yfinance"
        )
    )
    session.add(
        PriceHistoryORM(
            ticker=ticker, price_date=AS_OF, price=price, currency="USD", source="yfinance"
        )
    )
    session.add(
        CollateralItemORM(
            id=f"COL-{cp_id}",
            counterparty_id=cp_id,
            collateral_type="cash",
            value_usd=1_000_000.0,
            haircut_pct=0.0,
        )
    )
    session.commit()


def _seed_vix(session: Session, value: float = 20.0) -> None:
    session.add(ReferenceRateORM(series_id="VIXCLS", rate_date=AS_OF, value=value))
    session.commit()


class TestCalibrateCollateralToExposure:
    def test_replaces_collateral_within_the_configured_factor_range(self, session_factory) -> None:
        with session_factory() as session:
            # Large enough that 40-70% of exposure clears MIN_COLLATERAL_USD
            # -- a small toy example would just get floored, masking this
            # assertion (see test_floors_negative_exposure_at_the_minimum
            # for that case instead).
            _seed_counterparty(
                session, "CP-1", "XYZ", quantity=1000, prior_price=100.0, price=134.0
            )
            _seed_vix(session)

            results = calibrate_collateral_to_exposure(session, seed=42, as_of=AS_OF)

            # mtm_today=134,000, mtm_prior=100,000 -> VM=34,000, IM=134,000*0.15=20,100
            expected_exposure = 54_100.0
            assert "CP-1" in results
            assert (
                MIN_FACTOR * expected_exposure <= results["CP-1"] <= MAX_FACTOR * expected_exposure
            )

            rows = (
                session.execute(
                    select(CollateralItemORM).where(CollateralItemORM.counterparty_id == "CP-1")
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1  # old $1,000,000 row replaced, not accumulated
            assert rows[0].value_usd == pytest.approx(results["CP-1"])
            assert rows[0].haircut_pct == 0.0

    def test_is_deterministic_for_the_same_seed(self) -> None:
        # Two fully independent in-memory DBs -- the shared session_factory
        # fixture holds one DB for its whole lifetime (StaticPool), so
        # reusing it for two "runs" here would collide on primary keys.
        def _fresh_session_factory() -> sessionmaker[Session]:
            engine = create_engine(
                "sqlite:///:memory:",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
            Base.metadata.create_all(engine)
            return sessionmaker(bind=engine)

        with _fresh_session_factory()() as session:
            _seed_counterparty(session, "CP-1", "XYZ", quantity=10, prior_price=10.0, price=34.0)
            _seed_vix(session)
            first = calibrate_collateral_to_exposure(session, seed=42, as_of=AS_OF)

        with _fresh_session_factory()() as session:
            _seed_counterparty(session, "CP-1", "XYZ", quantity=10, prior_price=10.0, price=34.0)
            _seed_vix(session)
            second = calibrate_collateral_to_exposure(session, seed=42, as_of=AS_OF)

        assert first == second

    def test_leaves_a_counterparty_untouched_when_prior_price_is_missing(
        self, session_factory
    ) -> None:
        with session_factory() as session:
            session.add(CounterpartyORM(id="CP-1", name="CP-1", type="Bank", country="US"))
            session.add(PortfolioORM(id="PF-CP-1", counterparty_id="CP-1", currency="USD"))
            session.add(
                PositionORM(
                    id="POS-CP-1",
                    portfolio_id="PF-CP-1",
                    ticker="XYZ",
                    asset_class="equity",
                    quantity=10,
                    trade_date=date(2026, 1, 1),
                )
            )
            # Only today's price -- no prior close on record.
            session.add(
                PriceHistoryORM(
                    ticker="XYZ", price_date=AS_OF, price=34.0, currency="USD", source="yfinance"
                )
            )
            session.add(
                CollateralItemORM(
                    id="COL-CP-1",
                    counterparty_id="CP-1",
                    collateral_type="cash",
                    value_usd=1_000_000.0,
                    haircut_pct=0.0,
                )
            )
            session.commit()
            _seed_vix(session)

            results = calibrate_collateral_to_exposure(session, seed=42, as_of=AS_OF)

            assert "CP-1" not in results
            row = session.get(CollateralItemORM, "COL-CP-1")
            assert row is not None
            assert row.value_usd == 1_000_000.0  # untouched

    def test_floors_negative_exposure_at_the_minimum(self, session_factory) -> None:
        with session_factory() as session:
            # Short position, price rises -- confirmed pattern: exposure goes
            # negative (VM negative, IM small) for a short + price-up move.
            _seed_counterparty(session, "CP-1", "XYZ", quantity=-10, prior_price=10.0, price=34.0)
            _seed_vix(session)

            results = calibrate_collateral_to_exposure(session, seed=42, as_of=AS_OF)

            assert results["CP-1"] == MIN_COLLATERAL_USD

    def test_no_vix_returns_empty_and_touches_nothing(self, session_factory) -> None:
        with session_factory() as session:
            _seed_counterparty(session, "CP-1", "XYZ", quantity=10, prior_price=10.0, price=34.0)
            # No ReferenceRateORM row seeded at all.

            results = calibrate_collateral_to_exposure(session, seed=42, as_of=AS_OF)

            assert results == {}
            row = session.get(CollateralItemORM, "COL-CP-1")
            assert row is not None
            assert row.value_usd == 1_000_000.0

    def test_no_positions_leaves_counterparty_out_of_results(self, session_factory) -> None:
        with session_factory() as session:
            session.add(CounterpartyORM(id="CP-1", name="CP-1", type="Bank", country="US"))
            session.commit()
            _seed_vix(session)

            results = calibrate_collateral_to_exposure(session, seed=42, as_of=AS_OF)

            assert results == {}
