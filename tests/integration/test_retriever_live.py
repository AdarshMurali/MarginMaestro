"""Real retrieval against the live ChromaDB collection (populated by MM-24's
ingestion) and real OpenAI query embeddings. Excluded from the default/CI
run -- see the `live` marker in pyproject.toml. Run `make ingest-docs` first
if the collection is empty.
"""

import pytest

from rag.retriever import retrieve

pytestmark = pytest.mark.live


def test_counterparty_scoped_query_returns_that_counterpartys_threshold() -> None:
    results = retrieve("what is CP-3's threshold?", counterparty_id="CP-3", top_k=3)

    assert results
    assert results[0].counterparty_id == "CP-3"
    assert results[0].doc_type == "csa"
    assert "90,000" in results[0].text or results[0].section == "Threshold"


def test_counterparty_filter_never_leaks_another_counterpartys_csa() -> None:
    results = retrieve(
        "threshold and minimum transfer amount", counterparty_id="CP-3", doc_type="csa", top_k=10
    )

    assert results
    assert {r.counterparty_id for r in results} <= {"CP-3"}
