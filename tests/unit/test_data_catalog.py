"""MM-135: docs/data_catalog.yaml stays in sync with the code, and its own
classification rules hold. A new table, column or document family that isn't
catalogued fails here -- so it can't reach Dataplex or the LLM unclassified."""

import re
from pathlib import Path

import pytest

from governance import catalog as catalog_module
from governance.catalog import (
    CatalogError,
    DataCatalog,
    default_catalog_path,
    get_catalog,
    load_catalog,
    parse_catalog,
)
from persistence.db.models import Base

ROOT = Path(__file__).resolve().parents[2]
CATALOG = load_catalog(ROOT / "docs" / "data_catalog.yaml")
RAG_MIGRATION = ROOT / "migrations" / "versions" / "d4e1b9c2a7f5_rag_chunks_pgvector.py"


def _migration_only_columns(path: Path, table: str) -> set[str]:
    body = re.search(rf"CREATE TABLE {table} \((.*?)\n\s*\)", path.read_text(), re.DOTALL)
    assert body, f"CREATE TABLE {table} not found in {path.name}"
    return {line.split()[0] for line in body.group(1).strip().splitlines() if line.strip()}


# --- in sync with the code -------------------------------------------------------


def test_every_model_table_is_catalogued():
    model_tables = set(Base.metadata.tables)
    migration_only = {name for name, t in CATALOG.tables.items() if t.migration_only}
    assert set(CATALOG.tables) - migration_only == model_tables


@pytest.mark.parametrize("table", sorted(Base.metadata.tables))
def test_every_model_column_is_classified(table):
    model_columns = {column.name for column in Base.metadata.tables[table].columns}
    assert set(CATALOG.tables[table].columns) == model_columns


def test_migration_only_rag_chunks_columns_are_classified():
    assert CATALOG.tables["rag_chunks"].migration_only
    assert set(CATALOG.tables["rag_chunks"].columns) == _migration_only_columns(
        RAG_MIGRATION, "rag_chunks"
    )


def test_every_document_family_is_catalogued():
    families = {p.name for p in (ROOT / "data" / "documents").iterdir() if p.is_dir()}
    assert set(CATALOG.documents) == families


# --- classification rules ------------------------------------------------------


def test_adr_0015_confidential_data_is_classified_confidential():
    """Counterparty identity, exposures and collateral (ADR-0015)."""
    for ref in (
        "counterparties.name",
        "positions.quantity",
        "collateral_items.value_usd",
        "orchestrator_checkpoints.checkpoint_blob",
        "users.password_hash",
        "audit_log.payload",
    ):
        assert CATALOG.column(ref).class_ == "confidential", ref


def test_market_data_is_public():
    for table in ("price_history", "latest_prices", "reference_rates"):
        assert CATALOG.tables[table].class_ == "public"


def test_every_confidential_column_declares_how_the_llm_layer_handles_it():
    for table_name, table in CATALOG.tables.items():
        for column_name, column in table.columns.items():
            if column.class_ == "confidential":
                assert column.llm in ("pseudonymize", "mask", "deny"), (table_name, column_name)


def test_the_documents_that_name_counterparties_are_confidential():
    for family in CATALOG.documents.values():
        if family.contains:
            assert family.class_ == "confidential"


def test_llm_exceptions_are_explicit_and_few():
    assert [e.path for e in CATALOG.llm_exceptions] == ["desk_assistant.margin_status"]


def test_every_owner_and_freshness_is_set():
    entries = [*CATALOG.tables.values(), *CATALOG.documents.values()]
    assert all(e.owner and e.freshness and e.source and e.description for e in entries)


def test_dataplex_label_values_are_valid():
    """Terraform puts owner and class into Dataplex labels: lowercase,
    digits, '-' and '_' only, at most 63 characters."""
    label = re.compile(r"^[a-z0-9_-]{1,63}$")
    for entry in [*CATALOG.tables.values(), *CATALOG.documents.values()]:
        assert label.match(entry.owner) and label.match(entry.class_)


# --- validation -------------------------------------------------------------------

_MINIMAL = """
version: 1
tables:
  t:
    owner: o
    description: d
    class: {table_class}
    freshness: f
    source: s
    columns:
      id: {{class: internal}}
      secret: {column}
documents: {{}}
"""


@pytest.mark.parametrize(
    ("table_class", "column", "error"),
    [
        ("confidential", "{class: confidential}", "must declare its `llm`"),
        ("internal", "{class: internal, llm: mask}", "only confidential columns"),
        ("internal", "{class: confidential, llm: mask}", "lower than one of its columns"),
        ("confidential", "{class: confidential, llm: pseudonymize}", "needs a `pseudonym`"),
        ("confidential", "{class: confidential, llm: pseudonymize, pseudonym: nope}", "not in"),
        ("confidential", "{class: secret}", "class"),
        ("confidential", "{class: confidential, llm: deny, colour: red}", "colour"),
    ],
)
def test_catalog_rules_are_enforced(table_class, column, error):
    with pytest.raises(CatalogError, match=re.escape(error)):
        parse_catalog(_MINIMAL.format(table_class=table_class, column=column))


def test_references_to_unknown_or_unpseudonymized_columns_fail():
    base = _MINIMAL.format(table_class="internal", column="{class: internal}")
    with pytest.raises(CatalogError, match="unknown catalog column"):
        parse_catalog(
            base.replace(
                "documents: {}",
                "documents: {d: {owner: o, description: d, class: internal, freshness: f, source: s, contains: [t.nope]}}",
            )
        )
    with pytest.raises(CatalogError, match="has no pseudonym"):
        parse_catalog(
            base.replace(
                "documents: {}",
                "documents: {d: {owner: o, description: d, class: internal, freshness: f, source: s, contains: [t.id]}}",
            )
        )


def test_unreadable_or_malformed_catalog_fails_loud(tmp_path):
    with pytest.raises(CatalogError, match="cannot read"):
        load_catalog(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: [", encoding="utf-8")
    with pytest.raises(CatalogError, match="invalid data catalog"):
        load_catalog(bad)


def test_catalog_path_comes_from_the_env_first(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_CATALOG_PATH", str(tmp_path / "c.yaml"))
    assert default_catalog_path() == tmp_path / "c.yaml"
    monkeypatch.delenv("DATA_CATALOG_PATH")
    assert default_catalog_path() == ROOT / "docs" / "data_catalog.yaml"


def test_missing_catalog_without_env_fails_loud(monkeypatch, tmp_path):
    monkeypatch.delenv("DATA_CATALOG_PATH", raising=False)
    monkeypatch.setattr(catalog_module, "__file__", str(tmp_path / "x" / "catalog.py"))
    with pytest.raises(CatalogError, match="not found"):
        default_catalog_path()


def test_get_catalog_is_the_repo_catalog():
    get_catalog.cache_clear()
    assert isinstance(get_catalog(), DataCatalog)
    assert get_catalog().tables.keys() == CATALOG.tables.keys()
