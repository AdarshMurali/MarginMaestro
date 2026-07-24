# ADR-0004: Use ChromaDB as the RAG vector store

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

The RAG pipeline needs a vector store for CSA/policy/exception/escalation/dispute documents. Constraints: free, easy to run in a container, sufficient for a modest document volume. Options: ChromaDB, FAISS, pgvector (Postgres), managed services (paid).

## Decision

Use **ChromaDB** with **local `BAAI/bge-small-en-v1.5` embeddings** (free, no per-call cost). Chunks carry metadata (`counterparty_id`, `doc_type`, `effective_date`, `source_file`, `section`) for filtered retrieval.

## Rationale

- Free and container-friendly; minimal setup.
- Metadata filtering supports precise, cited retrieval per counterparty/doc type.
- Local embeddings protect the (paid) OpenAI budget — embeddings are where per-call cost quietly accumulates.

## Alternatives

- **pgvector** is a strong alternative if we want vectors co-located with relational data (one fewer moving part). Reconsider if operational simplicity favours a single store.
- **FAISS** is lower-level (no built-in metadata/persistence ergonomics).
- Managed vector DBs rejected on cost.

## Consequences

- One extra container (Chroma) in the local stack.
- Switching to pgvector later is contained (retriever is behind an MCP tool interface).
