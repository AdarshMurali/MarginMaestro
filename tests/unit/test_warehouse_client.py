"""MM-139: the BigQuery wrapper enforces the cost guardrails -- every query
has a bytes cap, writes are batch loads (WRITE_APPEND after a whole-partition
DELETE), and there is no streaming insert at all."""

import csv
import gzip
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

from warehouse.client import (
    DELETE_CAP_BYTES,
    GB,
    QUERY_CEILING_BYTES,
    QueryParam,
    WarehouseClient,
    WarehouseError,
    write_csv_gz,
)
from warehouse.schemas import DIM_DATE, FACT_PRICE_DAILY

bigquery = pytest.importorskip("google.cloud.bigquery")


def _client() -> tuple[WarehouseClient, MagicMock]:
    fake = MagicMock()
    fake.query.return_value.result.return_value = []
    fake.load_table_from_file.return_value.output_rows = 2
    return WarehouseClient("proj", client=fake), fake


def test_every_query_carries_a_bytes_cap():
    client, fake = _client()
    client.query("SELECT 1", [QueryParam("d", "DATE", date(2024, 1, 2))], max_bytes=10 * GB // 10)
    config = fake.query.call_args.kwargs["job_config"]
    assert config.maximum_bytes_billed == GB
    assert config.default_dataset.dataset_id == "marginmaestro_analytics"
    assert config.query_parameters[0].name == "d"


@pytest.mark.parametrize("cap", [0, -1, QUERY_CEILING_BYTES + 1])
def test_caps_outside_the_ceiling_are_refused(cap):
    client, fake = _client()
    with pytest.raises(WarehouseError):
        client.query("SELECT 1", max_bytes=cap)
    fake.query.assert_not_called()


def test_query_rows_and_failures():
    client, fake = _client()
    row = MagicMock()
    row.items.return_value = [("a", 1)]
    fake.query.return_value.result.return_value = [row]
    assert client.query("SELECT 1", max_bytes=GB) == [{"a": 1}]
    fake.query.return_value.result.side_effect = RuntimeError("bytes billed exceeded")
    with pytest.raises(WarehouseError, match="bytes billed exceeded"):
        client.query("SELECT 1", max_bytes=GB)


def test_array_parameters():
    client, fake = _client()
    client.query("SELECT 1", [QueryParam("ids", "STRING", ["CP-1"], array=True)], max_bytes=GB)
    param = fake.query.call_args.kwargs["job_config"].query_parameters[0]
    assert isinstance(param, bigquery.ArrayQueryParameter)


def test_estimate_bytes_is_a_dry_run():
    client, fake = _client()
    fake.query.return_value.total_bytes_processed = 1234
    assert client.estimate_bytes("SELECT 1") == 1234
    assert fake.query.call_args.kwargs["job_config"].dry_run is True


def test_replace_deletes_whole_partitions_then_appends():
    client, fake = _client()
    rows = [(date(2026, 8, 3), "live", "AAPL", "close", 1.5, "eod")]
    loaded = client.replace(FACT_PRICE_DAILY, date(2026, 8, 3), date(2026, 8, 3), rows)

    assert loaded == 2
    delete_sql = fake.query.call_args.args[0]
    assert delete_sql == (
        "DELETE FROM `proj.marginmaestro_analytics.fact_price_daily` "
        "WHERE price_date BETWEEN @start AND @end"
    )
    assert fake.query.call_args.kwargs["job_config"].maximum_bytes_billed == DELETE_CAP_BYTES
    config = fake.load_table_from_file.call_args.kwargs["job_config"]
    assert config.write_disposition == "WRITE_APPEND"  # never TRUNCATE: keeps row policies
    assert config.source_format == "CSV"
    assert config.create_disposition == "CREATE_NEVER"
    assert [f.name for f in config.schema] == FACT_PRICE_DAILY.column_names
    assert not fake.insert_rows.called and not fake.insert_rows_json.called


def test_replace_with_no_rows_still_clears_the_slice():
    client, fake = _client()
    assert client.replace(FACT_PRICE_DAILY, date(2026, 8, 3), date(2026, 8, 3), []) == 0
    fake.query.assert_called_once()
    fake.load_table_from_file.assert_not_called()


def test_a_failed_load_is_loud():
    client, fake = _client()
    fake.load_table_from_file.return_value.result.side_effect = RuntimeError("bad row")
    with pytest.raises(WarehouseError, match="fact_price_daily"):
        client.replace(
            FACT_PRICE_DAILY,
            date(2026, 8, 3),
            date(2026, 8, 3),
            [(date(2026, 8, 3), "live", "A", "close", 1.0, "eod")],
        )


def test_the_calendar_is_overwritten_whole():
    client, fake = _client()
    client.overwrite_unpartitioned(DIM_DATE, [(date(2024, 1, 1),) + (1,) * 8])
    assert "WHERE TRUE" in fake.query.call_args.args[0]
    with pytest.raises(WarehouseError):
        client.overwrite_unpartitioned(FACT_PRICE_DAILY, [])
    with pytest.raises(WarehouseError):
        client.delete_partitions(DIM_DATE, 1, 2, "INT64")


def test_replace_file_loads_a_prewritten_file(tmp_path):
    client, _ = _client()
    path = tmp_path / "x.csv.gz"
    write_csv_gz(path, FACT_PRICE_DAILY.column_names, [])
    assert (
        client.replace_file(FACT_PRICE_DAILY, date(2024, 1, 2), date(2024, 1, 3), path, "DATE") == 2
    )


def test_run_script_is_a_capped_query():
    client, fake = _client()
    client.run_script("DELETE x; INSERT y", [], max_bytes=GB)
    assert fake.query.call_args.kwargs["job_config"].maximum_bytes_billed == GB


def test_csv_formatting(tmp_path):
    path = tmp_path / "rows.csv.gz"
    count = write_csv_gz(
        path,
        ["a", "b", "c", "d", "e"],
        [
            (None, True, date(2024, 1, 2), datetime(2024, 1, 2, 3, 4, tzinfo=UTC), 0.1),
            ("x,y", False, 1, 2, 3),
        ],
    )
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert count == 2
    assert rows[1] == ["", "true", "2024-01-02", "2024-01-02T03:04:00+00:00", "0.1"]
    assert rows[2][0] == "x,y"


def test_the_real_client_is_built_lazily(monkeypatch):
    built = MagicMock()
    monkeypatch.setattr(bigquery, "Client", built)
    WarehouseClient("proj")
    built.assert_called_once_with(project="proj", location="us-central1")
