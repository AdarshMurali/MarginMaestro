"""Serves one MCP server over streamable HTTP (MM-128) -- the Cloud Run
entrypoint. Each read-only server is its own service, so IAM can grant the
desk assistant access per tool set. Started by the uvicorn CLI, like the
API's container (the bind address lives in the command, not in code):

    MCP_SERVER=market-data uvicorn --factory mcp_servers.http:create_app         --host 0.0.0.0 --port 8080

Only read-only servers are listed: the notifiers (Slack, ServiceNow) are never reachable from an LLM
over the network, so client contact stays behind the approval gate.
"""

import os
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette

from api.logging_config import configure_logging


# Static imports, deferred so a service loads only its own server (the
# margin-status one pulls in the orchestrator). No dynamic import by name.
def _market_data() -> FastMCP:
    from mcp_servers.market_data import mcp

    return mcp


def _rag() -> FastMCP:
    from mcp_servers.rag_retriever import mcp

    return mcp


def _margin_status() -> FastMCP:
    from mcp_servers.margin_status import mcp

    return mcp


SERVERS: dict[str, Callable[[], FastMCP]] = {
    "market-data": _market_data,
    "rag": _rag,
    "margin-status": _margin_status,
}


def get_server(name: str) -> FastMCP:
    loader = SERVERS.get(name)
    if loader is None:
        raise ValueError(f"Unknown MCP server; expected one of: {', '.join(SERVERS)}")
    return loader()


def build_app(name: str) -> Starlette:
    """Tools at POST /mcp, liveness at GET /health."""
    return get_server(name).streamable_http_app()


def create_app() -> Starlette:
    """uvicorn --factory entrypoint: the server named by MCP_SERVER."""
    configure_logging()
    return build_app(os.environ.get("MCP_SERVER", ""))
