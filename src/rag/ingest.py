from collections.abc import Sequence
from pathlib import Path

import chromadb
from openai import OpenAI

from adapters.chroma_adapter import ChromaVectorStore
from adapters.factory import RAG_COLLECTION, get_embedder, get_vector_store
from adapters.openai_adapter import EMBEDDING_MODEL, OpenAIEmbedder
from config.settings import Settings, get_settings
from ports.embedder import Embedder
from ports.vector_store import VectorStore
from rag.chunker import chunk_markdown, extract_effective_date
from rag.documents import iter_corpus_documents

# EMBEDDING_MODEL (ADR-0006) now lives with the OpenAI adapter; re-exported
# here for existing callers.
__all__ = [
    "COLLECTION_NAME",
    "EMBEDDING_MODEL",
    "embed_texts",
    "get_chroma_client",
    "run_ingestion",
]
COLLECTION_NAME = RAG_COLLECTION


def _metadata_from_key(key: str) -> tuple[str, str]:
    """csa/CP-3.md -> ("csa", "CP-3"); policy/margin_policy.md -> ("policy", "")."""
    parts = key.split("/")
    doc_type = parts[0] if len(parts) > 1 else "unknown"
    stem = Path(parts[-1]).stem
    counterparty_id = stem if doc_type == "csa" else ""
    return doc_type, counterparty_id


def get_chroma_client(settings: Settings | None = None) -> chromadb.ClientAPI:
    settings = settings or get_settings()
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)


def embed_texts(texts: list[str], client: OpenAI) -> list[Sequence[float]]:
    return OpenAIEmbedder(client).embed(texts)


def run_ingestion(
    settings: Settings | None = None,
    documents: list[tuple[str, str]] | None = None,
    openai_client: OpenAI | None = None,
    chroma_client: chromadb.ClientAPI | None = None,
    embedder: Embedder | None = None,
    vector_store: VectorStore | None = None,
) -> int:
    """Chunks every document in the corpus, embeds each chunk (OpenAI), and
    upserts into ChromaDB with citation metadata. upsert (not add) keyed by a
    deterministic chunk id makes re-ingestion idempotent.
    """
    settings = settings or get_settings()
    documents = documents if documents is not None else iter_corpus_documents(settings)
    if not documents:
        return 0

    embedder = embedder or get_embedder(settings, openai_client)
    if vector_store is None:
        vector_store = (
            ChromaVectorStore(chroma_client, COLLECTION_NAME)
            if chroma_client is not None
            else get_vector_store(settings)
        )

    ids: list[str] = []
    texts: list[str] = []
    metadatas: list[dict[str, str]] = []

    for key, content in documents:
        doc_type, counterparty_id = _metadata_from_key(key)
        effective_date = extract_effective_date(content)
        for i, chunk in enumerate(chunk_markdown(content)):
            ids.append(f"{key}#{i}")
            texts.append(chunk.text)
            metadatas.append(
                {
                    "source_file": key,
                    "doc_type": doc_type,
                    "counterparty_id": counterparty_id,
                    "effective_date": effective_date,
                    "section": chunk.section,
                }
            )

    embeddings = embedder.embed(texts)
    vector_store.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
    return len(texts)


def main() -> None:
    settings = get_settings()
    count = run_ingestion(settings)
    print(
        f"Ingested {count} chunks from {settings.document_store} into the "
        f"{settings.vector_store} store ('{COLLECTION_NAME}')"
    )


if __name__ == "__main__":
    main()
