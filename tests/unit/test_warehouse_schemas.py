"""MM-139: the warehouse schemas are one source of truth -- the Terraform JSON,
the data catalog and the loaders all agree with src/warehouse/schemas.py."""

import json
from datetime import date
from pathlib import Path

import pytest

from governance.catalog import load_catalog
from warehouse import schemas
from warehouse.schemas import (
    SCHEMA_DIR,
    SIM_END_DATE,
    SIM_START_DATE,
    TABLES,
    Book,
    BookDateError,
    check_book_dates,
    render_schema_files,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG = load_catalog(ROOT / "docs" / "data_catalog.yaml")


def test_committed_terraform_schemas_match_the_python_schemas():
    """Run `python -m warehouse.schemas --write` after changing a schema."""
    for file_name, content in render_schema_files().items():
        assert (SCHEMA_DIR / file_name).read_text(encoding="utf-8") == content, file_name
    assert {p.name for p in SCHEMA_DIR.glob("*.json")} == set(render_schema_files())


def test_every_warehouse_table_and_column_is_catalogued():
    assert set(CATALOG.warehouse_tables) == set(TABLES)
    for name, table in TABLES.items():
        assert set(CATALOG.warehouse_tables[name].columns) == set(table.column_names), name


def test_confidential_warehouse_columns():
    """Quantities, market values, collateral and legal names are masked by the
    policy tag (ADR-0015); prices are public."""
    for ref in (
        "fact_position_daily.quantity",
        "fact_position_daily.market_value",
        "fact_daily_exposure.collateral_held",
        "rpt_counterparty_daily.collateral_held",
        "rpt_concentration.net_market_value",
        "dim_counterparty.name",
        "fact_margin_call.rationale",
    ):
        table, column = ref.split(".")
        assert CATALOG.warehouse_tables[table].columns[column].class_ == "confidential", ref
    assert CATALOG.warehouse_tables["fact_price_daily"].class_ == "public"


def test_warehouse_tables_stay_out_of_the_llm_filter():
    """The LLM data-class filter reads `tables` only; the warehouse is never
    sent to a model."""
    assert not set(CATALOG.warehouse_tables) & set(CATALOG.tables)


def test_large_facts_require_a_partition_filter():
    assert TABLES["fact_position_daily"].require_partition_filter
    assert TABLES["fact_daily_exposure"].require_partition_filter


def test_every_table_but_the_calendar_carries_the_book():
    for name, table in TABLES.items():
        if name == "dim_date":
            assert "book" not in table.column_names
        else:
            assert "book" in table.column_names, name


def test_partitioning_is_declared_consistently():
    for table in TABLES.values():
        if table.partition_type == "BOOK":
            assert table.partition_column == "book_key"
            assert table.column("book_key").type == "INT64"
        elif table.partition_type in ("DAY", "MONTH"):
            assert table.column(table.partition_column or "").type == "DATE"
        for column in table.clustering:
            assert column in table.column_names


def test_bq_schema_shape():
    field = TABLES["fact_margin_call"].bq_schema()
    approved = next(f for f in field if f["name"] == "approved_at")
    assert approved == {
        "name": "approved_at",
        "type": "TIMESTAMP",
        "mode": "NULLABLE",
        "description": "First approval decision",
    }
    spec = json.loads(render_schema_files()["fact_position_daily.json"])
    assert spec["has_counterparty"] and spec["partition_type"] == "DAY"


def test_unknown_column_lookup_fails():
    with pytest.raises(KeyError):
        TABLES["dim_date"].column("nope")


@pytest.mark.parametrize(
    ("book", "start", "end"),
    [
        (Book.HISTORICAL_SIM, SIM_START_DATE, SIM_END_DATE),
        (Book.LIVE, date(2026, 8, 1), date(2026, 10, 6)),
    ],
)
def test_each_book_may_write_its_own_dates(book, start, end):
    check_book_dates(book, start, end)


@pytest.mark.parametrize(
    ("book", "start", "end"),
    [
        (Book.HISTORICAL_SIM, date(2026, 7, 1), date(2026, 8, 1)),
        (Book.HISTORICAL_SIM, date(2021, 7, 30), date(2021, 8, 5)),
        (Book.LIVE, SIM_END_DATE, SIM_END_DATE),
        (Book.LIVE, date(2026, 10, 6), date(2026, 10, 5)),
    ],
)
def test_a_book_may_not_write_the_other_books_dates(book, start, end):
    with pytest.raises(BookDateError):
        check_book_dates(book, start, end)


def test_schema_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(schemas, "SCHEMA_DIR", tmp_path)
    schemas.main(["--write"])
    assert (tmp_path / "tables.json").is_file()
    schemas.main([])
    assert "fact_position_daily" in capsys.readouterr().out
