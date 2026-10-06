"""The one door to BigQuery (MM-139). Cost guardrails live here, so no caller
can skip them:

- Every query sets `maximum_bytes_billed` (a per-call cap, itself capped by
  QUERY_CEILING_BYTES). A query that would scan more fails before it runs.
- Writes are batch load jobs from local gzip CSV (free); there is no
  streaming-insert method at all.
- Replacing data is "DELETE whole partitions, then load": the DELETE filters
  on the partition column only, which BigQuery executes as a metadata
  operation (0 bytes), and the load appends. Re-running replaces, never
  duplicates. Loads never use WRITE_TRUNCATE, which would also drop the
  tables' row access policies.

The google-cloud-bigquery import is lazy so the app imports without it when
WAREHOUSE=none.
"""

import csv
import gzip
import os
import tempfile
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import structlog

from warehouse.schemas import DATASET, LOCATION, Table

logger = structlog.get_logger()

MB = 1024**2
GB = 1024**3
# No single query may be allowed more than this, whatever the caller asks.
QUERY_CEILING_BYTES = 8 * GB
# A whole-partition DELETE scans 0 bytes; the cap only bounds a mistake.
DELETE_CAP_BYTES = 50 * MB


class WarehouseError(RuntimeError):
    """A BigQuery job failed or a guardrail refused it."""


@dataclass(frozen=True)
class QueryParam:
    name: str
    type: str  # STRING | DATE | INT64 | FLOAT64 | BOOL
    value: Any
    array: bool = False


def _format(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return repr(value)
    return str(value)


def write_csv_gz(path: Path, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
    """Streams rows to a gzip CSV (header + rows); returns the row count."""
    count = 0
    with gzip.open(path, "wt", encoding="utf-8", newline="", compresslevel=6) as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_format(v) for v in row])
            count += 1
    return count


@contextmanager
def staging_file(table: Table) -> Iterator[Path]:
    """A temporary gzip CSV for one load, deleted afterwards. The name is
    fixed by the table, never taken from user input."""
    handle, name = tempfile.mkstemp(prefix=f"mm-{table.name}-", suffix=".csv.gz")
    os.close(handle)
    path = Path(name)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


class WarehouseClient:
    def __init__(self, project: str, dataset: str = DATASET, client: Any = None) -> None:
        if client is None:
            from google.cloud import bigquery

            client = bigquery.Client(project=project, location=LOCATION)
        self._client = client
        self.project = project
        self.dataset = dataset

    def table_ref(self, table: Table | str) -> str:
        name = table.name if isinstance(table, Table) else table
        return f"{self.project}.{self.dataset}.{name}"

    # --- queries -------------------------------------------------------------

    def _job_config(self, params: Sequence[QueryParam], max_bytes: int, dry_run: bool) -> Any:
        from google.cloud import bigquery

        query_params: list[Any] = []
        for p in params:
            if p.array:
                query_params.append(bigquery.ArrayQueryParameter(p.name, p.type, list(p.value)))
            else:
                query_params.append(bigquery.ScalarQueryParameter(p.name, p.type, p.value))
        return bigquery.QueryJobConfig(
            query_parameters=query_params,
            maximum_bytes_billed=max_bytes,
            dry_run=dry_run,
            use_query_cache=not dry_run,
            default_dataset=f"{self.project}.{self.dataset}",
        )

    @staticmethod
    def _check_cap(max_bytes: int) -> None:
        if max_bytes <= 0 or max_bytes > QUERY_CEILING_BYTES:
            raise WarehouseError(
                f"maximum_bytes_billed must be in (0, {QUERY_CEILING_BYTES}]; got {max_bytes}"
            )

    def query(
        self, sql: str, params: Sequence[QueryParam] = (), *, max_bytes: int
    ) -> list[dict[str, Any]]:
        """Runs a query with a hard bytes cap and returns its rows."""
        self._check_cap(max_bytes)
        job = self._client.query(sql, job_config=self._job_config(params, max_bytes, False))
        try:
            rows = job.result()
        except Exception as exc:
            raise WarehouseError(f"query failed: {exc}") from exc
        logger.info(
            "warehouse_query",
            bytes_billed=getattr(job, "total_bytes_billed", None),
            max_bytes=max_bytes,
        )
        return [dict(row.items()) for row in rows]

    def estimate_bytes(self, sql: str, params: Sequence[QueryParam] = ()) -> int:
        """Dry run: bytes the query would process (free, nothing runs)."""
        job = self._client.query(
            sql, job_config=self._job_config(params, QUERY_CEILING_BYTES, True)
        )
        return int(job.total_bytes_processed or 0)

    # --- loads -----------------------------------------------------------------

    def _load(self, table: Table, path: Path) -> int:
        from google.cloud import bigquery

        config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=1,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
            schema=[bigquery.SchemaField.from_api_repr(f) for f in table.bq_schema()],
            allow_quoted_newlines=True,
        )
        with path.open("rb") as handle:
            job = self._client.load_table_from_file(
                handle, self.table_ref(table), job_config=config, rewind=True
            )
        try:
            job.result()
        except Exception as exc:
            raise WarehouseError(f"load into {table.name} failed: {exc}") from exc
        return int(job.output_rows or 0)

    def delete_partitions(self, table: Table, start: Any, end: Any, param_type: str) -> None:
        """DELETE rows whose partition column is in [start, end]. Callers pass
        whole partitions only, so BigQuery drops them without scanning."""
        if table.partition_column is None:
            raise WarehouseError(f"{table.name} is not partitioned")
        sql = (
            f"DELETE FROM `{self.table_ref(table)}` "
            f"WHERE {table.partition_column} BETWEEN @start AND @end"
        )
        self.query(
            sql,
            [QueryParam("start", param_type, start), QueryParam("end", param_type, end)],
            max_bytes=DELETE_CAP_BYTES,
        )

    def replace(
        self,
        table: Table,
        start: Any,
        end: Any,
        rows: Iterable[Sequence[Any]],
        param_type: str = "DATE",
    ) -> int:
        """Idempotent write of one slice: drop its partitions, load the rows."""
        with staging_file(table) as path:
            count = write_csv_gz(path, table.column_names, rows)
            self.delete_partitions(table, start, end, param_type)
            loaded = self._load(table, path) if count else 0
        logger.info(
            "warehouse_replace", table=table.name, start=str(start), end=str(end), rows=loaded
        )
        return loaded

    def replace_file(self, table: Table, start: Any, end: Any, path: Path, param_type: str) -> int:
        """Same as replace(), for a gzip CSV the caller already wrote."""
        self.delete_partitions(table, start, end, param_type)
        return self._load(table, path)

    def overwrite_unpartitioned(self, table: Table, rows: Iterable[Sequence[Any]]) -> int:
        """For dim_date only (no book, no row access policies): delete all,
        then load. The DELETE scans one tiny table."""
        if table.partition_column is not None:
            raise WarehouseError(f"{table.name} is partitioned; use replace()")
        with staging_file(table) as path:
            count = write_csv_gz(path, table.column_names, rows)
            self.query(
                f"DELETE FROM `{self.table_ref(table)}` WHERE TRUE", max_bytes=DELETE_CAP_BYTES
            )
            return self._load(table, path) if count else 0

    def run_script(self, sql: str, params: Sequence[QueryParam], *, max_bytes: int) -> None:
        """A multi-statement refresh script (DELETE + INSERT ... SELECT)."""
        self.query(sql, params, max_bytes=max_bytes)
