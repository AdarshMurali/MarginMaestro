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
