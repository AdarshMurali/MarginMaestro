from unittest.mock import MagicMock, patch

import pytest

from adapters import factory
from adapters.chroma_adapter import ChromaVectorStore
from adapters.openai_adapter import OpenAIChat, OpenAIEmbedder
from adapters.slack_adapter import SlackNotifier
from config.settings import Settings


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, openai_api_key="sk-test", **overrides)


def test_defaults_reproduce_the_pre_gcp_stack():
    settings = _settings()

    assert isinstance(factory.get_llm(settings), OpenAIChat)
    assert isinstance(factory.get_embedder(settings), OpenAIEmbedder)
    assert isinstance(factory.get_notifier(settings), SlackNotifier)
    with patch("rag.ingest.get_chroma_client", return_value=MagicMock()):
        assert isinstance(factory.get_vector_store(settings), ChromaVectorStore)
    with patch("streaming.producer.Producer") as producer_cls:
        from streaming.producer import EventProducer

        assert isinstance(factory.get_event_bus(settings), EventProducer)
        producer_cls.assert_called_once()


def test_llm_reuses_an_injected_openai_client():
    client = MagicMock()
    llm = factory.get_llm(_settings(openai_model="gpt-x"), openai_client=client)
    client.chat.completions.create.return_value.choices = [MagicMock()]

    llm.complete("s", "u")

    assert client.chat.completions.create.call_args.kwargs["model"] == "gpt-x"


@pytest.mark.parametrize(
    ("getter", "flag"),
    [
        (factory.get_vector_store, "vector_store"),
        (factory.get_event_bus, "event_bus"),
        (factory.get_notifier, "client_notifier"),
    ],
)
def test_unknown_adapter_choice_fails_loud(getter, flag):
    with pytest.raises(ValueError, match=flag.upper()):
        getter(_settings(**{flag: "carrier-pigeon"}))


def test_adapter_choice_is_case_and_space_insensitive():
    assert isinstance(factory.get_notifier(_settings(client_notifier=" Slack ")), SlackNotifier)


# --- MM-109: LLM_PROVIDER=openai|vertex -----------------------------------------


def test_default_llm_provider_is_openai():
    assert Settings(_env_file=None).llm_provider == "openai"


def test_vertex_provider_builds_gemini_on_vertex_ai():
    from adapters.gemini_adapter import GeminiChat

    settings = _settings(llm_provider="vertex", gcp_project_id="proj-x", gemini_model="gemini-x")
    with patch("google.genai.Client") as client_cls:
        llm = factory.get_llm(settings)

    assert isinstance(llm, GeminiChat)
    client_cls.assert_called_once_with(vertexai=True, project="proj-x", location="global")


def test_vertex_provider_requires_a_project():
    with pytest.raises(ValueError, match="GCP_PROJECT_ID"):
        factory.get_llm(_settings(llm_provider="vertex"))


def test_unknown_llm_provider_fails_loud():
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        factory.get_llm(_settings(llm_provider="ollama"))


# --- MM-110: embeddings + pgvector ---------------------------------------------


def test_vertex_embedder_is_regional_gemini_embedding_at_768_dims():
    from adapters.gemini_adapter import GeminiEmbedder

    settings = _settings(embedding_provider="vertex", gcp_project_id="proj-x")
    with patch("google.genai.Client") as client_cls:
        embedder = factory.get_embedder(settings)

    assert isinstance(embedder, GeminiEmbedder)
    client_cls.assert_called_once_with(vertexai=True, project="proj-x", location="us-central1")


def test_unknown_embedding_provider_fails_loud():
    with pytest.raises(ValueError, match="EMBEDDING_PROVIDER"):
        factory.get_embedder(_settings(embedding_provider="bge"))


def test_pgvector_requires_postgres():
    with pytest.raises(ValueError, match="DB_DIALECT=postgres"):
        factory.get_vector_store(_settings(vector_store="pgvector"))


def test_pgvector_store_on_postgres():
    from adapters.pgvector_adapter import PgVectorStore

    settings = _settings(vector_store="pgvector", db_dialect="postgres")
    with patch("persistence.db.engine.get_session_factory", return_value=MagicMock()):
        assert isinstance(factory.get_vector_store(settings), PgVectorStore)
