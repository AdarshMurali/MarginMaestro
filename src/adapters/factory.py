"""Picks one adapter per port from Settings (MM-102). Defaults reproduce the
pre-GCP stack exactly (OpenAI, Chroma, Kafka, Slack), so the AWS deployment
needs no config change (ground rule 6). GCP adapters are added here as each
phase lands: Gemini (G2, MM-109), pgvector (G2), Pub/Sub (G4), WhatsApp (G6)."""

from typing import Any

from openai import OpenAI

from adapters.chroma_adapter import ChromaVectorStore
from adapters.openai_adapter import OpenAIChat, OpenAIEmbedder
from config.settings import Settings
from ports.embedder import Embedder
from ports.event_bus import EventBus
from ports.guardrail import Guardrail
from ports.llm import LLMClient
from ports.notifier import Notifier
from ports.redactor import Redactor
from ports.vector_store import VectorStore

RAG_COLLECTION = "csa_documents"


def _choice(name: str, value: str, allowed: tuple[str, ...]) -> str:
    choice = value.strip().lower()
    if choice not in allowed:
        raise ValueError(f"{name} must be one of {allowed}, got {value!r}")
    return choice


def get_llm(settings: Settings, openai_client: OpenAI | None = None) -> LLMClient:
    """The configured model, wrapped in the configured guardrail (MM-113):
    every prompt and response is screened, failing closed."""
    from adapters.guarded_llm import GuardedLLM

    return GuardedLLM(
        _get_model(settings, openai_client), get_guardrail(settings), get_redactor(settings)
    )


def get_redactor(settings: Settings) -> Redactor:
    choice = _choice("REDACTOR_PROVIDER", settings.redactor_provider, ("regex", "sdp", "none"))
    from adapters.redactors import (
        ChainedRedactor,
        NoRedactor,
        RegexRedactor,
        SdpRedactor,
        dlp_client,
    )

    if choice == "sdp":
        if not settings.gcp_project_id:
            raise ValueError("REDACTOR_PROVIDER=sdp requires GCP_PROJECT_ID")
        return ChainedRedactor(
            [
                SdpRedactor(settings.gcp_project_id, settings.sdp_location, dlp_client()),
                RegexRedactor(),
            ]
        )
    return NoRedactor() if choice == "none" else RegexRedactor()


def get_guardrail(settings: Settings) -> Guardrail:
    choice = _choice(
        "GUARDRAIL_PROVIDER", settings.guardrail_provider, ("incode", "modelarmor", "none")
    )
    if choice == "modelarmor":
        from adapters.model_armor_guardrail import ModelArmorGuardrail, model_armor_client

        if not settings.gcp_project_id:
            raise ValueError("GUARDRAIL_PROVIDER=modelarmor requires GCP_PROJECT_ID")
        template = (
            f"projects/{settings.gcp_project_id}/locations/{settings.model_armor_location}"
            f"/templates/{settings.model_armor_template_id}"
        )
        from adapters.composite_guardrail import CompositeGuardrail
        from adapters.incode_guardrail import InCodeGuardrail

        # Defence in depth: Model Armor plus the in-code checks; either blocks.
        return CompositeGuardrail(
            [
                ModelArmorGuardrail(template, model_armor_client(settings.model_armor_location)),
                InCodeGuardrail(),
            ]
        )
    from adapters.incode_guardrail import InCodeGuardrail, NoGuardrail

    return NoGuardrail() if choice == "none" else InCodeGuardrail()


def _get_model(settings: Settings, openai_client: OpenAI | None = None) -> LLMClient:
    provider = _choice("LLM_PROVIDER", settings.llm_provider, ("openai", "vertex"))
    if provider == "vertex":
        from adapters.gemini_adapter import GeminiChat

        return GeminiChat(
            _genai_client(settings),
            model=settings.gemini_model,
            thinking_level=settings.gemini_thinking_level or None,
        )
    client = openai_client or OpenAI(api_key=settings.openai_api_key)
    return OpenAIChat(client, model=settings.openai_model)


def _genai_client(settings: Settings, location: str | None = None) -> Any:
    if not settings.gcp_project_id:
        raise ValueError(
            "Vertex AI (LLM_PROVIDER / EMBEDDING_PROVIDER=vertex) requires GCP_PROJECT_ID"
        )
    # Imported lazily: only needed when a Vertex adapter is selected.
    from google.genai import Client

    return Client(
        vertexai=True,
        project=settings.gcp_project_id,
        location=location or settings.gemini_location,
    )


def get_embedder(settings: Settings, openai_client: OpenAI | None = None) -> Embedder:
    provider = _choice("EMBEDDING_PROVIDER", settings.embedding_provider, ("openai", "vertex"))
    if provider == "vertex":
        from adapters.gemini_adapter import GeminiEmbedder

        return GeminiEmbedder(
            _genai_client(settings, location=settings.gemini_embedding_location),
            model=settings.gemini_embedding_model,
            dimensions=settings.embedding_dimensions,
        )
    return OpenAIEmbedder(openai_client or OpenAI(api_key=settings.openai_api_key))


def get_vector_store(settings: Settings) -> VectorStore:
    store = _choice("VECTOR_STORE", settings.vector_store, ("chroma", "pgvector"))
    if store == "pgvector":
        from adapters.pgvector_adapter import PgVectorStore
        from persistence.db.engine import db_dialect, get_session_factory

        if db_dialect(settings) != "postgres":
            raise ValueError("VECTOR_STORE=pgvector requires DB_DIALECT=postgres")
        return PgVectorStore(get_session_factory(settings))
    from rag.ingest import get_chroma_client

    return ChromaVectorStore(get_chroma_client(settings), RAG_COLLECTION)


def get_event_bus(settings: Settings) -> EventBus:
    _choice("EVENT_BUS", settings.event_bus, ("kafka",))
    from streaming.producer import EventProducer

    return EventProducer(settings)


def get_notifier(settings: Settings) -> Notifier:
    _choice("CLIENT_NOTIFIER", settings.client_notifier, ("slack",))
    from adapters.slack_adapter import SlackNotifier

    return SlackNotifier(settings)
