from mcp.server.fastmcp import FastMCP

from rag.retriever import retrieve

mcp = FastMCP("rag-retriever")


@mcp.tool()
def retrieve_document_chunks(
    query: str,
    counterparty_id: str | None = None,
    doc_type: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    """Retrieve CSA/policy document chunks relevant to a query, optionally
    filtered by counterparty and document type. Each result carries citation
    metadata (source_file, section) for auditability.
    """
    return [chunk.model_dump() for chunk in retrieve(query, counterparty_id, doc_type, top_k)]


if __name__ == "__main__":
    mcp.run()
