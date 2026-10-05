"""Who an MCP tool call is for (MM-128), and the row-level-security scope
that follows from it.

Over HTTP the desk assistant forwards the signed-in analyst's username in
the `X-MM-User` header. The header is trusted because of who can send it:
each MCP service on Cloud Run accepts only callers granted
`roles/run.invoker`, which is the assistant's identity alone (MM-128 grants
it to mm-agent-sa; MM-131 moves it to the agent's own Agent Identity
principal). The role is never taken from the caller: it is read from the
`users` table, then mapped to a scope by the same rule the API uses.

In-process calls (stdio for local MCP clients, direct calls in tests) carry
no HTTP request and run firm-wide, the same convention as rls.py: a session
without an explicit scope is internal, never an external caller.
"""

from functools import lru_cache
from typing import Any

import structlog
from mcp.server.fastmcp import Context
from sqlalchemy.orm import Session, sessionmaker

from persistence.db.engine import get_session_factory
from persistence.db.models import UserORM
from persistence.db.rls import FIRM_WIDE, RLS_SCOPE_KEY, scope_for

CALLER_HEADER = "x-mm-user"

logger = structlog.get_logger()


class CallerNotAuthorizedError(PermissionError):
    """An HTTP tool call without a known analyst behind it."""


@lru_cache
def get_mcp_session_factory() -> sessionmaker[Session]:
    """One engine per MCP process."""
    return get_session_factory()


def caller_username(ctx: Context | None) -> str | None:
    """The forwarded username, or None for an in-process call. Fails loud on
    an HTTP request without one: no anonymous reads over the network."""
    request = _http_request(ctx)
    if request is None:
        return None
    username = (request.headers.get(CALLER_HEADER) or "").strip()
    if not username:
        raise CallerNotAuthorizedError(f"Missing {CALLER_HEADER} header")
    return username


def caller_scope(ctx: Context | None, session_factory: sessionmaker[Session]) -> str:
    """The RLS scope for this call: firm-wide in process, else the analyst's
    own counterparties (or everything for firm-wide roles)."""
    username = caller_username(ctx)
    if username is None:
        return FIRM_WIDE
    with session_factory() as lookup:
        user = lookup.get(UserORM, username)
        if user is None:
            raise CallerNotAuthorizedError(f"Unknown user {username!r}")
        scope = scope_for(user.role, username, lookup)
    logger.info("mcp_caller_scoped", username=username, role=user.role, scope=scope)
    return scope


def scoped_factory(session_factory: sessionmaker[Session], scope: str) -> sessionmaker[Session]:
    """A session factory whose sessions carry `scope`, for code that opens
    its own sessions (e.g. the pgvector store)."""
    return sessionmaker(**{**session_factory.kw, "info": {RLS_SCOPE_KEY: scope}})


def _http_request(ctx: Context | None) -> Any:
    if ctx is None:
        return None
    try:
        return ctx.request_context.request
    except ValueError:  # no active request (in-process call)
        return None
