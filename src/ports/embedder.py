from collections.abc import Sequence
from typing import Protocol


class Embedder(Protocol):
    """Turns text into vectors. Ingestion and retrieval must use the same
    Embedder -- mixing models makes similarity scores meaningless."""

    def embed(self, texts: list[str]) -> list[Sequence[float]]:
        """One vector per input text, in input order."""
        ...
