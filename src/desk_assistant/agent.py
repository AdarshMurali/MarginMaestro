"""The desk assistant's ADK agent (MM-129).

- **Tools:** the three read-only MCP servers on Cloud Run (MM-128). Gemini
  picks which to call; every call carries the analyst (`X-MM-User`, the
  session's user id, set by our API) and, on GCP, a Google ID token for that
  service, which is what Cloud Run IAM checks.
- **Guardrails:** the same pipeline as every other LLM call in the app
  (MM-113/114): the analyst's message is screened before the model sees it,
  and every answer before the analyst does. A block or an unavailable
  screen ends the turn with a refusal, never an unscreened answer.
- **Numbers:** the instruction requires amounts to be quoted from tool
  results, never computed (golden rule 1). MM-132 evaluates it.
"""

import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import structlog
from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams
from google.genai import types

from adapters.guardrail_factory import get_guardrail
from config.settings import Settings, get_settings
from ports.guardrail import Guardrail, GuardrailError

logger = structlog.get_logger()

CALLER_HEADER = "X-MM-User"
REFUSAL = (
    "I can't help with that request. Ask about prices, CSA or policy terms, "
    "or the status of your margin calls."
)

INSTRUCTION = """You are the margin desk assistant for a collateral management team.
You answer analysts' questions about market prices, CSA and policy terms, and
the status of margin calls, using only your tools.

Rules:
- Use tools for every fact. If the tools don't return it, say you don't know.
- Quote amounts, thresholds and prices exactly as the tools return them, with
  their currency. Never calculate, estimate or round a financial figure.
- Cite the document and section for every CSA or policy term you mention.
- You can only read. You cannot approve, reject, send or escalate a margin
  call; tell the analyst to do that in the dashboard.
- You only see the counterparties this analyst covers. If a tool returns
  nothing for a counterparty, say it isn't available to them.
- Keep answers short and factual."""

# ID tokens last an hour; refresh with a margin.
_TOKEN_TTL_SECONDS = 50 * 60


class IdTokenCache:
    """One Google ID token per audience (the MCP service URL), refreshed
    before it expires. On Agent Runtime the token is for the agent's own
    identity, fetched from the metadata server."""

    def __init__(
        self,
        fetch: Callable[[str], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetch or _fetch_id_token
        self._clock = clock
        self._tokens: dict[str, tuple[str, float]] = {}

    def get(self, audience: str) -> str:
        token, fetched_at = self._tokens.get(audience, ("", 0.0))
        if not token or self._clock() - fetched_at > _TOKEN_TTL_SECONDS:
            token = self._fetch(audience)
            self._tokens[audience] = (token, self._clock())
        return token


def _fetch_id_token(audience: str) -> str:
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    return str(id_token.fetch_id_token(Request(), audience))


def _audience(url: str) -> str:
    """Cloud Run accepts the service URL (scheme + host, no path) as the
    token audience."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def header_provider(
    url: str, auth: str, tokens: IdTokenCache
) -> Callable[[ReadonlyContext], dict[str, str]]:
    def headers(context: ReadonlyContext) -> dict[str, str]:
        if not context.user_id:
            raise PermissionError("Desk assistant call without a user")
        result = {CALLER_HEADER: context.user_id}
        if auth == "google":
            result["Authorization"] = f"Bearer {tokens.get(_audience(url))}"
        return result

    return headers


def build_toolsets(settings: Settings, tokens: IdTokenCache | None = None) -> list[McpToolset]:
    urls = {
        "market_data": settings.desk_mcp_market_data_url,
        "rag": settings.desk_mcp_rag_url,
        "margin_status": settings.desk_mcp_margin_status_url,
    }
    missing = [name for name, url in urls.items() if not url]
    if missing:
        raise ValueError(f"Desk assistant MCP URLs not set: {', '.join(missing)}")
    auth = settings.desk_mcp_auth.strip().lower()
    if auth not in ("google", "none"):
        raise ValueError(f"DESK_MCP_AUTH must be 'google' or 'none', got {auth!r}")
    tokens = tokens or IdTokenCache()
    return [
        McpToolset(
            connection_params=StreamableHTTPConnectionParams(url=url, timeout=30),
            header_provider=header_provider(url, auth, tokens),
        )
        for url in urls.values()
    ]


def _text(content: types.Content | None) -> str:
    if content is None or not content.parts:
        return ""
    return "\n".join(part.text for part in content.parts if part.text)


def _refusal() -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=REFUSAL)]))


def screen_prompt(guardrail: Guardrail) -> Callable[[Any, LlmRequest], LlmResponse | None]:
    """Screens the analyst's latest message. Tool results are not
    re-screened here: they come from our own read-only servers."""

    def callback(_: Any, request: LlmRequest) -> LlmResponse | None:
        latest = request.contents[-1] if request.contents else None
        if latest is None or latest.role != "user":
            return None
        text = _text(latest)
        if not text:  # a function response turn, not the analyst
            return None
        return _screen(guardrail, text, "prompt")

    return callback


def screen_response(guardrail: Guardrail) -> Callable[[Any, LlmResponse], LlmResponse | None]:
    def callback(_: Any, response: LlmResponse) -> LlmResponse | None:
        text = _text(response.content)
        if not text or response.partial:
            return None
        return _screen(guardrail, text, "response")

    return callback


def _screen(guardrail: Guardrail, text: str, stage: str) -> LlmResponse | None:
    try:
        verdict = guardrail.screen(text, stage)  # type: ignore[arg-type]
    except GuardrailError as exc:  # unavailable: fail closed
        logger.warning("desk_guardrail_unavailable", stage=stage, error=str(exc))
        return _refusal()
    if verdict.allowed:
        return None
    logger.warning(
        "desk_guardrail_blocked", stage=stage, guardrail=verdict.guardrail, reasons=verdict.reasons
    )
    return _refusal()


def build_agent(
    settings: Settings | None = None,
    guardrail: Guardrail | None = None,
    tokens: IdTokenCache | None = None,
) -> LlmAgent:
    settings = settings or get_settings()
    guardrail = guardrail or get_guardrail(settings)
    return LlmAgent(
        name="margin_desk",
        model=settings.gemini_model,
        description="Answers analysts' questions about prices, CSA terms and margin calls.",
        instruction=INSTRUCTION,
        tools=list(build_toolsets(settings, tokens)),
        generate_content_config=types.GenerateContentConfig(temperature=0),
        before_model_callback=screen_prompt(guardrail),
        after_model_callback=screen_response(guardrail),
    )
