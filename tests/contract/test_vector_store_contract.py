"""VectorStore contract (MM-102): every adapter must pass these. Chroma needs a
running server (docker compose), so it's marked `live`. pgvector (MM-110) needs
a migrated Postgres: it runs in CI's `migrations` job (REQUIRE_DB=1) against a
throwaway table cloned from rag_chunks, and skips elsewhere.

Vectors are 768-dimensional (padded with zeros) so every store -- including
pgvector's fixed vector(768) column -- takes the same input."""

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from adapters.chroma_adapter import ChromaVectorStore
from adapters.in_memory import InMemoryVectorStore
from config.settings import Settings


def _chroma():
    from rag.ingest import get_chroma_client

    client = get_chroma_client(Settings(_env_file=None))
    name = f"contract-{uuid.uuid4().hex[:8]}"
    yield ChromaVectorStore(client, name)
    client.delete_collection(name)


def _in_memory():
    yield InMemoryVectorStore()


def _pgvector():
    from adapters.pgvector_adapter import PgVectorStore, rag_table
    from persistence.db.engine import db_dialect, get_engine, get_session_factory

    settings = Settings()
    if db_dialect(settings) != "postgres":
        pytest.skip("pgvector contract needs DB_DIALECT=postgres")
    # DDL on a plain engine connection (the migrating user): ORM sessions run
    # as the restricted mm_app role, which can't create tables (MM-106). The
    # store's own reads/writes still go through mm_app sessions.
    engine = get_engine(settings)
    name = f"contract_rag_{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as conn:
            # Same columns, types and indexes as the migrated rag_chunks; no RLS
            # (policies aren't copied), so the contract sees only its own rows.
            conn.execute(text(f"CREATE TABLE {name} (LIKE rag_chunks INCLUDING ALL)"))
            conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO mm_app"))
    except DBAPIError as exc:
        if os.environ.get("REQUIRE_DB") == "1":
            raise
        pytest.skip(f"No migrated Postgres reachable: {exc}")
    yield PgVectorStore(get_session_factory(settings), table=rag_table(name))
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
    engine.dispose()


@pytest.fixture(
    params=[
        pytest.param(_in_memory, id="in-memory"),
        pytest.param(_chroma, id="chroma", marks=pytest.mark.live),
        pytest.param(_pgvector, id="pgvector"),
    ]
)
def store(request):
    yield from request.param()


DIM = 768


def _v(x: float, y: float) -> list[float]:
    return [x, y] + [0.0] * (DIM - 2)


def _meta(counterparty_id: str, doc_type: str) -> dict[str, str]:
    return {"counterparty_id": counterparty_id, "doc_type": doc_type, "source_file": "f.md"}


@pytest.fixture
def seeded(store):
    store.upsert(
        ids=["cp3-csa", "cp4-csa", "policy", "cp3-dispute"],
        embeddings=[_v(1.0, 0.0), _v(0.9, 0.1), _v(0.0, 1.0), _v(0.8, 0.2)],
        documents=["CP-3 CSA", "CP-4 CSA", "Margin policy", "CP-3 dispute"],
        metadatas=[
            _meta("CP-3", "csa"),
            _meta("CP-4", "csa"),
            _meta("", "policy"),
            _meta("CP-3", "disputes"),
        ],
    )
    return store


def test_results_are_nearest_first_and_capped_at_top_k(seeded):
    hits = seeded.query(_v(1.0, 0.0), top_k=2)

    assert [hit.text for hit in hits] == ["CP-3 CSA", "CP-4 CSA"]
    assert hits[0].distance <= hits[1].distance


def test_counterparty_filter_includes_shared_docs_but_not_other_counterparties(seeded):
    texts = {hit.text for hit in seeded.query(_v(1.0, 0.0), top_k=10, counterparty_id="CP-3")}

    assert texts == {"CP-3 CSA", "CP-3 dispute", "Margin policy"}


def test_doc_type_filter_is_exact(seeded):
    hits = seeded.query(_v(1.0, 0.0), top_k=10, doc_type="csa")

    assert {hit.text for hit in hits} == {"CP-3 CSA", "CP-4 CSA"}


def test_filters_combine(seeded):
    hits = seeded.query(_v(1.0, 0.0), top_k=10, counterparty_id="CP-3", doc_type="csa")

    assert [hit.text for hit in hits] == ["CP-3 CSA"]


def test_metadata_round_trips(seeded):
    hit = seeded.query(_v(0.0, 1.0), top_k=1)[0]

    assert hit.text == "Margin policy"
    assert hit.metadata == _meta("", "policy")


def test_upsert_is_idempotent_by_id(seeded):
    seeded.upsert(
        ids=["cp3-csa"],
        embeddings=[_v(1.0, 0.0)],
        documents=["CP-3 CSA v2"],
        metadatas=[_meta("CP-3", "csa")],
    )

    hits = seeded.query(_v(1.0, 0.0), top_k=10, doc_type="csa")

    assert sorted(hit.text for hit in hits) == ["CP-3 CSA v2", "CP-4 CSA"]
