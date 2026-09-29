import chromadb
from openai import OpenAI
from pydantic import BaseModel

from adapters.chroma_adapter import ChromaVectorStore, build_where
from adapters.factory import get_embedder, get_vector_store
from config.settings import Settings, get_settings
from ports.embedder import Embedder
from ports.vector_store import VectorStore
from rag.ingest import COLLECTION_NAME


class RetrievedChunk(BaseModel):
    text: str
    source_file: str
    doc_type: str
    counterparty_id: str
    effective_date: str
    section: str
    distance: float


# Kept for existing callers/tests; the filter now lives with the Chroma adapter.
_build_where = build_where


def retrieve(
    query: str,
    counterparty_id: str | None = None,
    doc_type: str | None = None,
    top_k: int = 5,
    settings: Settings | None = None,
    openai_client: OpenAI | None = None,
    chroma_client: chromadb.ClientAPI | None = None,
    embedder: Embedder | None = None,
    vector_store: VectorStore | None = None,
) -> list[RetrievedChunk]:
    """Retrieves the top_k most relevant chunks for query, filtered by
    metadata before similarity search. Query and document embeddings use the
    same Embedder as ingestion -- required for the similarity search to be
    meaningful at all (see ADR-0006).
    """
    settings = settings or get_settings()
    embedder = embedder or get_embedder(settings, openai_client)
    if vector_store is None:
        vector_store = (
            ChromaVectorStore(chroma_client, COLLECTION_NAME)
            if chroma_client is not None
            else get_vector_store(settings)
        )

    query_embedding = embedder.embed([query])[0]
    hits = vector_store.query(
        query_embedding, top_k, counterparty_id=counterparty_id, doc_type=doc_type
    )
    return [
        RetrievedChunk(
            text=hit.text,
            source_file=hit.metadata["source_file"],
            doc_type=hit.metadata["doc_type"],
            counterparty_id=hit.metadata["counterparty_id"],
            effective_date=hit.metadata["effective_date"],
            section=hit.metadata["section"],
            distance=hit.distance,
        )
        for hit in hits
    ]
