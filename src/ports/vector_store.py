from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel


class VectorHit(BaseModel):
    text: str
    metadata: dict[str, str]
    distance: float


class VectorStore(Protocol):
    """Stores document chunks with metadata and finds the nearest ones.

    Filter semantics (shared by every adapter): `counterparty_id` matches that
    counterparty's own chunks *plus* shared chunks (counterparty_id == ""), so a
    counterparty-scoped query still surfaces firm-wide policy; `doc_type`
    matches exactly. Results are ordered nearest first.
    """

    def upsert(
        self,
        ids: list[str],
        embeddings: list[Sequence[float]],
        documents: list[str],
        metadatas: list[dict[str, str]],
    ) -> None:
        """Insert or replace by id -- re-ingesting the same chunk is idempotent."""
        ...

    def query(
        self,
        embedding: Sequence[float],
        top_k: int,
        counterparty_id: str | None = None,
        doc_type: str | None = None,
    ) -> list[VectorHit]: ...
