"""Warehouse table schemas (MM-139) -- the single source of truth.

Terraform reads the JSON files generated from these definitions
(`infra/gcp/bigquery_schemas/<table>.json`, rewritten by
`python -m warehouse.schemas --write`); a unit test fails if they drift. The
loaders write CSV in exactly this column order, and the catalog test checks
docs/data_catalog.yaml's `warehouse_tables` against the same columns.

Books and dates. Every row carries `book`: `historical-sim` (the 1,000
synthetic counterparties, back-tested over five years of real closes) or
`live` (the app's own counterparties). A date belongs to exactly one book:
the simulated book owns every date up to SIM_END_DATE and the live book every
date after it. Loads therefore replace whole date partitions -- a DELETE on
the partition column alone, which BigQuery runs as a metadata operation with
no bytes scanned, followed by a batch load (free) -- and can never touch the
other book's rows. The dimension tables are partitioned by `book_key`
(0 = historical-sim, 1 = live) for the same reason. `dim_date` is the one
table without a book: it is the shared calendar.
"""

import argparse
import json
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

DATASET = "marginmaestro_analytics"
LOCATION = "us-central1"

# The simulated book's window: five years of trading days, ending at the
# last month-end before the live book's first warehouse day.
SIM_START_DATE = date(2021, 8, 1)
SIM_END_DATE = date(2026, 7, 31)


class Book(StrEnum):
    HISTORICAL_SIM = "historical-sim"
    LIVE = "live"


BOOK_KEY: dict[Book, int] = {Book.HISTORICAL_SIM: 0, Book.LIVE: 1}


class BookDateError(ValueError):
    """A load tried to write a date that belongs to the other book."""


def check_book_dates(book: Book, start: date, end: date) -> None:
    """Fails loud if [start, end] crosses into the other book's dates."""
    if start > end:
        raise BookDateError(f"empty date range {start}..{end}")
    if book is Book.HISTORICAL_SIM and not (SIM_START_DATE <= start and end <= SIM_END_DATE):
        raise BookDateError(
            f"historical-sim owns {SIM_START_DATE}..{SIM_END_DATE}; refused {start}..{end}"
        )
    if book is Book.LIVE and start <= SIM_END_DATE:
        raise BookDateError(f"live owns dates after {SIM_END_DATE}; refused {start}..{end}")


FieldType = Literal["STRING", "INT64", "FLOAT64", "BOOL", "DATE", "TIMESTAMP"]
_BQ_TYPE = {
    "STRING": "STRING",
    "INT64": "INTEGER",
    "FLOAT64": "FLOAT",
    "BOOL": "BOOLEAN",
    "DATE": "DATE",
    "TIMESTAMP": "TIMESTAMP",
}
# Logical (billed) bytes per value: STRING is 2 + UTF-8 length; NULL is 0.
FIXED_SIZE = {"INT64": 8, "FLOAT64": 8, "BOOL": 1, "DATE": 8, "TIMESTAMP": 8}


