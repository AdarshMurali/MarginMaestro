"""MM-124: the daily end-of-day load into price_history and its endpoint."""

from datetime import date
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import app
from config.settings import Settings
from persistence.daily_close import (
    EOD_SOURCE,
    EOD_WINDOW_DAYS,
    load_daily_closes,
    refresh_reference_rates,
)
from persistence.db.models import Base, PriceHistoryORM
from persistence.fred_feed import RateDataUnavailableError
from streaming.market_feed import MarketDataUnavailableError, PriceHistoryPoint


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _history(ticker: str, days: int):
    if ticker == "BAD":
        raise MarketDataUnavailableError("no data for BAD")
    return [
        PriceHistoryPoint(date=date(2026, 10, 1), price=65.07),
        PriceHistoryPoint(date=date(2026, 10, 2), price=69.88),
    ]


def _rows(session_factory):
    with session_factory() as session:
        return session.execute(
            select(
                PriceHistoryORM.ticker, PriceHistoryORM.price_date, PriceHistoryORM.price
            ).order_by(PriceHistoryORM.ticker, PriceHistoryORM.price_date)
        ).all()


def test_appends_closes_and_reports_failures(session_factory):
    with (
        patch("persistence.daily_close.get_price_history", side_effect=_history) as fetch,
        session_factory() as session,
    ):
        result = load_daily_closes(session, ["HPE", "BAD"])

    assert result == {"loaded": ["HPE"], "failed": ["BAD"]}
    assert fetch.call_args_list[0].kwargs == {"days": EOD_WINDOW_DAYS}
    assert _rows(session_factory) == [
        ("HPE", date(2026, 10, 1), 65.07),
        ("HPE", date(2026, 10, 2), 69.88),
    ]


def test_rerunning_replaces_rather_than_duplicates(session_factory):
    with session_factory() as session:
        session.add(
            PriceHistoryORM(
                ticker="HPE", price_date=date(2026, 10, 2), price=1.0, currency="USD", source="x"
            )
        )
        session.commit()

    with patch("persistence.daily_close.get_price_history", side_effect=_history):
        for _ in range(2):
            with session_factory() as session:
                load_daily_closes(session, ["HPE"])

    assert _rows(session_factory) == [
        ("HPE", date(2026, 10, 1), 65.07),
        ("HPE", date(2026, 10, 2), 69.88),
    ]
    with session_factory() as session:
        assert {r.source for r in session.execute(select(PriceHistoryORM)).scalars()} == {
            EOD_SOURCE
        }


def test_reference_rates_are_skipped_without_a_fred_key(session_factory):
    with (
        patch("persistence.daily_close.FredFeed", side_effect=RateDataUnavailableError("no key")),
        session_factory() as session,
    ):
        assert refresh_reference_rates(session, Settings(_env_file=None)) == 0


def test_reference_rates_load_when_fred_is_configured(session_factory):
    with (
        patch("persistence.daily_close.FredFeed") as feed,
        patch("persistence.batch_loader.load_reference_rates", return_value=5) as load,
        session_factory() as session,
    ):
        assert refresh_reference_rates(session, Settings(_env_file=None)) == 5

    assert load.call_args.args[1] is feed.return_value


def test_eod_endpoint_runs_both_loads_for_the_universe(session_factory):
    settings = Settings(_env_file=None, internal_job_token="t", market_universe="HPE,BAD")
    with (
        patch("api.auth.get_settings", return_value=settings),
        patch("api.main.get_settings", return_value=settings),
        patch("api.main.get_db_session_factory", return_value=session_factory),
        patch("persistence.daily_close.get_price_history", side_effect=_history),
        patch("api.main.refresh_reference_rates", return_value=5),
    ):
        response = TestClient(app).post(
            "/internal/prices/eod", headers={"Authorization": "Bearer t"}
        )

    assert response.status_code == 200
    assert response.json() == {"tickers_loaded": 1, "tickers_failed": ["BAD"], "reference_rates": 5}


def test_eod_endpoint_needs_the_internal_caller():
    settings = Settings(_env_file=None, internal_job_token="t")
    with patch("api.auth.get_settings", return_value=settings):
        response = TestClient(app).post(
            "/internal/prices/eod", headers={"Authorization": "Bearer nope"}
        )

    assert response.status_code == 401
