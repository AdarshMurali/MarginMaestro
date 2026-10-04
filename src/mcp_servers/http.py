"""Serves one MCP server over streamable HTTP (MM-128) -- the Cloud Run
entrypoint. Each read-only server is its own service, so IAM can grant the
desk assistant access per tool set:

    python -m mcp_servers.http market-data

The server name can also come from MCP_SERVER. Only read-only servers are
listed: the notifiers (Slack, ServiceNow) are never reachable from an LLM
over the network, so client contact stays behind the approval gate.
"""

import importlib
import os
import sys

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette

from api.logging_config import configure_logging

SERVERS = {
    "market-data": "mcp_servers.market_data",
    "rag": "mcp_servers.rag_retriever",
    "margin-status": "mcp_servers.margin_status",
}


def get_server(name: str) -> FastMCP:
    if name not in SERVERS:
        raise ValueError(f"Unknown MCP server {name!r}; expected one of: {', '.join(SERVERS)}")
    server: FastMCP = importlib.import_module(SERVERS[name]).mcp
    return server


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
