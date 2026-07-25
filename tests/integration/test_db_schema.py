"""Live-DB schema/cascade tests. Skipped automatically if no database is
reachable (e.g. CI, which has no SQL Server or ODBC driver available) --
run these locally with `docker compose up -d sqlserver` first.
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.exc import DBAPIError

from config.settings import get_settings
from persistence.db.bootstrap import ensure_database_exists
from persistence.db.engine import get_engine, get_session_factory
from persistence.db.models import (
    AuditLogORM,
    Base,
    CollateralItemORM,
    CounterpartyORM,
    PortfolioORM,
    PositionORM,
    RatingORM,
    TicketORM,
)


@pytest.fixture(scope="module")
def db_session_factory():
    settings = get_settings()
    try:
        ensure_database_exists(settings)
        engine = get_engine(settings)
        Base.metadata.create_all(engine)
        engine.dispose()
    except DBAPIError as exc:
        pytest.skip(f"No reachable database for integration tests: {exc}")
    yield get_session_factory(settings)


def test_insert_readback_relationships_and_cascade_delete(db_session_factory) -> None:
    session_factory = db_session_factory

    with session_factory() as session:
        counterparty = CounterpartyORM(
            id="CP-ITEST", name="Integration Test Capital", type="Hedge Fund", country="Ireland"
        )
        portfolio = PortfolioORM(id="PF-ITEST", counterparty_id="CP-ITEST", currency="USD")
        position = PositionORM(
            id="POS-ITEST",
            portfolio_id="PF-ITEST",
            ticker="AAPL",
            asset_class="equity",
            quantity=100.0,
            trade_date=date(2026, 1, 1),
        )
        rating = RatingORM(
            id="RTG-ITEST", counterparty_id="CP-ITEST", grade="A", rating_date=date(2026, 1, 1)
        )
        collateral = CollateralItemORM(
            id="COL-ITEST",
            counterparty_id="CP-ITEST",
            collateral_type="cash",
            value_usd=1000.0,
            haircut_pct=0.0,
        )
        audit = AuditLogORM(
            correlation_id="itest-corr-1",
            event_type="test_event",
            payload={"k": "v"},
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        ticket = TicketORM(
            counterparty_id="CP-ITEST", status="open", created_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
        session.add_all([counterparty, portfolio, position, rating, collateral, audit, ticket])
        session.commit()

    with session_factory() as session:
        cp_back = session.get(CounterpartyORM, "CP-ITEST")
        assert cp_back is not None
        assert cp_back.name == "Integration Test Capital"

        pos_back = session.get(PositionORM, "POS-ITEST")
        assert pos_back is not None
        assert pos_back.ticker == "AAPL"

        audit_back = session.query(AuditLogORM).filter_by(correlation_id="itest-corr-1").first()
        assert audit_back is not None
        assert audit_back.payload == {"k": "v"}

        assert cp_back.portfolios[0].id == "PF-ITEST"
        assert cp_back.portfolios[0].positions[0].ticker == "AAPL"

        session.delete(cp_back)
        session.delete(audit_back)
        session.commit()

    with session_factory() as session:
        assert session.get(PortfolioORM, "PF-ITEST") is None
        assert session.get(PositionORM, "POS-ITEST") is None
        assert session.get(RatingORM, "RTG-ITEST") is None
        assert session.get(CollateralItemORM, "COL-ITEST") is None
