"""Real end-to-end run of the batch loader against a live local DB (docker
compose up -d sqlserver) and the real price/FRED adapters (MARKET_FEED_MODE=live,
FRED_API_KEY set). Excluded from the default/CI run -- see the `live` marker
in pyproject.toml.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from config.settings import get_settings
from persistence.batch_loader import run_batch_load
from persistence.db.bootstrap import ensure_database_exists
from persistence.db.engine import get_engine, get_session_factory
from persistence.db.models import AuditLogORM, Base, PriceHistoryORM, ReferenceRateORM

pytestmark = pytest.mark.live


def test_run_batch_load_populates_prices_rates_and_audit_log() -> None:
    settings = get_settings()
    try:
        ensure_database_exists(settings)
        engine = get_engine(settings)
        Base.metadata.create_all(engine)
        engine.dispose()
    except DBAPIError as exc:
        pytest.skip(f"No reachable database for integration tests: {exc}")

    as_of = datetime.now(UTC).date()
    summary = run_batch_load(as_of=as_of)

    assert summary["prices"] > 0
    assert summary["reference_rates"] > 0

    session_factory = get_session_factory(settings)
    with session_factory() as session:
        price_rows = session.scalars(
            select(PriceHistoryORM).where(PriceHistoryORM.price_date == as_of)
        ).all()
        rate_rows = session.scalars(
            select(ReferenceRateORM).where(ReferenceRateORM.rate_date == as_of)
        ).all()
        audit_rows = session.scalars(
            select(AuditLogORM).where(AuditLogORM.event_type == "batch_load")
        ).all()

    assert len(price_rows) == summary["prices"]
    assert len(rate_rows) == summary["reference_rates"]
    assert len(audit_rows) >= 1
