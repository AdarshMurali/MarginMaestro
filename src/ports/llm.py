from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    """A chat model used for reasoning and drafting only -- never for math
    (ADR-0005)."""

    def complete(self, system: str, user: str) -> str | None:
        """Free-text answer, or None/empty if the model returned nothing."""
        ...

    def parse(self, system: str, user: str, schema: type[T]) -> T | None:
        """Structured answer validated against `schema`, or None if the model
        couldn't produce one."""
        ...
