"""Serves one MCP server over streamable HTTP (MM-128) -- the Cloud Run
entrypoint. Each read-only server is its own service, so IAM can grant the
desk assistant access per tool set:

    python -m mcp_servers.http market-data

The server name can also come from MCP_SERVER. Only read-only servers are
listed: the notifiers (Slack, ServiceNow) are never reachable from an LLM
over the network, so client contact stays behind the approval gate.
"""

import os
import sys
from collections.abc import Callable

import uvicorn
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


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    name = args[0] if args else os.environ.get("MCP_SERVER", "")
    configure_logging()
    host = "0.0.0.0"  # NOSONAR -- the container listens on all interfaces
    uvicorn.run(build_app(name), host=host, port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
