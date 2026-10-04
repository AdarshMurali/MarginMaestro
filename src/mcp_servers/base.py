"""Shared FastMCP setup (MM-128): the same server object runs over stdio
locally and over streamable HTTP on Cloud Run.

On Cloud Run each server is its own service, invokable only by the desk
assistant's identity (IAM, not a public URL), so the HTTP transport is:

- stateless + JSON responses: any instance can answer any request, which is
  what lets a service scale to zero between calls;
- without FastMCP's DNS-rebinding check: it only allows localhost Host
  headers by default, so every request through `*.run.app` would get 421.
  That check protects servers on a developer's machine from browsers; here
  Cloud Run's front end and IAM decide who reaches the container.
"""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def new_server(name: str) -> FastMCP:
    server = FastMCP(
        name,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @server.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok", "server": name})

    return server
