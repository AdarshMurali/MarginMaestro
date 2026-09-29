from collections.abc import Sequence
from typing import Any

import chromadb

from ports.vector_store import VectorHit


def build_where(counterparty_id: str | None, doc_type: str | None) -> dict | None:
    """Chroma `where` filter for the VectorStore filter semantics: a
    counterparty's own chunks plus shared/global ones (counterparty_id == "")."""
    clauses: list[dict] = []
    if counterparty_id:
        clauses.append({"$or": [{"counterparty_id": counterparty_id}, {"counterparty_id": ""}]})
    if doc_type:
        clauses.append({"doc_type": doc_type})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


class ChromaVectorStore:
    """`VectorStore` over one ChromaDB collection."""

    def __init__(self, client: chromadb.ClientAPI, collection_name: str) -> None:
        self._client = client
        self._collection_name = collection_name

    def upsert(
        self,
        ids: list[str],
        embeddings: list[Sequence[float]],
        documents: list[str],
        metadatas: list[dict[str, str]],
    ) -> None:
        collection = self._client.get_or_create_collection(self._collection_name)
        collection.upsert(
            ids=ids,
            embeddings=embeddings,  # type: ignore[arg-type]
            documents=documents,
            metadatas=metadatas,  # type: ignore[arg-type]
        )

    def query(
        self,
        embedding: Sequence[float],
        top_k: int,
        counterparty_id: str | None = None,
        doc_type: str | None = None,
    ) -> list[VectorHit]:
        # get_collection (not get_or_create): querying a collection that was
        # never ingested is a setup error and must fail loud.
        collection = self._client.get_collection(self._collection_name)
        results: Any = collection.query(
            query_embeddings=[embedding],  # type: ignore[list-item]
            n_results=top_k,
            where=build_where(counterparty_id, doc_type),
        )
        documents = results["documents"][0] if results["documents"] else []
        metadatas = results["metadatas"][0] if results["metadatas"] else []
        distances = results["distances"][0] if results["distances"] else []
        return [
            VectorHit(
                text=text,
                metadata={k: str(v) for k, v in meta.items()},
                distance=distance,
            )
            for text, meta, distance in zip(documents, metadatas, distances, strict=True)
        ]
