"""VectorStore contract (MM-102): every adapter must pass these. pgvector joins
the parameter list in G1. Chroma needs a running server (docker compose), so
it's marked `live` and excluded from CI like the other server-backed tests."""

import uuid

import pytest

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


@pytest.fixture(
    params=[
        pytest.param(_in_memory, id="in-memory"),
        pytest.param(_chroma, id="chroma", marks=pytest.mark.live),
    ]
)
def store(request):
    yield from request.param()


def _meta(counterparty_id: str, doc_type: str) -> dict[str, str]:
    return {"counterparty_id": counterparty_id, "doc_type": doc_type, "source_file": "f.md"}


@pytest.fixture
def seeded(store):
    store.upsert(
        ids=["cp3-csa", "cp4-csa", "policy", "cp3-dispute"],
        embeddings=[[1.0, 0.0], [0.9, 0.1], [0.0, 1.0], [0.8, 0.2]],
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
    hits = seeded.query([1.0, 0.0], top_k=2)

    assert [hit.text for hit in hits] == ["CP-3 CSA", "CP-4 CSA"]
    assert hits[0].distance <= hits[1].distance


def test_counterparty_filter_includes_shared_docs_but_not_other_counterparties(seeded):
    texts = {hit.text for hit in seeded.query([1.0, 0.0], top_k=10, counterparty_id="CP-3")}

    assert texts == {"CP-3 CSA", "CP-3 dispute", "Margin policy"}


def test_doc_type_filter_is_exact(seeded):
    hits = seeded.query([1.0, 0.0], top_k=10, doc_type="csa")

    assert {hit.text for hit in hits} == {"CP-3 CSA", "CP-4 CSA"}


def test_filters_combine(seeded):
    hits = seeded.query([1.0, 0.0], top_k=10, counterparty_id="CP-3", doc_type="csa")

    assert [hit.text for hit in hits] == ["CP-3 CSA"]


def test_metadata_round_trips(seeded):
    hit = seeded.query([0.0, 1.0], top_k=1)[0]

    assert hit.text == "Margin policy"
    assert hit.metadata == _meta("", "policy")


def test_upsert_is_idempotent_by_id(seeded):
    seeded.upsert(
        ids=["cp3-csa"],
        embeddings=[[1.0, 0.0]],
        documents=["CP-3 CSA v2"],
        metadatas=[_meta("CP-3", "csa")],
    )

    hits = seeded.query([1.0, 0.0], top_k=10, doc_type="csa")

    assert sorted(hit.text for hit in hits) == ["CP-3 CSA v2", "CP-4 CSA"]
