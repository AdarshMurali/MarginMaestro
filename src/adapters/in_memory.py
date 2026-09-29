"""In-memory adapters: test doubles that honour the same contracts as the
real ones (tests/contract/). Not for production use -- nothing persists."""

from collections.abc import Sequence

from pydantic import BaseModel

from ports.vector_store import VectorHit


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._rows: dict[str, tuple[list[float], str, dict[str, str]]] = {}

    def upsert(
        self,
        ids: list[str],
        embeddings: list[Sequence[float]],
        documents: list[str],
        metadatas: list[dict[str, str]],
    ) -> None:
        for id_, embedding, document, metadata in zip(
            ids, embeddings, documents, metadatas, strict=True
        ):
            self._rows[id_] = (list(embedding), document, dict(metadata))

    def query(
        self,
        embedding: Sequence[float],
        top_k: int,
        counterparty_id: str | None = None,
        doc_type: str | None = None,
    ) -> list[VectorHit]:
        hits = []
        for vector, document, metadata in self._rows.values():
            if counterparty_id and metadata.get("counterparty_id") not in (counterparty_id, ""):
                continue
            if doc_type and metadata.get("doc_type") != doc_type:
                continue
            # Squared L2, matching Chroma's default distance.
            distance = sum((a - b) ** 2 for a, b in zip(vector, embedding, strict=True))
            hits.append(VectorHit(text=document, metadata=metadata, distance=distance))
        hits.sort(key=lambda hit: hit.distance)
        return hits[:top_k]


class InMemoryEventBus:
    def __init__(self) -> None:
        self.pending: list[tuple[str, str | None, str]] = []
        self.delivered: list[tuple[str, str | None, str]] = []

    def publish(self, topic: str, value: BaseModel, key: str | None = None) -> None:
        self.pending.append((topic, key, value.model_dump_json()))

    def flush(self, timeout: float = 10.0) -> int:
        self.delivered.extend(self.pending)
        self.pending.clear()
        return 0
