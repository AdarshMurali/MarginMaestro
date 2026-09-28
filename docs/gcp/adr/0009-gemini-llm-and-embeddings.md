# ADR-0009: Use Gemini on Vertex AI for reasoning and embeddings

- **Status:** Accepted
- **Date:** 2026-09-28
- **Supersedes:** ADR-0006 (OpenAI embeddings) and the `gpt-4o-mini` default in `CLAUDE.md`

## Context

ADR-0006 moved to OpenAI (`gpt-4o-mini` + `text-embedding-3-small`) because Ollama wasn't viable on the dev machine. With GCP as the primary platform (ADR-0008), the LLM should be Gemini.

## Decision

- **Reasoning / drafting:** Gemini **Flash** tier on **Vertex AI**, exact model version pinned in `Settings` (`GEMINI_MODEL`) — never an unversioned alias.
- **Embeddings:** Vertex AI **`gemini-embedding-001`** with `output_dimensionality=768`, so vectors fit pgvector's HNSW index limit (2,000 dims) — see ADR-0011.
- New `LLM_PROVIDER=vertex` branch in `Settings`, alongside the existing `openai` / `ollama` branches (kept as fallbacks, ADR-0017).
- Auth via the Cloud Run service account (ADC) — no API key stored.
- Use Gemini **structured output** (response schema) for every LLM call whose result feeds orchestration, validated again by Pydantic.

## Rationale

- Vertex AI (unlike the AI Studio free tier) does not use prompts to train models and sits inside the project's IAM/audit boundary — needed for the governance requirement (ADR-0015).
- Query and document embeddings must share one model (same rule as ADR-0006), so the whole RAG corpus is re-embedded once.

## Consequences

- Full re-ingestion of the RAG corpus into pgvector with the new embedding model.
- A golden regression set of margin-call scenarios runs against the new model before cut-over (assert on orchestration decisions, not prose — per `CLAUDE.md` rule 4).
- Vertex AI usage is billable (covered by trial credits). Post-trial fallback: AI Studio free tier (synthetic data only) or the existing OpenAI adapter — decided at the month-2 review (ADR-0017).
- Gemini Live API is **out of scope** — reviewed and rejected: margin calls must be written, asynchronous and auditable; voice adds little to the core flow.
