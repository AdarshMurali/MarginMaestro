# ADR-0006: Use OpenAI `text-embedding-3-small` for RAG embeddings (supersedes ADR-0004's local-embeddings choice)

- **Status:** Accepted
- **Date:** 2026-07-26

## Context

ADR-0004 chose local `BAAI/bge-small-en-v1.5` embeddings specifically to protect the (paid) OpenAI budget, on the assumption that the LLM itself would run locally via Ollama. Two things changed during Phase 3 planning:

1. This development machine can't run Ollama viably (8GB total RAM, already tight — see the WSL2 memory-cap troubleshooting from Phase 1). The CSA-RAG Agent (MM-26) needs OpenAI `gpt-4o-mini` regardless.
2. Query embeddings and document embeddings **must** come from the same model — different embedding models produce different vector spaces (and usually different dimensionality), so similarity search across mismatched embeddings isn't just worse, it's meaningless. Once the agent's LLM call goes to OpenAI, keeping embeddings local doesn't save meaningful cost — it only adds a second model integration and a local memory footprint on an already memory-constrained machine.

## Decision

Use OpenAI `text-embedding-3-small` for both document ingestion (MM-24) and query-time retrieval (MM-25), replacing local `BAAI/bge-small-en-v1.5`.

## Rationale

- Cost is negligible at this project's corpus size (a curated set of ~9 short documents, a few hundred chunks at most) — pennies, not a meaningful budget item.
- Avoids loading a local embedding model into an already memory-constrained process (8GB host, WSL2 capped at 3GB for Docker).
- One vendor (OpenAI) for both embeddings and agent reasoning is operationally simpler than mixing local + hosted.
- Query/document embedding consistency is guaranteed by construction — there's only one embedding call path in the codebase, not two that could drift.

## Alternatives

- **Keep local BGE for embeddings, OpenAI only for the LLM call:** rejected — still requires hosting/loading a local model on a constrained machine, for negligible cost savings once the LLM call already leaves the local machine.
- **Ollama for the LLM call:** rejected for this project — not installed, and the host machine's specs make it an unreliable choice on top of everything else already running (Docker Desktop, VS Code, browser).

## Consequences

- `sentence-transformers` is no longer needed as a runtime dependency; `openai` (official SDK) is added instead.
- Ingestion and retrieval both require network access and a configured `OPENAI_API_KEY` — there's no fully-offline path for the RAG pipeline anymore. This is an acceptable tradeoff for a demo/portfolio project's corpus size.
- `CLAUDE.md`'s tech stack table and `docs/DATA_SOURCES.md` §4 are updated to reflect OpenAI embeddings as the current choice.
- `CLAUDE.md`'s LLM line is also updated: `gpt-4o-mini` is now the practical default for *this project's development* (not just the "optional" path), since Ollama isn't viable on this machine's specs. `LLM_PROVIDER=ollama` remains a supported `Settings` value for anyone running on hardware where it works — this is a development-environment constraint, not a claim that Ollama is architecturally unsound.
