"""Seeded retrieval-precision suite (MM-27): for each of the 8 counterparties,
a canned question retrieves that counterparty's own CSA chunk -- not another's
-- with citation metadata present. Proves Phase 3's exit criteria end-to-end.
Real ChromaDB + real OpenAI query embeddings; excluded from CI (`live` marker,
per pyproject.toml). Run `make ingest-docs` first if the collection is empty.

Ground-truth threshold figures below are read directly from
`data/documents/csa/CP-*.md`, not guessed.
"""

import pytest

from rag.retriever import retrieve

pytestmark = pytest.mark.live

# counterparty_id -> threshold USD, from data/documents/csa/CP-*.md
_GROUND_TRUTH: dict[str, str] = {
    "CP-1": "340,000",
    "CP-2": "95,000",
    "CP-3": "90,000",
    "CP-4": "365,000",
    "CP-5": "240,000",
    "CP-6": "220,000",
    "CP-7": "105,000",
    "CP-8": "450,000",
}


@pytest.mark.parametrize("counterparty_id,threshold", list(_GROUND_TRUTH.items()))
def test_threshold_question_retrieves_that_counterpartys_own_chunk(
    counterparty_id: str, threshold: str
) -> None:
    # doc_type="csa" matches how the CSA-RAG agent actually calls retrieve()
    # (agents/csa_rag.py) -- without it, the shared margin-policy doc's
    # "General Threshold Policy" section can narrowly outrank a counterparty's
    # own Threshold chunk for 2/8 counterparties (close embedding distances,
    # e.g. CP-4: 1.193 vs 1.2486), since that policy section's prose also
    # repeats "threshold"/"MTA"/"counterparty" generically.
    results = retrieve(
        f"what is {counterparty_id}'s threshold?",
        counterparty_id=counterparty_id,
        doc_type="csa",
        top_k=3,
    )

    assert results
    top = results[0]
    assert top.counterparty_id == counterparty_id
    assert top.doc_type == "csa"
    assert threshold in top.text or top.section == "Threshold"


@pytest.mark.parametrize("counterparty_id", list(_GROUND_TRUTH))
def test_broad_csa_query_never_leaks_another_counterpartys_chunks(counterparty_id: str) -> None:
    results = retrieve(
        "threshold and minimum transfer amount",
        counterparty_id=counterparty_id,
        doc_type="csa",
        top_k=10,
    )

    assert results
    assert {r.counterparty_id for r in results} <= {counterparty_id}


@pytest.mark.parametrize("counterparty_id", list(_GROUND_TRUTH))
def test_citations_present_for_every_retrieved_chunk(counterparty_id: str) -> None:
    results = retrieve(
        f"what are {counterparty_id}'s CSA terms?",
        counterparty_id=counterparty_id,
        doc_type="csa",
        top_k=5,
    )

    assert results
    for chunk in results:
        assert chunk.source_file
        assert chunk.section
