from collections.abc import Sequence
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

from ports.embedder import EmbeddingKind

T = TypeVar("T", bound=BaseModel)

# See ADR-0006: ingestion and retrieval must use this exact same model --
# mismatched embeddings produce meaningless similarity scores.
EMBEDDING_MODEL = "text-embedding-3-small"


class OpenAIChat:
    """`LLMClient` over OpenAI chat completions."""

    def __init__(self, client: OpenAI, model: str, max_output_tokens: int | None = None) -> None:
        self._client = client
        self._model = model
        self._max_output_tokens = max_output_tokens

    def _limits(self) -> dict:
        return {"max_tokens": self._max_output_tokens} if self._max_output_tokens else {}

    def _messages(self, system: str, user: str) -> list:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def complete(self, system: str, user: str) -> str | None:
        completion = self._client.chat.completions.create(
            model=self._model, messages=self._messages(system, user), **self._limits()
        )
        content: str | None = completion.choices[0].message.content
        return content

    def parse(self, system: str, user: str, schema: type[T]) -> T | None:
        completion = self._client.chat.completions.parse(
            model=self._model,
            messages=self._messages(system, user),
            response_format=schema,
            **self._limits(),
        )
        parsed: T | None = completion.choices[0].message.parsed
        return parsed


class OpenAIEmbedder:
    """`Embedder` over OpenAI embeddings."""

    def __init__(self, client: OpenAI, model: str = EMBEDDING_MODEL) -> None:
        self._client = client
        self._model = model

    def embed(self, texts: list[str], kind: EmbeddingKind = "document") -> list[Sequence[float]]:
        # OpenAI embeds documents and queries the same way; `kind` is unused.
        response = self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in response.data]
