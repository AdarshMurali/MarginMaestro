"""MM-141: POST /internal/warehouse/daily-load, and the load the daily margin
run triggers when WAREHOUSE=bigquery (best effort: never fails the run)."""

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_report_service, get_warehouse_client
from config.settings import Settings
from streaming.schemas import ImpactSet, MarketEventType
from warehouse.client import WarehouseError
from warehouse.live_load import LoadResult, NoClosesError
from warehouse.schemas import BookDateError

URL = "/internal/warehouse/daily-load"
AUTH = {"Authorization": "Bearer job-token"}
client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear():
    get_warehouse_client.cache_clear()
    get_report_service.cache_clear()
    yield
    get_warehouse_client.cache_clear()


def _settings(warehouse: str = "bigquery") -> Settings:
    return Settings(
        _env_file=None, internal_job_token="job-token", warehouse=warehouse, gcp_project_id="p"
    )


def _post(load, warehouse="bigquery", url=URL, headers=AUTH):
    settings = _settings(warehouse)
    with (
        patch("api.auth.get_settings", return_value=settings),
        patch("api.main.get_settings", return_value=settings),
        patch("api.main.get_db_session_factory", return_value=MagicMock()),
        patch("api.main.get_orchestrator_graph", return_value=MagicMock()),
        patch("api.main.get_warehouse_client", return_value=MagicMock()),
        patch("warehouse.live_load.load_live_day", **load) as load_live_day,
    ):
        return client.post(url, headers=headers), load_live_day


def test_loads_the_day_and_reports_rows():
    result = LoadResult(
        as_of=date(2026, 10, 5), rows={"fact_daily_exposure": 8}, skipped=["CP-9: x"]
    )
    response, load = _post({"return_value": result}, url=f"{URL}?as_of=2026-10-05")
    assert response.status_code == 200
    assert response.json() == {
        "as_of": "2026-10-05",
        "rows": {"fact_daily_exposure": 8},
        "skipped": ["CP-9: x"],
    }
    assert load.call_args.args[3] == date(2026, 10, 5)


def test_needs_an_internal_caller():
    response, load = _post({"return_value": None}, headers={})
    assert response.status_code == 401
    load.assert_not_called()


def test_disabled_warehouse_is_503():
    response, load = _post({"return_value": None}, warehouse="none")
    assert response.status_code == 503
    load.assert_not_called()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (NoClosesError("no closes"), 409),
        (BookDateError("simulated date"), 409),
        (WarehouseError("quota"), 503),
    ],
)
def test_errors_map_to_retryable_or_not(error, status):
    response, _ = _post({"side_effect": error})
    assert response.status_code == status


# --- after the daily margin run -------------------------------------------------------


def _daily_run(warehouse: str, load_side_effect=None):
    settings = _settings(warehouse)
    impact = ImpactSet(
        event_id="daily-margin-run:2026-10-05",
        event_type=MarketEventType.DAILY_MARGIN_RUN,
        counterparty_ids=["CP-1"],
        reason="Daily margin run",
        occurred_at=datetime(2026, 10, 5, 20, 45, tzinfo=UTC),
    )
    with (
        patch("api.auth.get_settings", return_value=settings),
        patch("api.main.get_settings", return_value=settings),
        patch("api.main.get_db_session_factory", return_value=MagicMock()),
        patch("api.main.daily_margin_run_impact", return_value=impact),
        patch("api.main.live_graph_factory"),
        patch("api.main.handle_impact", return_value=[]),
        patch("api.main.get_orchestrator_graph", return_value=MagicMock()),
        patch("api.main.get_warehouse_client", return_value=MagicMock()),
        patch("warehouse.live_load.load_live_day", side_effect=load_side_effect) as load,
    ):
        response = client.post("/internal/margin/daily-run", headers=AUTH)
    return response, load


def test_the_daily_run_triggers_the_warehouse_load():
    response, load = _daily_run("bigquery")
    assert response.status_code == 200
    load.assert_called_once()


def test_a_warehouse_failure_never_fails_the_daily_run():
    response, load = _daily_run("bigquery", WarehouseError("down"))
    assert response.status_code == 200
    load.assert_called_once()


def test_no_warehouse_no_load():
    response, load = _daily_run("none")
    assert response.status_code == 200
    load.assert_not_called()
