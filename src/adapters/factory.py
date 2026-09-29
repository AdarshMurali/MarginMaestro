"""Picks one adapter per port from Settings (MM-102). Defaults reproduce the
pre-GCP stack exactly (OpenAI, Chroma, Kafka, Slack), so the AWS deployment
needs no config change (ground rule 6). GCP adapters are added here as each
phase lands: pgvector (G1), Gemini (G2), Pub/Sub (G4), WhatsApp (G6)."""

from openai import OpenAI

from adapters.chroma_adapter import ChromaVectorStore
from adapters.openai_adapter import OpenAIChat, OpenAIEmbedder
from config.settings import Settings
from ports.embedder import Embedder
from ports.event_bus import EventBus
from ports.llm import LLMClient
from ports.notifier import Notifier
from ports.vector_store import VectorStore

RAG_COLLECTION = "csa_documents"


def _choice(name: str, value: str, allowed: tuple[str, ...]) -> str:
    choice = value.strip().lower()
    if choice not in allowed:
        raise ValueError(f"{name} must be one of {allowed}, got {value!r}")
    return choice


def get_llm(settings: Settings, openai_client: OpenAI | None = None) -> LLMClient:
    # Only OpenAI exists today. LLM_PROVIDER isn't consulted yet: its default
    # ("ollama") was never honoured by the agents, which always used OpenAI --
    # G2 wires LLM_PROVIDER=openai|vertex here and fixes that default.
    client = openai_client or OpenAI(api_key=settings.openai_api_key)
    return OpenAIChat(client, model=settings.openai_model)


def get_embedder(settings: Settings, openai_client: OpenAI | None = None) -> Embedder:
    return OpenAIEmbedder(openai_client or OpenAI(api_key=settings.openai_api_key))


def get_vector_store(settings: Settings) -> VectorStore:
    _choice("VECTOR_STORE", settings.vector_store, ("chroma",))
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
