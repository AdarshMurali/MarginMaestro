from unittest.mock import MagicMock

from rag.retriever import _build_where, retrieve


class TestBuildWhere:
    def test_no_filters_returns_none(self) -> None:
        assert _build_where(None, None) is None

    def test_counterparty_only_matches_own_or_shared_docs(self) -> None:
        where = _build_where("CP-3", None)

        assert where == {"$or": [{"counterparty_id": "CP-3"}, {"counterparty_id": ""}]}

    def test_doc_type_only(self) -> None:
        where = _build_where(None, "csa")

        assert where == {"doc_type": "csa"}

    def test_both_filters_combine_with_and(self) -> None:
        where = _build_where("CP-3", "csa")

        assert where == {
            "$and": [
                {"$or": [{"counterparty_id": "CP-3"}, {"counterparty_id": ""}]},
                {"doc_type": "csa"},
            ]
        }


class TestRetrieve:
    def test_embeds_query_and_returns_chunks_with_citations(self) -> None:
        openai_client = MagicMock()
        openai_client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=[0.1, 0.2])]
        )

        collection = MagicMock()
        collection.query.return_value = {
            "documents": [
                ["## Threshold\n\nThe Threshold applicable to Yang Partners is USD 90,000."]
            ],
            "metadatas": [
                [
                    {
                        "source_file": "csa/CP-3.md",
                        "doc_type": "csa",
                        "counterparty_id": "CP-3",
                        "effective_date": "2026-07-26",
                        "section": "Threshold",
                    }
                ]
            ],
            "distances": [[0.12]],
        }
        chroma_client = MagicMock()
        chroma_client.get_collection.return_value = collection

        results = retrieve(
            "what is CP-3's threshold?",
            counterparty_id="CP-3",
            top_k=3,
            openai_client=openai_client,
            chroma_client=chroma_client,
        )

        openai_client.embeddings.create.assert_called_once()
        collection.query.assert_called_once_with(
            query_embeddings=[[0.1, 0.2]],
            n_results=3,
            where={"$or": [{"counterparty_id": "CP-3"}, {"counterparty_id": ""}]},
        )

        assert len(results) == 1
        assert results[0].source_file == "csa/CP-3.md"
        assert results[0].counterparty_id == "CP-3"
        assert results[0].section == "Threshold"
        assert results[0].distance == 0.12
        assert "USD 90,000" in results[0].text

    def test_no_results_returns_empty_list(self) -> None:
        openai_client = MagicMock()
        openai_client.embeddings.create.return_value = MagicMock(data=[MagicMock(embedding=[0.1])])
        collection = MagicMock()
        collection.query.return_value = {"documents": [[]], "metadatas": [[]], "distances": [[]]}
        chroma_client = MagicMock()
        chroma_client.get_collection.return_value = collection

        results = retrieve("anything", openai_client=openai_client, chroma_client=chroma_client)

        assert results == []
