"""MM-142: the five reports -- scope rules (an analyst sees only their live
counterparties; the simulated book is firm-wide only), the 10-minute cache,
the pre-aggregated-tables-only SQL, the refresh scripts, and the endpoints
(BigQuery mocked)."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.auth import Identity, require_user
from api.main import app, get_report_service, get_warehouse_client
from config.settings import Settings
from warehouse import refresh
from warehouse.client import MB
from warehouse.refresh import REFRESH_SCRIPTS, REPORT_QUERIES, refresh_reports, sql
from warehouse.reports import (
    REPORT_MAX_BYTES,
    ReportAccessError,
    ReportService,
    date_range,
    report_scope,
    visible_books,
)
from warehouse.schemas import SIM_END_DATE, SIM_START_DATE, TABLES, Book

TODAY = date(2026, 10, 6)


# --- scope -------------------------------------------------------------------------


def test_firm_wide_callers_see_both_books_and_every_counterparty():
    assert report_scope("*", Book.LIVE) == (True, [])
    assert report_scope("*", Book.HISTORICAL_SIM) == (True, [])
    assert visible_books("*") == [Book.LIVE, Book.HISTORICAL_SIM]


def test_analysts_see_only_their_live_counterparties():
    assert report_scope("CP-1,CP-3", Book.LIVE) == (False, ["CP-1", "CP-3"])
    assert report_scope("", Book.LIVE) == (False, [])  # no access rows: nothing
    assert visible_books("CP-1") == [Book.LIVE]
    with pytest.raises(ReportAccessError):
        report_scope("CP-1", Book.HISTORICAL_SIM)


def test_date_ranges_stay_inside_each_book():
    assert date_range(Book.HISTORICAL_SIM, "5y", TODAY) == (SIM_START_DATE, SIM_END_DATE)
    start, end = date_range(Book.HISTORICAL_SIM, "3m", TODAY)
    assert end == SIM_END_DATE and (end - start).days == 92
    start, end = date_range(Book.LIVE, "1y", TODAY)
    assert end == TODAY and start == date(2026, 8, 1)


# --- the SQL ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", REPORT_QUERIES)
def test_report_queries_read_report_tables_only(name):
    text = sql(name)
    facts = [t for t in TABLES if t.startswith(("fact_", "dim_"))]
    assert not any(f in text for f in facts), name
    assert "rpt_" in text
    assert "@book" in text and "@scope_all" in text and "UNNEST(@counterparty_ids)" in text


@pytest.mark.parametrize("name", list(REFRESH_SCRIPTS))
def test_refresh_scripts_drop_then_reinsert_their_range(name):
    text = sql(name)
    assert text.index("DELETE FROM rpt_") < text.index("INSERT INTO rpt_")
    assert "BETWEEN @start" in text


def test_unknown_sql_is_refused():
    with pytest.raises(KeyError):
        sql("../../etc/passwd")


def test_refresh_runs_every_script_with_a_cap():
    client = MagicMock()
    refresh_reports(client, date(2024, 2, 14), date(2024, 3, 2))
    names = [c.args[0] for c in client.run_script.call_args_list]
    assert names == [sql(n) for n in REFRESH_SCRIPTS]
    daily, concentration, _ = client.run_script.call_args_list
    assert [p.value for p in daily.args[1]] == [date(2024, 2, 14), date(2024, 3, 2)]
    assert [p.value for p in concentration.args[1]] == [date(2024, 2, 1), date(2024, 3, 1)]
    for call in client.run_script.call_args_list:
        assert call.kwargs["max_bytes"] in REFRESH_SCRIPTS.values()
    assert refresh.month_start(date(2024, 2, 29)) == date(2024, 2, 1)


# --- the service --------------------------------------------------------------------------


def _service(rows_by_query: dict, clock=lambda: 0.0):
    client = MagicMock()

    def query(text, params, max_bytes):
        assert max_bytes == REPORT_MAX_BYTES
        for name, rows in rows_by_query.items():
            if text == sql(name):
                return rows(params) if callable(rows) else rows
        raise AssertionError("unexpected query")

    client.query.side_effect = query
    return ReportService(client, clock=clock, today=lambda: TODAY), client


def _params(call) -> dict:
    return {p.name: p.value for p in call.args[1]}


def test_exposure_trend_passes_the_scope_and_is_cached():
    now = [0.0]
    rows = [
        {
            "as_of_date": date(2026, 9, 1),
            "counterparties": 2,
            "exposure": 10.0,
            "threshold": 5.0,
            "headroom": 1.0,
            "breached": 1,
            "shortfalls": 0,
        }
    ]
    service, client = _service({"report_exposure_trend": rows}, clock=lambda: now[0])
    report = service.exposure_trend("CP-1,CP-2", Book.LIVE, "1y")
    assert report.points[0].exposure == 10.0 and report.meta.scoped
    params = _params(client.query.call_args)
    assert params["scope_all"] is False and params["counterparty_ids"] == ["CP-1", "CP-2"]
    assert params["book"] == "live"

    service.exposure_trend("CP-1,CP-2", Book.LIVE, "1y")
    assert client.query.call_count == 1  # cached
    service.exposure_trend("*", Book.LIVE, "1y")
    assert client.query.call_count == 2  # another scope is another entry
    now[0] = 601.0
    service.exposure_trend("CP-1,CP-2", Book.LIVE, "1y")
    assert client.query.call_count == 3  # expired after 10 minutes


def test_a_scoped_caller_never_queries_the_simulated_book():
    service, client = _service({})
    with pytest.raises(ReportAccessError):
        service.stress_backtest("CP-1", Book.HISTORICAL_SIM, "5y")
    client.query.assert_not_called()


def test_collateral_adequacy_groups_buckets():
    rows = [
        {
            "as_of_date": date(2026, 7, 31),
            "counterparty_id": f"SIM-{i}",
            "tier": "standard",
            "required_support": 100.0,
            "collateral_held": held,
            "coverage_ratio": held / 100.0,
            "headroom": held - 100.0,
            "coverage_bucket": bucket,
        }
        for i, (held, bucket) in enumerate(
            [(50.0, "under 80%"), (90.0, "80-100%"), (150.0, "120% or more")]
        )
    ]
    service, _ = _service({"report_collateral_adequacy": rows})
    report = service.collateral_adequacy("*", Book.HISTORICAL_SIM, "3m")
    assert report.counterparties == 3 and report.collateral_held == 290.0
    buckets = {b.bucket: b.counterparties for b in report.buckets}
    assert buckets == {
        "under 80%": 1,
        "80-100%": 1,
        "100-120%": 0,
        "120% or more": 1,
        "no requirement": 0,
    }
    assert report.lowest_headroom[0].counterparty_id == "SIM-0"
    assert report.as_of_date == date(2026, 7, 31)


def test_collateral_adequacy_with_no_rows():
    service, _ = _service({"report_collateral_adequacy": []})
    report = service.collateral_adequacy("*", Book.LIVE, "3m")
    assert report.as_of_date is None and report.counterparties == 0


def test_concentration_splits_dimensions_and_falls_back_a_month_for_live():
    month_rows = [
        {"dimension": "sector", "key": "Energy", "gross": 5.0, "net": 5.0, "counterparties": 1, "as_of_date": date(2026, 9, 30)},
        {"dimension": "sector", "key": "Financials", "gross": 9.0, "net": -1.0, "counterparties": 2, "as_of_date": date(2026, 9, 30)},
        {"dimension": "asset_class", "key": "equity", "gross": 14.0, "net": 4.0, "counterparties": 2, "as_of_date": date(2026, 9, 30)},
        {"dimension": "ticker", "key": "JPM", "gross": 9.0, "net": -1.0, "counterparties": 2, "as_of_date": date(2026, 9, 30)},
    ]  # fmt: skip

    def rows(params):
        month = next(p.value for p in params if p.name == "month")
        return month_rows if month == date(2026, 9, 1) else []

    service, client = _service({"report_concentration": rows})
    report = service.concentration("*", Book.LIVE, "3m")
    assert [r.key for r in report.by_sector] == ["Financials", "Energy"]
    assert report.by_asset_class[0].gross == 14.0 and report.top_tickers[0].key == "JPM"
    assert report.as_of_date == date(2026, 9, 30)
    months = [_params(c)["month"] for c in client.query.call_args_list]
    assert months == [date(2026, 10, 1), date(2026, 9, 1)]


def test_margin_call_performance_and_stress():
    performance = [
        {
            "month": date(2024, 3, 1),
            "calls": 3,
            "amount": 30.0,
            "avg_approval_minutes": 12.5,
            "p90_approval_minutes": 20.0,
            "sla_met": 2,
            "sla_breached": 1,
            "escalations": 1,
            "open_calls": 0,
        }
    ]
    days = [
        {
            "as_of_date": date(2022, 6, 13),
            "calls_raised": 400,
            "call_amount": 9e6,
            "breached": 420,
            "vix": 34.0,
        }
    ]
    months = [
        {
            "month": date(2022, 6, 1),
            "calls_raised": 900,
            "call_amount": 2e7,
            "breach_days": 1000,
            "avg_vix": 29.0,
            "max_vix": 34.0,
        }
    ]
    service, _ = _service(
        {
            "report_margin_call_performance": performance,
            "report_stress_days": days,
            "report_stress_monthly": months,
        }
    )
    assert (
        service.margin_call_performance("*", Book.HISTORICAL_SIM, "5y").months[0].escalations == 1
    )
    stress = service.stress_backtest("*", Book.HISTORICAL_SIM, "5y")
    assert stress.top_days[0].calls_raised == 400 and stress.months[0].max_vix == 34.0


# --- endpoints ---------------------------------------------------------------------------

client = TestClient(app)
REPORT_PATHS = [
    "/reports/exposure-trend",
    "/reports/collateral-adequacy",
    "/reports/concentration",
    "/reports/margin-call-performance",
    "/reports/stress-backtest",
]


@pytest.fixture
def warehouse_on():
    settings = Settings(_env_file=None, warehouse="bigquery", gcp_project_id="p")
    with patch("api.main.get_settings", return_value=settings):
        yield


@pytest.fixture(autouse=True)
def _clear_caches():
    get_report_service.cache_clear()
    get_warehouse_client.cache_clear()
    yield
    get_report_service.cache_clear()
    get_warehouse_client.cache_clear()


def test_status_without_the_warehouse_is_not_configured():
    with patch("api.main.get_settings", return_value=Settings(_env_file=None)):
        response = client.get("/reports/status")
    assert response.status_code == 200
    assert response.json() == {"configured": False, "books": [], "scoped": False}


@pytest.mark.parametrize("path", REPORT_PATHS)
def test_reports_without_the_warehouse_are_503(path):
    with patch("api.main.get_settings", return_value=Settings(_env_file=None)):
        assert client.get(path).status_code == 503


def test_status_for_an_analyst(warehouse_on):
    app.dependency_overrides[require_user] = lambda: Identity(username="analyst1", role="viewer")
    with patch("api.main.get_db_session_factory"), patch("api.main.scope_for", return_value="CP-1"):
        response = client.get("/reports/status")
    assert response.json() == {"configured": True, "books": ["live"], "scoped": True}


@pytest.mark.parametrize(
    ("path", "method"),
    list(
        zip(
            REPORT_PATHS,
            [
                "exposure_trend",
                "collateral_adequacy",
                "concentration",
                "margin_call_performance",
                "stress_backtest",
            ],
            strict=True,
        )
    ),
)
def test_each_report_runs_as_the_caller(warehouse_on, path, method):
    service = MagicMock()
    getattr(service, method).return_value = None
    app.dependency_overrides[require_user] = lambda: Identity(username="analyst1", role="viewer")
    with (
        patch("api.main.get_report_service", return_value=service),
        patch("api.main.get_db_session_factory"),
        patch("api.main.scope_for", return_value="CP-1") as scope_for,
        patch.object(ReportService, method, autospec=True) as report,
    ):
        report.side_effect = lambda self, scope, book, period: (
            (_ for _ in ()).throw(ReportAccessError("no"))
            if book is Book.HISTORICAL_SIM
            else _empty(method, scope, book, period)
        )
        ok = client.get(f"{path}?book=live&period=3m")
        forbidden = client.get(f"{path}?book=historical-sim")
    assert ok.status_code == 200, ok.text
    assert forbidden.status_code == 403
    assert scope_for.call_args.args[:2] == ("viewer", "analyst1")
    assert report.call_args_list[0].args[1:] == ("CP-1", Book.LIVE, "3m")


def _empty(method, scope, book, period):
    from warehouse import reports

    meta = reports.ReportMeta(
        book=book.value,
        period=period,
        start_date=date(2026, 8, 1),
        end_date=TODAY,
        generated_at="2026-10-06T00:00:00Z",
        scoped=scope != "*",
    )
    return {
        "exposure_trend": reports.ExposureTrendReport(meta=meta, points=[]),
        "collateral_adequacy": reports.CollateralAdequacyReport(
            meta=meta,
            as_of_date=None,
            counterparties=0,
            required_support=0.0,
            collateral_held=0.0,
            buckets=[],
            lowest_headroom=[],
        ),
        "concentration": reports.ConcentrationReport(
            meta=meta, as_of_date=None, by_sector=[], by_asset_class=[], top_tickers=[]
        ),
        "margin_call_performance": reports.MarginCallPerformanceReport(meta=meta, months=[]),
        "stress_backtest": reports.StressBacktestReport(meta=meta, top_days=[], months=[]),
    }[method]


def test_bad_book_or_period_is_422(warehouse_on):
    assert client.get("/reports/exposure-trend?book=other").status_code == 422
    assert client.get("/reports/exposure-trend?period=10y").status_code == 422


def test_the_warehouse_client_needs_a_project():
    with patch(
        "api.main.get_settings", return_value=Settings(_env_file=None, warehouse="bigquery")
    ):
        assert client.get("/reports/exposure-trend").status_code == 503


def test_the_report_service_is_built_on_the_project_client(warehouse_on):
    with patch("warehouse.client.WarehouseClient") as built:
        service = get_report_service()
    built.assert_called_once_with("p", "marginmaestro_analytics")
    assert isinstance(service, ReportService)


def test_report_byte_cap():
    assert REPORT_MAX_BYTES == 500 * MB
