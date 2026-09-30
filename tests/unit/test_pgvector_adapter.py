"""MM-110: PgVectorStore's SQL, checked without a database (the behaviour
against real Postgres is covered by the pgvector VectorStore contract in
CI's migrations job)."""

import re
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from adapters.pgvector_adapter import PgVectorStore, rag_table


def _store():
    session = MagicMock()
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    return PgVectorStore(factory), session


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_table_shape():
    table = rag_table()

    assert table.name == "rag_chunks"
    assert [c.name for c in table.columns] == [
        "id",
        "counterparty_id",
        "doc_type",
        "text",
        "metadata",
        "embedding",
    ]
    assert table.c.embedding.type.dim == 768


def test_upsert_is_insert_on_conflict_update_and_commits():
    store, session = _store()

    store.upsert(
        ids=["csa/CP-1.md#0"],
        embeddings=[[0.1] * 768],
        documents=["Threshold USD 340,000"],
        metadatas=[{"counterparty_id": "CP-1", "doc_type": "csa", "source_file": "csa/CP-1.md"}],
    )

    statement = session.execute.call_args.args[0]
    sql = _sql(statement)
    assert "INSERT INTO rag_chunks" in sql
    assert "ON CONFLICT (id) DO UPDATE SET" in sql
    for column in ("counterparty_id", "doc_type", "text", "metadata", "embedding"):
        assert f"{column} = excluded.{column}" in sql
    session.commit.assert_called_once()


def test_upsert_maps_filter_columns_from_metadata():
    store, session = _store()

    store.upsert(
        ids=["policy/margin_policy.md#0"],
        embeddings=[[0.0] * 768],
        documents=["policy"],
        metadatas=[{"doc_type": "policy", "source_file": "policy/margin_policy.md"}],
    )

    params = session.execute.call_args.args[0].compile(dialect=postgresql.dialect()).params
    assert params["counterparty_id_m0"] == ""  # shared document
    assert params["doc_type_m0"] == "policy"
    assert params["metadata_m0"] == {"doc_type": "policy", "source_file": "policy/margin_policy.md"}


def test_upsert_of_nothing_touches_no_database():
    store, session = _store()

    store.upsert(ids=[], embeddings=[], documents=[], metadatas=[])

    session.execute.assert_not_called()


def test_query_orders_by_cosine_distance_with_shared_docs_and_doc_type_filters():
    store, session = _store()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            text="CP-6 threshold", metadata={"source_file": "csa/CP-6.md"}, distance=0.12
        )
    ]

    hits = store.query([0.2] * 768, top_k=3, counterparty_id="CP-6", doc_type="csa")

    sql = _sql(session.execute.call_args.args[0])
    # Patterns, not exact strings: newer SQLAlchemy adds casts like ::VARCHAR.
    assert "embedding <=>" in sql  # pgvector cosine distance
    assert re.search(
        r"rag_chunks\.counterparty_id = %\(counterparty_id_1\)s(::\w+)?\)? OR "
        r"\(?rag_chunks\.counterparty_id = %\(counterparty_id_2\)s",
        sql,
    )
    assert re.search(r"rag_chunks\.doc_type = %\(doc_type_1\)s", sql)
    assert "ORDER BY distance" in sql
    assert re.search(r"LIMIT %\(param_1\)s", sql)
    assert hits[0].text == "CP-6 threshold"
    assert hits[0].metadata == {"source_file": "csa/CP-6.md"}
    assert hits[0].distance == 0.12


def test_query_without_filters_has_no_where_clause():
    store, session = _store()
    session.execute.return_value.all.return_value = []

    assert store.query([0.0] * 768, top_k=5) == []
    assert "WHERE" not in _sql(session.execute.call_args.args[0])


def test_custom_table_is_used():
    session = MagicMock()
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    session.execute.return_value.all.return_value = []

    PgVectorStore(factory, table=rag_table("contract_rag_x")).query([0.0] * 768, top_k=1)

    assert "FROM contract_rag_x" in _sql(session.execute.call_args.args[0])
