"""Read-only margin-call status for the desk assistant (MM-128).

Reuses the API's own feed (api.margin_calls): the same checkpoint reads and
the same lifecycle status, so the assistant can never describe a call
differently from the dashboard. Every read runs in a session scoped to the
calling analyst, so row-level security hides other analysts' counterparties
(MM-106). There is deliberately no tool here that changes anything --
approvals stay with a human in the UI (golden rule 5).
"""

from functools import lru_cache
from typing import Annotated

from langgraph.graph.state import CompiledStateGraph
from mcp.server.fastmcp import Context
from pydantic import Field

from agents.orchestrator import build_orchestrator_graph
from api.margin_calls import list_margin_calls as margin_call_feed
from api.schemas import MarginCallLifecycleStatus, MarginCallSummary
from mcp_servers.base import new_server
from mcp_servers.caller import caller_scope, get_mcp_session_factory
from persistence.db.rls import RLS_SCOPE_KEY, can_see

mcp = new_server("margin-status")

STATUSES = ", ".join(status.value for status in MarginCallLifecycleStatus)


class MarginCallNotFoundError(LookupError):
    """No visible margin call with that id (absent or outside the caller's scope)."""


@lru_cache
def get_graph() -> CompiledStateGraph:
    return build_orchestrator_graph(session_factory=get_mcp_session_factory())


@mcp.tool()
def list_margin_calls(
    counterparty_id: Annotated[
        str | None, Field(description="Only this counterparty's calls, e.g. 'CP-3'.")
    ] = None,
    status: Annotated[str | None, Field(description=f"Only calls in this status: {STATUSES}.")] = (
        None
    ),
    limit: Annotated[int, Field(description="Maximum calls to return.", ge=1, le=100)] = 20,
    ctx: Context | None = None,
) -> list[dict]:
    """List margin calls the calling analyst may see, most recent first:
    counterparty, triggering event, lifecycle status, call amount and
    currency, approval decision, SLA deadline. Amounts come from the
    deterministic calc engine; quote them as given, never recompute them.
    """
    if status is not None and status not in MarginCallLifecycleStatus._value2member_map_:
        raise ValueError(f"Unknown status {status!r}; expected one of: {STATUSES}")
    calls = [
        call
        for call in _visible_calls(ctx)
        if (counterparty_id is None or call.counterparty_id == counterparty_id)
        and (status is None or call.status.value == status)
    ]
    return [call.model_dump(mode="json") for call in calls[:limit]]


@mcp.tool()
def get_margin_call(
    thread_id: Annotated[
        str, Field(description="The margin call's thread id, as returned by list_margin_calls.")
    ],
    ctx: Context | None = None,
) -> dict:
    """One margin call's current status and amounts. Raises
    MarginCallNotFoundError when it doesn't exist or isn't visible to the
    calling analyst (the two are deliberately indistinguishable)."""
    for call in _visible_calls(ctx):
        if call.thread_id == thread_id:
            return call.model_dump(mode="json")
    raise MarginCallNotFoundError(f"No margin call found for thread_id {thread_id!r}")


def _visible_calls(ctx: Context | None) -> list[MarginCallSummary]:
    factory = get_mcp_session_factory()
    scope = caller_scope(ctx, factory)
    with factory(info={RLS_SCOPE_KEY: scope}) as session:
        calls = margin_call_feed(get_graph(), session).margin_calls
    # The database already filtered by scope on Postgres; this also covers
    # SQL Server, which has no RLS (same rule as the database's app_can_see).
    return [call for call in calls if can_see(scope, call.counterparty_id)]


if __name__ == "__main__":
    mcp.run()
