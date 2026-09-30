from collections.abc import Sequence
from typing import Literal, Protocol

EmbeddingKind = Literal["document", "query"]


class Embedder(Protocol):
    """Turns text into vectors. Ingestion and retrieval must use the same
    Embedder -- mixing models makes similarity scores meaningless."""

    def embed(self, texts: list[str], kind: EmbeddingKind = "document") -> list[Sequence[float]]:
        """One vector per input text, in input order. `kind` lets models that
        embed documents and queries differently (Gemini's retrieval task
        types) do so; others ignore it."""
        ...
