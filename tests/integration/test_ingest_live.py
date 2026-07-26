"""Real end-to-end ingestion: real S3 corpus, real OpenAI embeddings, real
ChromaDB (docker compose up -d chroma). Excluded from the default/CI run --
see the `live` marker in pyproject.toml.
"""

import pytest

from rag.ingest import COLLECTION_NAME, get_chroma_client, run_ingestion

pytestmark = pytest.mark.live


def test_run_ingestion_populates_chroma_with_citable_chunks() -> None:
    count = run_ingestion()
    assert count > 0

    client = get_chroma_client()
    collection = client.get_collection(COLLECTION_NAME)
    assert collection.count() == count

    result = collection.get(where={"counterparty_id": "CP-1"}, include=["metadatas"])
    sections = {m["section"] for m in result["metadatas"]}
    assert "Threshold" in sections
    assert "Minimum Transfer Amount" in sections
    assert all(m["source_file"] == "csa/CP-1.md" for m in result["metadatas"])


def test_run_ingestion_is_idempotent() -> None:
    first_count = run_ingestion()
    second_count = run_ingestion()

    client = get_chroma_client()
    collection = client.get_collection(COLLECTION_NAME)

    assert first_count == second_count
    assert collection.count() == first_count
