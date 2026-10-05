"""Picks one adapter per port from Settings (MM-102). Defaults reproduce the
pre-GCP stack exactly (OpenAI, Chroma, Kafka, Slack), so the AWS deployment
needs no config change (ground rule 6). GCP adapters are added here as each
phase lands: Gemini (G2, MM-109), pgvector (G2), Pub/Sub (G4), WhatsApp (G6)."""

from typing import Any

from openai import OpenAI

from adapters.chroma_adapter import ChromaVectorStore

# get_guardrail lives in its own light module so the desk assistant (MM-129,
# Agent Runtime) can use it without the OpenAI/Chroma imports; re-exported.
from adapters.guardrail_factory import get_guardrail
from adapters.openai_adapter import OpenAIChat, OpenAIEmbedder
from adapters.selection import choose as _choice
from config.settings import Settings
from ports.embedder import Embedder
from ports.event_bus import EventBus
from ports.llm import LLMClient
from ports.notifier import Notifier
from ports.redactor import Redactor
from ports.sla_scheduler import SlaScheduler
from ports.vector_store import VectorStore

RAG_COLLECTION = "csa_documents"


def get_llm(settings: Settings, openai_client: OpenAI | None = None) -> LLMClient:
    """The configured model, wrapped in the configured guardrail (MM-113):
    every prompt and response is screened, failing closed."""
    from adapters.guarded_llm import GuardedLLM

    return GuardedLLM(
        _get_model(settings, openai_client),
        get_guardrail(settings),
        get_redactor(settings),
        max_prompt_chars=settings.llm_max_prompt_chars,
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


def _get_model(settings: Settings, openai_client: OpenAI | None = None) -> LLMClient:
    provider = _choice("LLM_PROVIDER", settings.llm_provider, ("openai", "vertex"))
    if provider == "vertex":
        from adapters.gemini_adapter import GeminiChat

        return GeminiChat(
            _genai_client(settings),
            model=settings.gemini_model,
            thinking_level=settings.gemini_thinking_level or None,
            thinking_budget=settings.gemini_thinking_budget,
            max_output_tokens=settings.llm_max_output_tokens,
        )
    client = openai_client or OpenAI(api_key=settings.openai_api_key)
    return OpenAIChat(
        client, model=settings.openai_model, max_output_tokens=settings.llm_max_output_tokens
    )


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
    bus = _choice("EVENT_BUS", settings.event_bus, ("kafka", "pubsub"))
    if bus == "pubsub":
        from adapters.pubsub_adapter import PubSubEventBus

        if not settings.gcp_project_id:
            raise ValueError("EVENT_BUS=pubsub requires GCP_PROJECT_ID")
        return PubSubEventBus(settings.gcp_project_id)
    from streaming.producer import EventProducer

    return EventProducer(settings)


def get_notifier(settings: Settings) -> Notifier:
    _choice("CLIENT_NOTIFIER", settings.client_notifier, ("slack",))
    from adapters.slack_adapter import SlackNotifier

    return SlackNotifier(settings)


def get_sla_scheduler(settings: Settings) -> SlaScheduler:
    """SLA_SCHEDULER=none|cloudtasks (MM-122). Cloud Tasks needs the project,
    the API's base URL and the invoker identity; missing any fails loud."""
    from adapters.cloud_tasks_sla import CloudTasksSlaScheduler, NoSlaScheduler

    choice = _choice("SLA_SCHEDULER", settings.sla_scheduler, ("none", "cloudtasks"))
    if choice == "none":
        return NoSlaScheduler()
    required = {
        "GCP_PROJECT_ID": settings.gcp_project_id,
        "INTERNAL_BASE_URL": settings.internal_base_url,
        "INTERNAL_CALLER_SERVICE_ACCOUNT": settings.internal_caller_service_account,
        "INTERNAL_CALLER_AUDIENCE": settings.internal_caller_audience,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"SLA_SCHEDULER=cloudtasks requires {', '.join(missing)}")
    queue = (
        f"projects/{settings.gcp_project_id}/locations/{settings.cloud_tasks_location}"
        f"/queues/{settings.cloud_tasks_queue}"
    )
    return CloudTasksSlaScheduler(
        queue_path=queue,
        base_url=str(settings.internal_base_url),
        invoker_service_account=str(settings.internal_caller_service_account),
        audience=str(settings.internal_caller_audience),
    )
