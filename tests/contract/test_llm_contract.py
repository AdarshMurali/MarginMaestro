"""LLMClient + Embedder contracts (MM-102). Gemini / Vertex embeddings join in
G2. Vendor SDKs are faked at the HTTP-client boundary, so these assert what
each adapter sends and how it maps the response -- never real model output."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from adapters.openai_adapter import EMBEDDING_MODEL, OpenAIChat, OpenAIEmbedder


class _Answer(BaseModel):
    threshold: float


def _openai_chat(content=None, parsed=None):
    client = MagicMock()
    message = SimpleNamespace(content=content, parsed=parsed)
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=message)]
    )
    client.chat.completions.parse.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=message)]
    )
    return OpenAIChat(client, model="gpt-test"), client


LLM_ADAPTERS = [pytest.param(_openai_chat, id="openai")]


@pytest.mark.parametrize("make", LLM_ADAPTERS)
def test_complete_returns_model_text(make):
    llm, _ = make(content="Dear client, ...")

    assert llm.complete("system", "user") == "Dear client, ..."


@pytest.mark.parametrize("make", LLM_ADAPTERS)
def test_complete_returns_none_when_model_is_silent(make):
    llm, _ = make(content=None)

    assert llm.complete("system", "user") is None


@pytest.mark.parametrize("make", LLM_ADAPTERS)
def test_parse_returns_schema_instance(make):
    llm, _ = make(parsed=_Answer(threshold=1_000_000))

    result = llm.parse("system", "user", _Answer)

    assert isinstance(result, _Answer)
    assert result.threshold == 1_000_000


@pytest.mark.parametrize("make", LLM_ADAPTERS)
def test_parse_returns_none_when_extraction_fails(make):
    llm, _ = make(parsed=None)

    assert llm.parse("system", "user", _Answer) is None


def test_openai_chat_sends_system_and_user_messages_to_configured_model():
    llm, client = _openai_chat(parsed=_Answer(threshold=1.0))

    llm.parse("be precise", "extract terms", _Answer)

    client.chat.completions.parse.assert_called_once_with(
        model="gpt-test",
        messages=[
            {"role": "system", "content": "be precise"},
            {"role": "user", "content": "extract terms"},
        ],
        response_format=_Answer,
    )


def _openai_embedder():
    client = MagicMock()
    client.embeddings.create.side_effect = lambda model, input: SimpleNamespace(
        data=[SimpleNamespace(embedding=[float(len(text)), 1.0]) for text in input]
    )
    return OpenAIEmbedder(client), client


@pytest.mark.parametrize("make", [pytest.param(_openai_embedder, id="openai")])
def test_embedder_returns_one_vector_per_text_in_order(make):
    embedder, _ = make()

    vectors = embedder.embed(["a", "bbb", "cc"])

    assert [list(v) for v in vectors] == [[1.0, 1.0], [3.0, 1.0], [2.0, 1.0]]


def test_openai_embedder_uses_the_shared_embedding_model():
    embedder, client = _openai_embedder()

    embedder.embed(["a"])

    client.embeddings.create.assert_called_once_with(model=EMBEDDING_MODEL, input=["a"])
