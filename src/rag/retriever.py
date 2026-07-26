import chromadb
from openai import OpenAI
from pydantic import BaseModel

from config.settings import Settings, get_settings
from rag.ingest import COLLECTION_NAME, embed_texts, get_chroma_client


class RetrievedChunk(BaseModel):
    text: str
    source_file: str
    doc_type: str
    counterparty_id: str
    effective_date: str
    section: str
    distance: float


def _build_where(counterparty_id: str | None, doc_type: str | None) -> dict | None:
    """Filters by counterparty's own chunks plus the shared/global docs
    (counterparty_id == "") -- so a counterparty-scoped query still surfaces
    e.g. the general margin policy alongside that counterparty's CSA.
    """
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


def retrieve(
    query: str,
    counterparty_id: str | None = None,
    doc_type: str | None = None,
    top_k: int = 5,
    settings: Settings | None = None,
    openai_client: OpenAI | None = None,
    chroma_client: chromadb.ClientAPI | None = None,
) -> list[RetrievedChunk]:
    """Retrieves the top_k most relevant chunks for query, filtered by
    metadata before similarity search. Query and document embeddings use the
    same OpenAI model (ingest.embed_texts) -- required for the similarity
    search to be meaningful at all (see ADR-0006).
    """
    settings = settings or get_settings()
    openai_client = openai_client or OpenAI(api_key=settings.openai_api_key)
    chroma_client = chroma_client or get_chroma_client(settings)
    collection = chroma_client.get_collection(COLLECTION_NAME)

    query_embedding = embed_texts([query], openai_client)[0]
    where = _build_where(counterparty_id, doc_type)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
    )

    documents = results["documents"][0] if results["documents"] else []
    metadatas = results["metadatas"][0] if results["metadatas"] else []
    distances = results["distances"][0] if results["distances"] else []

    return [
        RetrievedChunk(
            text=text,
            source_file=str(meta["source_file"]),
            doc_type=str(meta["doc_type"]),
            counterparty_id=str(meta["counterparty_id"]),
            effective_date=str(meta["effective_date"]),
            section=str(meta["section"]),
            distance=distance,
        )
        for text, meta, distance in zip(documents, metadatas, distances, strict=True)
    ]
