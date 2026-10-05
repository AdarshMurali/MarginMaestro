"""MM-129: the API side of 'Ask the margin desk' -- Agent Runtime REST calls,
event parsing, and the authenticated /desk/chat endpoint."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import desk
from api.auth import Identity, require_user
from api.main import app
from config.settings import Settings

RESOURCE = "projects/proj-x/locations/us-central1/reasoningEngines/123"
BASE = f"https://us-central1-aiplatform.googleapis.com/v1/{RESOURCE}"


def _response(status: int = 200, body: dict | None = None, lines: list[str] | None = None):
    return SimpleNamespace(
        status_code=status,
        text=json.dumps(body or {}),
        json=lambda: body,
        iter_lines=lambda: iter(lines or []),
    )


EVENTS = [
    {"content": {"role": "model", "parts": [{"function_call": {"name": "list_margin_calls"}}]}},
    {"content": {"role": "user", "parts": [{"function_response": {"name": "list_margin_calls"}}]}},
    {"partial": True, "content": {"role": "model", "parts": [{"text": "CP-3 has"}]}},
    {"content": {"role": "model", "parts": [{"text": "CP-3 has one call awaiting approval."}]}},
]


class FakeHttp:
    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def _sse(events: list[dict]) -> list[str]:
    return [f"data: {json.dumps(e)}" for e in events]


# --- Agent Runtime client --------------------------------------------------------


def test_first_turn_opens_a_session_as_the_analyst_then_streams():
    http = FakeHttp(_response(body={"output": {"id": "s-1"}}), _response(lines=_sse(EVENTS)))

    reply = desk.AgentRuntimeDesk(RESOURCE, "us-central1", http).chat(
        "analyst1", "Any calls?", None
    )

    assert reply == desk.DeskChatResponse(
        session_id="s-1",
        answer="CP-3 has one call awaiting approval.",
        tools_used=["list_margin_calls"],
    )
    (create_url, create), (stream_url, stream) = http.calls
    assert create_url == f"{BASE}:query"
    assert create["json"] == {
        "class_method": "async_create_session",
        "input": {"user_id": "analyst1"},
    }
    assert stream_url == f"{BASE}:streamQuery?alt=sse"
    assert stream["json"]["input"] == {
        "user_id": "analyst1",
        "session_id": "s-1",
        "message": "Any calls?",
    }


def test_later_turns_reuse_the_session():
    http = FakeHttp(_response(lines=[json.dumps(e) for e in EVENTS] + [""]))

    reply = desk.AgentRuntimeDesk(RESOURCE, "us-central1", http).chat(
        "analyst1", "And CP-1?", "s-1"
    )

    assert reply.session_id == "s-1"
    assert len(http.calls) == 1


def test_bytes_lines_are_decoded():
    events = list(desk._events([b'data: {"a": 1}', b"", b'{"b": 2}']))

    assert events == [{"a": 1}, {"b": 2}]


def test_someone_elses_session_is_not_found():
    http = FakeHttp(_response(status=404))

    with pytest.raises(HTTPException) as exc:
        desk.AgentRuntimeDesk(RESOURCE, "us-central1", http).chat("analyst2", "hi", "s-1")

    assert exc.value.status_code == 404


def test_agent_errors_become_502():
    http = FakeHttp(_response(status=500, body={"error": "boom"}))

    with pytest.raises(HTTPException) as exc:
        desk.AgentRuntimeDesk(RESOURCE, "us-central1", http).chat("analyst1", "hi", "s-1")

    assert exc.value.status_code == 502


def test_a_turn_without_an_answer_is_502():
    with pytest.raises(HTTPException) as exc:
        desk.summarize_events([EVENTS[0]])

    assert exc.value.status_code == 502


def test_tools_are_listed_once_in_call_order():
    events = [
        {"content": {"role": "model", "parts": [{"function_call": {"name": "a"}}]}},
        {"content": {"role": "model", "parts": [{"function_call": {"name": "b"}}]}},
        {"content": {"role": "model", "parts": [{"function_call": {"name": "a"}}]}},
        {"content": {"role": "model", "parts": [{"text": " done "}]}},
    ]

    assert desk.summarize_events(events) == ("done", ["a", "b"])


# --- selection --------------------------------------------------------------------


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_chat_is_off_by_default():
    with pytest.raises(HTTPException) as exc:
        desk.get_desk(_settings())

    assert exc.value.status_code == 503


def test_agent_runtime_needs_a_full_resource_name():
    with pytest.raises(ValueError, match="DESK_AGENT_RESOURCE"):
        desk.get_desk(_settings(desk_assistant="agent_runtime", desk_agent_resource="123"))


def test_unknown_mode_fails_loud():
    with pytest.raises(ValueError, match="DESK_ASSISTANT"):
        desk.get_desk(_settings(desk_assistant="local"))


def test_agent_runtime_client_uses_the_resource_location():
    http = MagicMock()
    client = desk.get_desk(
        _settings(
            desk_assistant="agent_runtime",
            desk_agent_resource="projects/p/locations/europe-west4/reasoningEngines/9",
        ),
        http_factory=lambda: http,
    )

    assert client._base.startswith("https://europe-west4-aiplatform.googleapis.com/v1/projects/p/")


def test_google_session_uses_application_default_credentials():
    with (
        patch("google.auth.default", return_value=("creds", "proj")) as default,
        patch("google.auth.transport.requests.AuthorizedSession") as session_cls,
    ):
        desk._google_session()

    default.assert_called_once_with(scopes=[desk.CLOUD_PLATFORM])
    session_cls.assert_called_once_with("creds")


# --- endpoint ---------------------------------------------------------------------


@pytest.fixture
def client():
    app.dependency_overrides[require_user] = lambda: Identity(username="analyst1", role="viewer")
    yield TestClient(app)
    app.dependency_overrides.pop(require_user, None)


def test_chat_endpoint_forwards_the_authenticated_analyst(client):
    reply = desk.DeskChatResponse(session_id="s-1", answer="ok", tools_used=[])
    fake = MagicMock()
    fake.chat.return_value = reply
    with patch("api.main.get_desk_client", return_value=fake):
        response = client.post("/desk/chat", json={"message": "hi"})

    assert response.status_code == 200
    assert response.json()["answer"] == "ok"
    fake.chat.assert_called_once_with("analyst1", "hi", None)


def test_chat_endpoint_validates_the_message(client):
    assert client.post("/desk/chat", json={"message": ""}).status_code == 422
    assert client.post("/desk/chat", json={"message": "x" * 2001}).status_code == 422


def test_chat_endpoint_requires_a_user():
    app.dependency_overrides.pop(require_user, None)
    response = TestClient(app).post("/desk/chat", json={"message": "hi"})

    assert response.status_code in (401, 500)  # 500 only if AUTH_BACKEND_SECRET is unset


def test_chat_endpoint_is_rate_limited(client):
    fake = MagicMock()
    fake.chat.return_value = desk.DeskChatResponse(session_id="s", answer="ok")
    settings = SimpleNamespace(rate_limit_per_minute=2)
    with (
        patch("api.main.get_desk_client", return_value=fake),
        patch("api.main.get_settings", return_value=settings),
        patch(
            "api.main.DESK_LIMITER",
            desk_limiter := __import__("api.rate_limit").rate_limit.SlidingWindowLimiter(),
        ),
    ):
        codes = [client.post("/desk/chat", json={"message": "hi"}).status_code for _ in range(3)]

    assert codes == [200, 200, 429]
    assert desk_limiter is not None


def test_chat_endpoint_when_disabled_is_503(client):
    from api import main

    main.get_desk_client.cache_clear()
    with patch("api.main.get_settings", return_value=_settings()):
        response = client.post("/desk/chat", json={"message": "hi"})
    main.get_desk_client.cache_clear()

    assert response.status_code == 503
