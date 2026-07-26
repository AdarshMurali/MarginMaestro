"""Real end-to-end CSA-RAG extraction: real retrieval (ChromaDB populated by
MM-24's ingestion) and a real OpenAI gpt-4o-mini call. Excluded from the
default/CI run -- see the `live` marker in pyproject.toml. Run
`make ingest-docs` first if the collection is empty.
"""

import pytest

from agents.csa_rag import answer_csa_terms

pytestmark = pytest.mark.live

# Ground truth for seed=42's CP-1 (verified by reading data/documents/csa/CP-1.md
# directly): threshold USD 340,000, MTA USD 11,000.
CP1_THRESHOLD = 340000.0
CP1_MTA = 11000.0


def test_extracts_correct_threshold_and_mta_for_a_known_counterparty() -> None:
    result = answer_csa_terms("CP-1")

    assert result.threshold == CP1_THRESHOLD
    assert result.mta == CP1_MTA
    assert result.currency == "USD"


def test_haircuts_are_decimal_fractions_not_percentages() -> None:
    result = answer_csa_terms("CP-1")

    # Every haircut must be a small fraction (<=1.0), never a raw percentage
    # number like 8 -- this is the exact bug found during manual verification.
    assert result.haircuts
    assert all(0 <= value <= 1 for value in result.haircuts.values())


def test_citations_point_to_that_counterpartys_own_csa_document() -> None:
    result = answer_csa_terms("CP-1")

    assert result.citations
    assert all(c.source_file == "csa/CP-1.md" for c in result.citations)
