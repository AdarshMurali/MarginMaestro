from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from rag.retriever import retrieve

mcp = FastMCP("rag-retriever")


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
) -> list[dict]:
    """Retrieve CSA/policy document chunks relevant to a query, optionally
    filtered by counterparty and document type. Each result carries citation
    metadata (source_file, section) for auditability. Returns an empty list
    when nothing matches -- distinct from the other MCP servers in this
    project, which raise a domain error when their underlying lookup comes
    up empty; a "no relevant documents" result is a normal outcome here,
    not a failure.
    """
    return [chunk.model_dump() for chunk in retrieve(query, counterparty_id, doc_type, top_k)]


if __name__ == "__main__":
    mcp.run()
