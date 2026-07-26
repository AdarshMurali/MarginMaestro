from collections.abc import Sequence
from pathlib import Path

import chromadb
from chromadb.api.types import Metadata
from openai import OpenAI

from config.settings import Settings, get_settings
from rag.chunker import chunk_markdown, extract_effective_date
from rag.s3_upload import iter_corpus_documents

# See ADR-0006: OpenAI embeddings, not local BGE. Ingestion and retrieval
# (MM-25) must use this exact same model -- mismatched embeddings produce
# meaningless similarity scores.
EMBEDDING_MODEL = "text-embedding-3-small"
COLLECTION_NAME = "csa_documents"


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
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def run_ingestion(
    settings: Settings | None = None,
    documents: list[tuple[str, str]] | None = None,
    openai_client: OpenAI | None = None,
    chroma_client: chromadb.ClientAPI | None = None,
) -> int:
    """Chunks every document in the corpus, embeds each chunk (OpenAI), and
    upserts into ChromaDB with citation metadata. upsert (not add) keyed by a
    deterministic chunk id makes re-ingestion idempotent.
    """
    settings = settings or get_settings()
    documents = documents if documents is not None else iter_corpus_documents(settings)
    if not documents:
        return 0

    openai_client = openai_client or OpenAI(api_key=settings.openai_api_key)
    chroma_client = chroma_client or get_chroma_client(settings)
    collection = chroma_client.get_or_create_collection(COLLECTION_NAME)

    ids: list[str] = []
    texts: list[str] = []
    metadatas: list[Metadata] = []

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

    embeddings = embed_texts(texts, openai_client)
    collection.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
    return len(texts)


def main() -> None:
    count = run_ingestion()
    print(f"Ingested {count} chunks into ChromaDB collection '{COLLECTION_NAME}'")


if __name__ == "__main__":
    main()
