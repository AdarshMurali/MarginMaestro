# CLAUDE.md — Agent Operating Guide

> **Read this first, every session.** This is the operating contract for anyone (human or Claude agent) working on MarginMaestro. Keep it lean and high-signal. When a convention solidifies or a recurring mistake appears, add a one-line rule here rather than re-explaining each session.

## What this project is

**MarginMaestro** automates the end-to-end **margin call lifecycle** using **LLM agent orchestration**, a **RAG pipeline** over legal/policy documents, and a **real-time streaming** backbone. A market event moves prices → exposure is recomputed → if a threshold breaks, a margin call is raised, a human approves it, the client is notified via Slack, an SLA timer runs, and non-response escalates to Jira — with a full audit trail throughout.

It is a **portfolio / proof-of-concept** built to production-engineering standards. Data is **free + synthetic**. Margin math is **directionally correct**, not a certified risk model.

## Golden rules (do not violate)

1. **LLM for reasoning, code for math.** NEVER compute MTM, VM, IM, thresholds, or any number with the LLM. Financial calculations are deterministic Python with exhaustive unit tests. The LLM is only for: RAG over documents, dispute rationale, entity/impact judgment, and drafting notification text. (See `docs/adr/0005`.)
2. **No secrets in code.** All config/secrets via env vars locally and **AWS Parameter Store** in deployed envs. Never hardcode keys, tokens, or connection strings. `.env` is git-ignored; only `.env.example` is committed.
3. **One story at a time, fully finished.** Follow the loop in `CONTRIBUTING.md`. Do not start the next story until the current one meets the Definition of Done and `docs/PROGRESS.md` is updated.
4. **Tests are mandatory.** Every story ships with tests. Coverage must stay ≥ 80%. Mock the LLM in tests; assert on orchestration decisions, not model prose.
5. **Human-in-the-loop is a feature.** A margin call is never fired fully autonomously — there is always an approval gate before a client-facing call goes out.
6. **Keep the frontend thin.** It visualizes state; it holds no business logic.
7. **Curated demo universe.** Entity/impact mapping runs over a small fixed set of tickers/counterparties (see `MARKET_UNIVERSE`), not open-world news. Do not over-promise general entity resolution.

## Tech stack (don't swap without an ADR)

- **Orchestration:** LangGraph (explicit state-graph over agents).
- **LLM:** OpenAI `gpt-4o-mini` (usage-minimized) for this project's development — Ollama isn't viable on the dev machine's specs (see ADR-0006). `LLM_PROVIDER=ollama` remains supported in `Settings` for anyone running on hardware where it works.
- **Embeddings:** OpenAI `text-embedding-3-small` (see ADR-0006 — supersedes the earlier local BGE choice; query/document embeddings must share one model, and Ollama isn't viable on the dev machine anyway).
- **RAG store:** ChromaDB. **Relational:** Azure SQL (free tier).
- **Streaming:** Kafka (Redpanda locally). Flink is **deferred** — only if a genuine windowed job is built (see `docs/adr/0003`).
- **API:** FastAPI. **Frontend:** Next.js on Vercel.
- **Tools exposed as MCP servers:** market data, Jira, Slack, RAG retriever.
- **Notifications:** Slack. **Ticketing/escalation:** Jira *(planned swap to ServiceNow for this specific feature in Phase 6 — see `docs/ROADMAP.md`'s Phase 6 note; needs an ADR before it actually changes)*. **Secrets:** AWS Parameter Store.
- **CI/CD:** GitHub Actions + Docker Hub. **Quality:** SonarCloud + pytest-cov. **IaC:** Terraform.

## Commands (keep these current)

```bash
# Local stack
docker compose up -d          # Kafka/Redpanda, Chroma, app services

# Python
make test                     # all tests
make test-unit                # fast unit tests
make cov                      # coverage report (target >= 80%)
make lint                     # ruff + black --check + mypy
make fmt                      # auto-format

# Simulator
make simulate SCENARIO=price_shock   # inject a synthetic market event
```
> If a command here is wrong or missing, fix it in this file as part of your story.

## Project conventions

- **Language/runtime:** Python 3.11+ (backend), TypeScript/Next.js (frontend).
- **Validation:** Pydantic models at every external boundary (feeds, API, tool IO).
- **Structure (target):** `src/agents/`, `src/calc/`, `src/streaming/`, `src/rag/`, `src/api/`, `src/mcp/`, `src/persistence/`, `src/config/` (shared Pydantic settings — env locally, AWS Parameter Store when deployed; added in MM-9), `tests/`, `infra/` (Terraform), `frontend/`.
- **Errors:** fail loud in calc/agent code; never silently swallow. Events are processed **idempotently** (replaying the same event must not double-raise a call).
- **Logging:** structured JSON logs; every agent action is logged with a correlation id for the margin-call run.
- **Commits:** conventional commits + Jira key, e.g. `feat(calc): add VM computation [MM-12]`.

## Where to look

- `docs/ARCHITECTURE.md` — lifecycle, agent mesh, streaming, data flow.
- `docs/AGENTS.md` — each agent's responsibility, inputs, outputs, tools.
- `docs/DATA_SOURCES.md` — structured vs unstructured data map + free sources.
- `docs/ROADMAP.md` — phased plan, mapped to Jira epics/stories with DoD.
- `docs/PROGRESS.md` — **living handoff log; update at the end of every story.**
- `docs/adr/` — architecture decision records (the *why* behind choices).

## Handoff protocol

At the end of every story, append a handoff entry to `docs/PROGRESS.md` using the template there: **Done / Decisions / Changed / Known issues / Next step.** This is how the next session resumes without context loss. Treat it as part of the Definition of Done, not optional paperwork.