class Column(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    type: FieldType
    description: str
    required: bool = True


class Table(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    columns: tuple[Column, ...]
    # Day (or month) partitioning on a DATE column, or integer-range
    # partitioning on book_key for the dimensions; None = unpartitioned.
    partition_column: str | None = None
    partition_type: Literal["DAY", "MONTH", "BOOK"] | None = None
    clustering: tuple[str, ...] = ()
    require_partition_filter: bool = False
    kind: Literal["fact", "dimension", "report"] = "fact"

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def column(self, name: str) -> Column:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(f"{self.name} has no column {name!r}")

    def bq_schema(self) -> list[dict]:
        """The table schema as the BigQuery API / Terraform expects it."""
        return [
            {
                "name": c.name,
                "type": _BQ_TYPE[c.type],
                "mode": "REQUIRED" if c.required else "NULLABLE",
                "description": c.description,
            }
            for c in self.columns
        ]


def _c(name: str, type_: FieldType, description: str, required: bool = True) -> Column:
    return Column(name=name, type=type_, description=description, required=required)


BOOK = _c("book", "STRING", "live | historical-sim")
BOOK_KEY_COL = _c("book_key", "INT64", "Partition key: 0 = historical-sim, 1 = live")
CP = _c("counterparty_id", "STRING", "Counterparty id (CP-n live, SIM-nnnn simulated)")

FACT_DAILY_EXPOSURE = Table(
    name="fact_daily_exposure",
    description=(
        "Counterparty x trading day: exposure (VM + IM), collateral, CSA threshold/MTA, "
        "headroom and the call due -- all computed by the calc engine."
    ),
    columns=(
        _c("as_of_date", "DATE", "Trading day (partition)"),
        BOOK,
        CP,
        _c("csa_version", "INT64", "dim_csa_terms version in force that day"),
        _c("rating", "STRING", "Counterparty rating that day", required=False),
        _c("vix", "FLOAT64", "VIX close used for initial margin"),
        _c("variation_margin", "FLOAT64", "MTM today - MTM at the prior close"),
        _c("initial_margin", "FLOAT64", "SIMM-proxy initial margin"),
        _c("exposure", "FLOAT64", "variation_margin + initial_margin"),
        _c("threshold", "FLOAT64", "Effective CSA threshold (after rating triggers)"),
        _c("mta", "FLOAT64", "CSA minimum transfer amount"),
        _c("collateral_held", "FLOAT64", "Collateral held after haircuts (confidential)"),
        _c("required_support", "FLOAT64", "max(0, exposure - threshold)"),
        _c("headroom", "FLOAT64", "threshold + collateral_held - exposure (negative = shortfall)"),
        _c("call_due", "FLOAT64", "Delivery amount when breached, else 0"),
        _c("breached", "BOOL", "Shortfall > 0 and >= MTA (calc.breach.evaluate_breach)"),
        _c("call_raised", "BOOL", "A margin call was raised that day (no call already open)"),
        _c("currency", "STRING", "CSA currency"),
    ),
    partition_column="as_of_date",
    partition_type="DAY",
    clustering=("counterparty_id", "book"),
    require_partition_filter=True,
)

FACT_POSITION_DAILY = Table(
    name="fact_position_daily",
    description="Position x trading day: quantity, close and market value.",
    columns=(
        _c("as_of_date", "DATE", "Trading day (partition)"),
        BOOK,
        CP,
        _c("position_id", "STRING", "Position id"),
        _c("ticker", "STRING", "Instrument ticker (Yahoo Finance form)"),
        _c("asset_class", "STRING", "equity | etf | crypto"),
        _c("quantity", "FLOAT64", "Signed quantity (confidential)"),
        _c("close", "FLOAT64", "Daily close (real, Yahoo Finance)"),
        _c("market_value", "FLOAT64", "quantity x close (confidential)"),
    ),
    partition_column="as_of_date",
    partition_type="DAY",
    clustering=("counterparty_id", "ticker"),
    require_partition_filter=True,
)

FACT_MARGIN_CALL = Table(
    name="fact_margin_call",
    description="One row per margin call raised, with its lifecycle timestamps and outcome.",
    columns=(
        _c("raised_date", "DATE", "UTC date the call was raised (partition)"),
        BOOK,
        _c("call_id", "STRING", "Call id (orchestrator thread id for live calls)"),
        CP,
        _c("trigger_type", "STRING", "daily_margin_run, price_shock, rating_downgrade, ..."),
        _c("call_amount", "FLOAT64", "Call amount (the adjusted amount when adjusted)"),
        _c("currency", "STRING", "CSA currency"),
        _c("rationale", "STRING", "Why the call was raised, generated by code", required=False),
        _c("raised_at", "TIMESTAMP", "When the call was raised"),
        _c("approval_decision", "STRING", "approved | adjusted | rejected | ...", required=False),
        _c("approved_at", "TIMESTAMP", "First approval decision", required=False),
        _c("approver", "STRING", "First approver's username", required=False),
        _c("manager_approved_at", "TIMESTAMP", "Second signature (elite)", required=False),
        _c("notified_at", "TIMESTAMP", "Client notice sent", required=False),
        _c("channel", "STRING", "slack | whatsapp | simulated", required=False),
        _c("acknowledged_at", "TIMESTAMP", "Client acknowledged within SLA", required=False),
        _c("escalated_at", "TIMESTAMP", "Escalated to ServiceNow", required=False),
        _c("sla_outcome", "STRING", "met | breached | null while open", required=False),
        _c("status", "STRING", "Lifecycle status when loaded"),
    ),
    partition_column="raised_date",
    partition_type="DAY",
    clustering=("counterparty_id", "book"),
)

FACT_PRICE_DAILY = Table(
    name="fact_price_daily",
    description="Symbol x trading day: real daily closes (Yahoo Finance) and FRED reference rates.",
    columns=(
        _c("price_date", "DATE", "Trading day (partition)"),
        BOOK,
        _c("symbol", "STRING", "Ticker, ^VIX, or FRED series id"),
        _c("kind", "STRING", "close | rate"),
        _c("value", "FLOAT64", "Close in USD, or the rate/index level"),
        _c("source", "STRING", "yfinance | fred | eod"),
    ),
    partition_column="price_date",
    partition_type="DAY",
    clustering=("symbol",),
)

DIM_COUNTERPARTY = Table(
    name="dim_counterparty",
    description="Counterparties of both books (simulated names are clearly synthetic).",
    columns=(
        BOOK_KEY_COL,
        BOOK,
        CP,
        _c("name", "STRING", "Legal name (confidential)"),
        _c("type", "STRING", "Bank | Hedge Fund | Asset Manager"),
        _c("country", "STRING", "Jurisdiction"),
        _c("tier", "STRING", "standard | elite"),
        _c("rating", "STRING", "Current rating", required=False),
    ),
    partition_column="book_key",
    partition_type="BOOK",
    clustering=("counterparty_id",),
    kind="dimension",
)

DIM_INSTRUMENT = Table(
    name="dim_instrument",
    description="Instruments held by each book, with GICS sector from the S&P 500 snapshot.",
    columns=(
        BOOK_KEY_COL,
        BOOK,
        _c("ticker", "STRING", "Ticker (Yahoo Finance form)"),
        _c("security", "STRING", "Security name", required=False),
        _c("asset_class", "STRING", "equity | etf | crypto"),
        _c("sector", "STRING", "GICS sector; ETF / Crypto for those asset classes"),
        _c("sub_industry", "STRING", "GICS sub-industry", required=False),
        _c("in_sp500", "BOOL", "In the S&P 500 snapshot"),
    ),
    partition_column="book_key",
    partition_type="BOOK",
    clustering=("ticker",),
    kind="dimension",
)

DIM_CSA_TERMS = Table(
    name="dim_csa_terms",
    description="CSA terms per counterparty, SCD type 2 (valid_from / valid_to).",
    columns=(
        BOOK_KEY_COL,
        BOOK,
        CP,
        _c("csa_version", "INT64", "1, 2, ... per counterparty"),
        _c("valid_from", "DATE", "First day in force"),
        _c("valid_to", "DATE", "Last day in force (9999-12-31 = current)"),
        _c("is_current", "BOOL", "The version in force now"),
        _c("threshold", "FLOAT64", "Base threshold"),
        _c("mta", "FLOAT64", "Minimum transfer amount"),
        _c("currency", "STRING", "CSA currency"),
        _c("trigger_below_grade", "STRING", "Rating trigger grade", required=False),
        _c("trigger_threshold", "FLOAT64", "Threshold once the trigger fires", required=False),
        _c("haircut_cash", "FLOAT64", "Null = not eligible", required=False),
        _c("haircut_treasury", "FLOAT64", "Null = not eligible", required=False),
        _c("haircut_corporate", "FLOAT64", "Null = not eligible", required=False),
        _c("haircut_mmf", "FLOAT64", "Null = not eligible", required=False),
        _c("change_reason", "STRING", "initial | renegotiated | extracted"),
    ),
    partition_column="book_key",
    partition_type="BOOK",
    clustering=("counterparty_id",),
    kind="dimension",
)

DIM_DATE = Table(
    name="dim_date",
    description="Shared calendar (no book): one row per day, 2021-2030.",
    columns=(
        _c("date_key", "DATE", "Calendar day"),
        _c("year", "INT64", "Year"),
        _c("quarter", "INT64", "1-4"),
        _c("month", "INT64", "1-12"),
        _c("day_of_week", "INT64", "1 = Monday ... 7 = Sunday"),
        _c("is_weekday", "BOOL", "Monday-Friday"),
        _c("is_month_end", "BOOL", "Last calendar day of the month"),
        _c("year_quarter", "STRING", "e.g. 2024-Q1"),
        _c("year_month", "STRING", "e.g. 2024-01"),
    ),
    kind="dimension",
)

# Pre-aggregated report tables (MM-142): refreshed by the committed SQL in
# warehouse/sql/ after every load; the API, Tableau and any dashboard read
# these only, never the facts.
RPT_COUNTERPARTY_DAILY = Table(
    name="rpt_counterparty_daily",
    description="Reports 1, 2, 5: exposure, headroom, collateral adequacy and calls per day.",
    columns=(
        _c("as_of_date", "DATE", "Trading day (partition)"),
        BOOK,
        CP,
        _c("tier", "STRING", "standard | elite"),
        _c("exposure", "FLOAT64", "Exposure"),
        _c("threshold", "FLOAT64", "Effective threshold"),
        _c("headroom", "FLOAT64", "threshold + collateral_held - exposure"),
        _c("required_support", "FLOAT64", "max(0, exposure - threshold)"),
        _c("collateral_held", "FLOAT64", "Collateral after haircuts (confidential)"),
        _c("coverage_ratio", "FLOAT64", "collateral_held / required_support", required=False),
        _c("breached", "BOOL", "Breached"),
        _c("call_raised", "BOOL", "Call raised that day"),
        _c("call_due", "FLOAT64", "Call amount due"),
        _c("vix", "FLOAT64", "VIX close"),
    ),
    partition_column="as_of_date",
    partition_type="DAY",
    clustering=("book", "counterparty_id"),
    kind="report",
)

RPT_CONCENTRATION = Table(
    name="rpt_concentration",
    description="Report 3: month-end gross/net market value by counterparty, ticker and sector.",
    columns=(
        _c("month_start", "DATE", "First day of the month (partition)"),
        _c("as_of_date", "DATE", "Last trading day of the month loaded"),
        BOOK,
        CP,
        _c("ticker", "STRING", "Ticker"),
        _c("sector", "STRING", "GICS sector (ETF / Crypto / Unknown otherwise)"),
        _c("asset_class", "STRING", "Asset class"),
        _c("gross_market_value", "FLOAT64", "abs(market value)"),
        _c("net_market_value", "FLOAT64", "Signed market value (confidential)"),
    ),
    partition_column="month_start",
    partition_type="MONTH",
    clustering=("book", "counterparty_id", "sector"),
    kind="report",
)

RPT_MARGIN_CALL = Table(
    name="rpt_margin_call",
    description="Report 4: one row per call with approval turnaround and SLA result.",
    columns=(
        _c("raised_date", "DATE", "UTC date raised (partition)"),
        BOOK,
        _c("call_id", "STRING", "Call id"),
        CP,
        _c("tier", "STRING", "standard | elite", required=False),
        _c("trigger_type", "STRING", "Trigger type"),
        _c("call_amount", "FLOAT64", "Call amount"),
        _c("approval_minutes", "FLOAT64", "raised_at -> approved_at", required=False),
        _c("notify_minutes", "FLOAT64", "raised_at -> notified_at", required=False),
        _c("sla_outcome", "STRING", "met | breached | null", required=False),
        _c("escalated", "BOOL", "Escalated"),
        _c("status", "STRING", "Lifecycle status"),
    ),
    partition_column="raised_date",
    partition_type="MONTH",
    clustering=("book", "counterparty_id"),
    kind="report",
)

TABLES: dict[str, Table] = {
    t.name: t
    for t in (
        FACT_DAILY_EXPOSURE,
        FACT_POSITION_DAILY,
        FACT_MARGIN_CALL,
        FACT_PRICE_DAILY,
        DIM_COUNTERPARTY,
        DIM_INSTRUMENT,
        DIM_CSA_TERMS,
        DIM_DATE,
        RPT_COUNTERPARTY_DAILY,
        RPT_CONCENTRATION,
        RPT_MARGIN_CALL,
    )
}

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "infra" / "gcp" / "bigquery_schemas"


def terraform_table_spec(table: Table) -> dict:
    """What infra/gcp/bigquery.tf reads per table (besides the schema)."""
    return {
        "description": table.description,
        "kind": table.kind,
        "partition_column": table.partition_column,
        "partition_type": table.partition_type,
        "clustering": list(table.clustering),
        "require_partition_filter": table.require_partition_filter,
        "has_counterparty": "counterparty_id" in table.column_names,
        "schema": table.bq_schema(),
    }


def render_schema_files() -> dict[str, str]:
    """file name -> content, for every table plus the index Terraform reads."""
    files = {
        f"{name}.json": json.dumps(terraform_table_spec(table), indent=2) + "\n"
        for name, table in TABLES.items()
    }
    files["tables.json"] = json.dumps(sorted(TABLES), indent=2) + "\n"
    return files


def write_schema_files() -> int:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    files = render_schema_files()
    for file_name, content in files.items():
        (SCHEMA_DIR / file_name).write_text(content, encoding="utf-8")
    return len(files)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Warehouse schemas (MM-139)")
    parser.add_argument("--write", action="store_true", help="rewrite infra/gcp/bigquery_schemas")
    args = parser.parse_args(argv)
    if args.write:
        print(f"wrote {write_schema_files()} files")
    else:
        for name, table in TABLES.items():
            print(f"{name}: {len(table.columns)} columns")


if __name__ == "__main__":
    main()
