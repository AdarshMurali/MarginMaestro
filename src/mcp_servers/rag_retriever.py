from typing import Annotated

from mcp.server.fastmcp import Context
from pydantic import Field

from config.settings import get_settings
from mcp_servers.base import new_server
from mcp_servers.caller import caller_scope, get_mcp_session_factory, scoped_factory
from persistence.db.rls import FIRM_WIDE, can_see
from ports.vector_store import VectorStore
from rag.retriever import retrieve

mcp = new_server("rag-retriever")


@mcp.tool()
def retrieve_document_chunks(
    query: Annotated[str, Field(description="Natural-language question to retrieve chunks for.")],
    counterparty_id: Annotated[
        str | None,
        Field(
            description="Scope to one counterparty's own docs plus shared/global docs, e.g. 'CP-3'."
        ),
    ] = None,
    doc_type: Annotated[
        str | None,
        Field(description="One of: csa, policy, disputes, exceptions, escalation."),
    ] = None,
    top_k: Annotated[int, Field(description="Maximum chunks to return.", ge=1)] = 5,
    ctx: Context | None = None,
) -> list[dict]:
    """Retrieve CSA/policy document chunks relevant to a query, optionally
    filtered by counterparty and document type. Each result carries citation
    metadata (source_file, section) for auditability. Returns an empty list
    when nothing matches -- distinct from the other MCP servers in this
    project, which raise a domain error when their underlying lookup comes
    up empty; a "no relevant documents" result is a normal outcome here,
    not a failure. Only documents the calling analyst may see are returned.
    """
    scope, vector_store = _scoped_store(ctx)
    if scope == FIRM_WIDE:
        chunks = retrieve(query, counterparty_id, doc_type, top_k)
    else:
        chunks = retrieve(query, counterparty_id, doc_type, top_k, vector_store=vector_store)
    # Shared documents have counterparty_id "". On pgvector the database
    # already filtered by scope; this also covers Chroma, which has no RLS.
    return [
        chunk.model_dump()
        for chunk in chunks
        if not chunk.counterparty_id or can_see(scope, chunk.counterparty_id)
    ]


def _scoped_store(ctx: Context | None) -> tuple[str, VectorStore | None]:
    """The caller's scope, plus a pgvector store whose sessions carry it."""
    if ctx is None:
        return FIRM_WIDE, None
    factory = get_mcp_session_factory()
    scope = caller_scope(ctx, factory)
    if scope == FIRM_WIDE or get_settings().vector_store != "pgvector":
        return scope, None
    from adapters.pgvector_adapter import PgVectorStore

    return scope, PgVectorStore(scoped_factory(factory, scope))


if __name__ == "__main__":
    mcp.run()
