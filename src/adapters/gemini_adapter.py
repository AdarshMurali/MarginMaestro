"""`LLMClient` over Gemini on Vertex AI (MM-109, ADR-0009) via the
`google-genai` SDK. Reasoning and drafting only -- never math (ADR-0005).
Vertex AI (not the AI Studio free tier) keeps prompts out of model training
and inside the project's IAM/audit boundary (ADR-0015)."""

from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ports.embedder import EmbeddingKind

T = TypeVar("T", bound=BaseModel)


class GeminiChat:
    def __init__(self, client: Any, model: str, thinking_level: str | None = None) -> None:
        # `client` is a google.genai.Client(vertexai=True, ...); typed Any so
        # this module imports without the SDK (it's only needed when
        # LLM_PROVIDER=vertex).
        self._client = client
        self._model = model
        # Gemini 3.x thinks before answering by default. Extraction and
        # drafting don't need it: `low` returned the identical CP-6 terms in
        # 2.1 s vs 6.8 s (MM-110 probe). None = the model's default.
        self._thinking_level = thinking_level

    def _config(self, system: str, **extra: Any) -> Any:
        from google.genai import types

        if self._thinking_level:
            extra["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(self._thinking_level.upper())
            )
        return types.GenerateContentConfig(system_instruction=system, **extra)

    def complete(self, system: str, user: str) -> str | None:
        response = self._client.models.generate_content(
            model=self._model, contents=user, config=self._config(system)
        )
        text: str | None = response.text
        return text

    def parse(self, system: str, user: str, schema: type[T]) -> T | None:
        response = self._client.models.generate_content(
            model=self._model,
            contents=user,
            config=self._config(
                system,
                response_mime_type="application/json",
                response_schema=schema,
                # Extraction must be repeatable (golden regression, MM-112).
                temperature=0.0,
            ),
        )
        if isinstance(response.parsed, schema):
            return response.parsed
        # The SDK leaves `parsed` empty when its own parse fails; the JSON
        # text may still be valid. Anything that doesn't validate is "no
        # answer" (None), the same contract as the OpenAI adapter.
        if not response.text:
            return None
        try:
            return schema.model_validate_json(response.text)
        except ValidationError:
            return None


class GeminiEmbedder:
    """`Embedder` over Vertex AI Gemini embeddings (MM-110, ADR-0009).
    768 dimensions to fit pgvector's HNSW index; documents and queries use
    Gemini's matching retrieval task types."""

    BATCH_SIZE = 50  # inputs per request; well inside Vertex AI's limits

    def __init__(self, client: Any, model: str, dimensions: int) -> None:
        self._client = client
        self._model = model
        self._dimensions = dimensions

    def embed(self, texts: list[str], kind: EmbeddingKind = "document") -> list[Sequence[float]]:
        from google.genai import types

        config = types.EmbedContentConfig(
            output_dimensionality=self._dimensions,
            task_type="RETRIEVAL_QUERY" if kind == "query" else "RETRIEVAL_DOCUMENT",
        )
        vectors: list[Sequence[float]] = []
        for start in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[start : start + self.BATCH_SIZE]
            response = self._client.models.embed_content(
                model=self._model, contents=batch, config=config
            )
            if len(response.embeddings) != len(batch):
                raise RuntimeError(
                    f"Gemini returned {len(response.embeddings)} embeddings for {len(batch)} texts"
                )
            vectors.extend(e.values for e in response.embeddings)
        return vectors
