"""Refreshes the pre-aggregated report tables after a load (MM-142).

The SQL is committed in warehouse/sql/ and read by an allow-listed name, never
a path from input. Each script drops the affected partitions (0 bytes) and
re-inserts them, so a refresh is idempotent. The bytes cap per script is
sized from the scan noted at the top of each file.
"""

from datetime import date
from functools import cache
from pathlib import Path

from warehouse.client import GB, MB, QueryParam, WarehouseClient

SQL_DIR = Path(__file__).resolve().parent / "sql"

# script -> maximum bytes billed (the scan noted in the file, with margin)
REFRESH_SCRIPTS: dict[str, int] = {
    "refresh_rpt_counterparty_daily": 1 * GB,
    "refresh_rpt_concentration": 2 * GB,
    "refresh_rpt_margin_call": 500 * MB,
}
REPORT_QUERIES = (
    "report_exposure_trend",
    "report_collateral_adequacy",
    "report_concentration",
    "report_margin_call_performance",
    "report_stress_days",
    "report_stress_monthly",
)


@cache
def sql(name: str) -> str:
    if name not in REFRESH_SCRIPTS and name not in REPORT_QUERIES:
        raise KeyError(f"unknown warehouse SQL {name!r}")
    return (SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")


def month_start(day: date) -> date:
    return day.replace(day=1)


def refresh_reports(client: WarehouseClient, start: date, end: date) -> None:
    """Rebuilds every report table for [start, end]; the monthly reports are
    rebuilt for the whole months the range touches."""
    client.run_script(
        sql("refresh_rpt_counterparty_daily"),
        [QueryParam("start_date", "DATE", start), QueryParam("end_date", "DATE", end)],
        max_bytes=REFRESH_SCRIPTS["refresh_rpt_counterparty_daily"],
    )
    months = [
        QueryParam("start_month", "DATE", month_start(start)),
        QueryParam("end_month", "DATE", month_start(end)),
    ]
    for name in ("refresh_rpt_concentration", "refresh_rpt_margin_call"):
        client.run_script(sql(name), months, max_bytes=REFRESH_SCRIPTS[name])
