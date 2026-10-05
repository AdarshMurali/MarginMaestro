"""The API side of 'Ask the margin desk' (MM-129).

The UI posts a message; the API, which knows who the analyst is, forwards it
to the ADK agent on Agent Runtime as that analyst (`user_id`). The agent
passes the same id to the MCP servers, which scope every read to it. So the
analyst's identity always comes from the API's JWT check, never from the
chat itself.

Calls Agent Runtime's REST API directly (`:query` to open a session,
`:streamQuery` for a turn) so the API image needs no ADK/Vertex SDK. The
Cloud Run service account (mm-api-sa) holds aiplatform.user.
"""

import json
from collections.abc import Callable, Iterable
from typing import Any, Protocol, cast

import structlog
from fastapi import HTTPException
from pydantic import BaseModel, Field

from config.settings import Settings

logger = structlog.get_logger()

CLOUD_PLATFORM = "https://www.googleapis.com/auth/cloud-platform"


class DeskChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=200)


class DeskChatResponse(BaseModel):
    session_id: str
    answer: str
    tools_used: list[str] = []


class HttpSession(Protocol):
    def post(self, url: str, **kwargs: Any) -> Any: ...


class AgentRuntimeDesk:
    """Talks to the deployed agent (`projects/.../reasoningEngines/<id>`)."""

    def __init__(self, resource: str, location: str, http: HttpSession) -> None:
        self._base = f"https://{location}-aiplatform.googleapis.com/v1/{resource}"
        self._http = http

    def chat(self, username: str, message: str, session_id: str | None) -> DeskChatResponse:
        session_id, events = self.run_turn(username, message, session_id)
        answer, tools = summarize_events(events)
        logger.info("desk_chat_turn", username=username, session_id=session_id, tools=tools)
        return DeskChatResponse(session_id=session_id, answer=answer, tools_used=tools)

    def run_turn(
        self, username: str, message: str, session_id: str | None
    ) -> tuple[str, list[dict]]:
        """One turn's raw events (model text, tool calls and tool results) --
        what the evaluation job (MM-132) scores; chat() summarizes them."""
        session_id = session_id or self._create_session(username)
        response = self._http.post(
            f"{self._base}:streamQuery?alt=sse",
            json={
                "class_method": "async_stream_query",
                "input": {"user_id": username, "session_id": session_id, "message": message},
            },
            stream=True,
            timeout=120,
        )
        _raise_for_status(response)
        return session_id, list(_events(response.iter_lines()))

    def _create_session(self, username: str) -> str:
        response = self._http.post(
            f"{self._base}:query",
            json={"class_method": "async_create_session", "input": {"user_id": username}},
            timeout=60,
        )
        _raise_for_status(response)
        return str(response.json()["output"]["id"])


def _raise_for_status(response: Any) -> None:
    if response.status_code == 404:
        # An unknown session id, or one that belongs to another user.
        raise HTTPException(status_code=404, detail="Chat session not found")
    if response.status_code >= 400:
        logger.error("desk_agent_error", status=response.status_code, body=response.text[:500])
        raise HTTPException(status_code=502, detail="Desk assistant unavailable")


def _events(lines: Iterable[bytes | str]) -> Iterable[dict]:
    """streamQuery yields one JSON event per line (SSE `data:` prefix optional)."""
    for raw in lines:
        line = raw.decode() if isinstance(raw, bytes) else raw
        line = line.strip()
        if line.startswith("data:"):
            line = line[len("data:") :].strip()
        if line:
            yield json.loads(line)


def summarize_events(events: Iterable[dict]) -> tuple[str, list[str]]:
    """The model's final text and the tools it called, in order. Partial
    (streamed) chunks are skipped; the complete event repeats them."""
    texts: list[str] = []
    tools: list[str] = []
    for event in events:
        if event.get("partial"):
            continue
        for part in (event.get("content") or {}).get("parts") or []:
            call = part.get("function_call")
            if call and call.get("name") not in tools:
                tools.append(call["name"])
            if part.get("text") and event.get("content", {}).get("role") == "model":
                texts.append(part["text"])
    if not texts:
        raise HTTPException(status_code=502, detail="Desk assistant returned no answer")
    return texts[-1].strip(), tools


def _google_session() -> HttpSession:
    from google.auth import default as google_default_credentials
    from google.auth.transport.requests import AuthorizedSession

    credentials, _ = google_default_credentials(scopes=[CLOUD_PLATFORM])
    session: Any = AuthorizedSession(credentials)  # type: ignore[no-untyped-call]
    return cast(HttpSession, session)


def get_desk(
    settings: Settings, http_factory: Callable[[], HttpSession] = _google_session
) -> AgentRuntimeDesk:
    mode = settings.desk_assistant.strip().lower()
    if mode == "none":
        raise HTTPException(status_code=503, detail="Desk assistant is not enabled")
    if mode != "agent_runtime":
        raise ValueError(f"DESK_ASSISTANT must be 'none' or 'agent_runtime', got {mode!r}")
    if "/locations/" not in settings.desk_agent_resource:
        raise ValueError(
            "DESK_ASSISTANT=agent_runtime requires DESK_AGENT_RESOURCE "
            "(projects/<p>/locations/<l>/reasoningEngines/<id>)"
        )
    location = settings.desk_agent_resource.split("/locations/", 1)[1].split("/", 1)[0]
    return AgentRuntimeDesk(settings.desk_agent_resource, location, http_factory())
