from unittest.mock import MagicMock, patch

from config.settings import Settings
from rag.ingest import (
    EMBEDDING_MODEL,
    _metadata_from_key,
    embed_texts,
    get_chroma_client,
    main,
    run_ingestion,
)

SAMPLE_CSA = """# Credit Support Annex — Rodriguez Partners (CP-1)

Effective date: 2026-07-26

## Threshold

The Threshold applicable to Rodriguez Partners is USD 340,000.
"""

SAMPLE_POLICY = """# MarginMaestro — Internal Margin Call Policy

## Valuation Timing

Portfolios are revalued whenever a qualifying market event occurs.
"""


class TestMetadataFromKey:
    def test_csa_document_extracts_counterparty_id(self) -> None:
        assert _metadata_from_key("csa/CP-3.md") == ("csa", "CP-3")

    def test_policy_document_has_no_counterparty_id(self) -> None:
        assert _metadata_from_key("policy/margin_policy.md") == ("policy", "")

    def test_top_level_file_is_unknown_doc_type(self) -> None:
        assert _metadata_from_key("README.md") == ("unknown", "")


class TestGetChromaClient:
    def test_constructs_http_client_from_settings(self) -> None:
        settings = Settings(_env_file=None, chroma_host="chroma-test-host", chroma_port=9999)

        with patch("rag.ingest.chromadb.HttpClient") as mock_http_client:
            get_chroma_client(settings)

        mock_http_client.assert_called_once_with(host="chroma-test-host", port=9999)


class TestEmbedTexts:
    def test_calls_openai_with_the_configured_model(self) -> None:
        client = MagicMock()
        client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=[0.1, 0.2]), MagicMock(embedding=[0.3, 0.4])]
        )

        result = embed_texts(["a", "b"], client=client)

        client.embeddings.create.assert_called_once_with(model=EMBEDDING_MODEL, input=["a", "b"])
        assert result == [[0.1, 0.2], [0.3, 0.4]]


class TestRunIngestion:
    def test_chunks_embeds_and_upserts_with_citation_metadata(self) -> None:
        documents = [("csa/CP-1.md", SAMPLE_CSA), ("policy/margin_policy.md", SAMPLE_POLICY)]

        openai_client = MagicMock()
        openai_client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=[float(i)]) for i in range(4)]
        )

        chroma_client = MagicMock()
        collection = MagicMock()
        chroma_client.get_or_create_collection.return_value = collection

        count = run_ingestion(
            documents=documents, openai_client=openai_client, chroma_client=chroma_client
        )

        # CP-1.md: Overview + Threshold = 2 chunks; margin_policy.md: Overview + Valuation Timing = 2
        assert count == 4
        collection.upsert.assert_called_once()
        call_kwargs = collection.upsert.call_args.kwargs

        assert call_kwargs["ids"] == [
            "csa/CP-1.md#0",
            "csa/CP-1.md#1",
            "policy/margin_policy.md#0",
            "policy/margin_policy.md#1",
        ]
        assert len(call_kwargs["embeddings"]) == 4
        assert len(call_kwargs["documents"]) == 4

        csa_threshold_meta = call_kwargs["metadatas"][1]
        assert csa_threshold_meta["source_file"] == "csa/CP-1.md"
        assert csa_threshold_meta["doc_type"] == "csa"
        assert csa_threshold_meta["counterparty_id"] == "CP-1"
        assert csa_threshold_meta["effective_date"] == "2026-07-26"
        assert csa_threshold_meta["section"] == "Threshold"

        policy_meta = call_kwargs["metadatas"][2]
        assert policy_meta["doc_type"] == "policy"
        assert policy_meta["counterparty_id"] == ""

    def test_empty_corpus_returns_zero_without_calling_openai_or_chroma(self) -> None:
        openai_client = MagicMock()
        chroma_client = MagicMock()

        count = run_ingestion(
            documents=[], openai_client=openai_client, chroma_client=chroma_client
        )

        assert count == 0
        openai_client.embeddings.create.assert_not_called()
        chroma_client.get_or_create_collection.assert_not_called()


class TestMain:
    def test_prints_ingested_count(self, capsys) -> None:
        with patch("rag.ingest.run_ingestion", return_value=7):
            main()

        assert "7 chunks" in capsys.readouterr().out
