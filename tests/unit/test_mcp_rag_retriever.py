from unittest.mock import patch

from mcp_servers.rag_retriever import retrieve_document_chunks
from rag.retriever import RetrievedChunk


class TestRetrieveDocumentChunksTool:
    def test_forwards_args_and_serializes_results(self) -> None:
        chunk = RetrievedChunk(
            text="The Threshold applicable to Yang Partners is USD 90,000.",
            source_file="csa/CP-3.md",
            doc_type="csa",
            counterparty_id="CP-3",
            effective_date="2026-07-26",
            section="Threshold",
            distance=0.12,
        )

        with patch("mcp_servers.rag_retriever.retrieve", return_value=[chunk]) as mock_retrieve:
            result = retrieve_document_chunks(
                "what is CP-3's threshold?", counterparty_id="CP-3", doc_type="csa", top_k=3
            )

        mock_retrieve.assert_called_once_with("what is CP-3's threshold?", "CP-3", "csa", 3)
        assert result == [chunk.model_dump()]

    def test_no_matches_returns_an_empty_list_not_an_error(self) -> None:
        with patch("mcp_servers.rag_retriever.retrieve", return_value=[]):
            result = retrieve_document_chunks("nothing relevant")

        assert result == []
