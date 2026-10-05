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


class TestDataClassFilterOnToolOutput:
    """MM-135: the tool's chunks go straight to the desk assistant's model."""

    def _chunk(self) -> RetrievedChunk:
        return RetrievedChunk(
            text="The Threshold applicable to Yang Partners is USD 90,000.",
            source_file="csa/CP-3.md",
            doc_type="csa",
            counterparty_id="CP-3",
            effective_date="2026-07-26",
            section="Threshold",
            distance=0.12,
        )

    def test_legal_names_are_pseudonymized_when_the_filter_is_on(self) -> None:
        from governance.catalog import get_catalog
        from governance.classification import DataClassFilter

        class Names:
            def pseudonyms(self, table: str, column: str, pseudonym: str) -> dict[str, str]:
                return {"Yang Partners": "CP-3"}

        data_filter = DataClassFilter(get_catalog(), Names())
        with (
            patch("mcp_servers.rag_retriever.retrieve", return_value=[self._chunk()]),
            patch("mcp_servers.rag_retriever._data_filter", return_value=data_filter),
        ):
            result = retrieve_document_chunks("threshold?", counterparty_id="CP-3")

        assert result[0]["text"] == "The Threshold applicable to CP-3 is USD 90,000."

    def test_filter_is_built_once_and_only_when_enabled(self) -> None:
        from mcp_servers import rag_retriever

        rag_retriever._data_filter.cache_clear()
        with (
            patch("mcp_servers.rag_retriever.get_settings") as settings,
            patch("mcp_servers.rag_retriever.get_mcp_session_factory") as session_factory,
            patch("mcp_servers.rag_retriever.get_data_class_filter") as build,
        ):
            settings.return_value.llm_data_class_filter = "none"
            assert rag_retriever._data_filter() is None
            session_factory.assert_not_called()

            rag_retriever._data_filter.cache_clear()
            settings.return_value.llm_data_class_filter = "catalog"
            assert rag_retriever._data_filter() is build.return_value
            rag_retriever._data_filter()
            build.assert_called_once_with(settings.return_value, session_factory.return_value)
        rag_retriever._data_filter.cache_clear()
