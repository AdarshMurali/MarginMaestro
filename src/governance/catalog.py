"""The data catalog (MM-135, ADR-0015): `docs/data_catalog.yaml`, validated.

The YAML is the single source of truth. Terraform registers it in Dataplex
Universal Catalog (infra/gcp/dataplex.tf) and the LLM data-class filter
(governance.classification) is driven by it, so both always agree. Its
`warehouse_tables` (MM-139) also drive the BigQuery policy tags
(infra/gcp/bigquery.tf): every confidential column there is masked.

Where the file is found, in order:
1. `DATA_CATALOG_PATH` (the Docker image sets it: /app/docs/data_catalog.yaml);
2. `docs/data_catalog.yaml` in the checkout this module runs from.
A missing or invalid catalog raises: a filter that can't read its rules must
not let text through unfiltered.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DataClass = Literal["public", "internal", "confidential"]
LlmHandling = Literal["pseudonymize", "mask", "deny"]
CLASS_ORDER: dict[str, int] = {"public": 0, "internal": 1, "confidential": 2}
CATALOG_ENV = "DATA_CATALOG_PATH"


class CatalogError(ValueError):
    """The catalog is missing, unreadable or breaks one of its own rules."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ColumnEntry(_Strict):
    class_: DataClass = Field(alias="class")
    llm: LlmHandling | None = None
    pseudonym: str | None = None
    contains: list[str] = Field(default_factory=list)
    pattern: str | None = None

    @model_validator(mode="after")
    def _confidential_needs_handling(self) -> "ColumnEntry":
        if self.class_ == "confidential" and self.llm is None:
            raise ValueError("a confidential column must declare its `llm` handling")
        if self.class_ != "confidential" and self.llm is not None:
            raise ValueError("only confidential columns take an `llm` handling")
        if self.llm == "pseudonymize" and not (self.pseudonym or self.contains):
            raise ValueError("`pseudonymize` needs a `pseudonym` column or `contains`")
        return self


class TableEntry(_Strict):
    owner: str
    description: str
    class_: DataClass = Field(alias="class")
    freshness: str
    source: str
    migration_only: bool = False
    columns: dict[str, ColumnEntry]

    @model_validator(mode="after")
    def _class_covers_columns(self) -> "TableEntry":
        highest = max(CLASS_ORDER[c.class_] for c in self.columns.values())
        if CLASS_ORDER[self.class_] < highest:
            raise ValueError(f"class {self.class_!r} is lower than one of its columns")
        return self


class DocumentFamily(_Strict):
    owner: str
    description: str
    class_: DataClass = Field(alias="class")
    freshness: str
    source: str
    contains: list[str] = Field(default_factory=list)


class LlmException(_Strict):
    path: str
    fields: list[str]
    exposes: str
    reason: str


class DataCatalog(_Strict):
    version: int
    tables: dict[str, TableEntry]
    documents: dict[str, DocumentFamily]
    # MM-139: BigQuery warehouse tables (dataset marginmaestro_analytics).
    # Kept apart from `tables` (Cloud SQL): the LLM data-class filter reads
    # `tables` only, and no warehouse data is ever sent to a model.
    warehouse_tables: dict[str, TableEntry] = Field(default_factory=dict)
    llm_exceptions: list[LlmException] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references_resolve(self) -> "DataCatalog":
        for table_name, table in {**self.tables, **self.warehouse_tables}.items():
            self._check_table_references(table_name, table)
        for family_name, family in self.documents.items():
            for ref in family.contains:
                self._pseudonymized(ref, f"documents.{family_name}")
        for exception in self.llm_exceptions:
            for ref in exception.fields:
                self.column(ref)
        return self

    def _check_table_references(self, table_name: str, table: TableEntry) -> None:
        for column_name, column in table.columns.items():
            if column.pseudonym and column.pseudonym not in table.columns:
                raise ValueError(
                    f"{table_name}.{column_name}: pseudonym column {column.pseudonym!r} "
                    "is not in the table"
                )
            for ref in column.contains:
                self._pseudonymized(ref, f"{table_name}.{column_name}")

    def column(self, ref: str) -> ColumnEntry:
        """`table.column` -> its entry; unknown references raise."""
        table_name, _, column_name = ref.partition(".")
        try:
            return self.tables[table_name].columns[column_name]
        except KeyError:
            raise CatalogError(f"unknown catalog column {ref!r}") from None

    def _pseudonymized(self, ref: str, where: str) -> None:
        if self.column(ref).pseudonym is None:
            raise CatalogError(f"{where} contains {ref!r}, which has no pseudonym")

    def columns_with(self, handling: LlmHandling) -> list[tuple[str, str, ColumnEntry]]:
        """(table, column, entry) for every column with that `llm` handling."""
        return [
            (table_name, column_name, column)
            for table_name, table in self.tables.items()
            for column_name, column in table.columns.items()
            if column.llm == handling
        ]


def default_catalog_path() -> Path:
    explicit = os.environ.get(CATALOG_ENV)
    if explicit:
        return Path(explicit)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "docs" / "data_catalog.yaml"
        if candidate.is_file():
            return candidate
    raise CatalogError(f"docs/data_catalog.yaml not found; set {CATALOG_ENV}")


def parse_catalog(text: str) -> DataCatalog:
    try:
        return DataCatalog.model_validate(yaml.safe_load(text))
    except (yaml.YAMLError, ValueError) as exc:
        raise CatalogError(f"invalid data catalog: {exc}") from exc


def load_catalog(path: Path | None = None) -> DataCatalog:
    path = path or default_catalog_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogError(f"cannot read the data catalog at {path}: {exc}") from exc
    return parse_catalog(text)


@lru_cache
def get_catalog() -> DataCatalog:
    return load_catalog()
