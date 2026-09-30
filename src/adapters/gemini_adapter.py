"""`LLMClient` over Gemini on Vertex AI (MM-109, ADR-0009) via the
`google-genai` SDK. Reasoning and drafting only -- never math (ADR-0005).
Vertex AI (not the AI Studio free tier) keeps prompts out of model training
and inside the project's IAM/audit boundary (ADR-0015)."""

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class GeminiChat:
    def __init__(self, client: Any, model: str) -> None:
        # `client` is a google.genai.Client(vertexai=True, ...); typed Any so
        # this module imports without the SDK (it's only needed when
        # LLM_PROVIDER=vertex).
        self._client = client
        self._model = model

    def _config(self, system: str, **extra: Any) -> Any:
        from google.genai import types

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
