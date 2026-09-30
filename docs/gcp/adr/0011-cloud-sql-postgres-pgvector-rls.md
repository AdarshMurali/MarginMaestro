# ADR-0011: Cloud SQL for PostgreSQL with pgvector and row-level security

- **Status:** Accepted
- **Date:** 2026-09-28
- **Supersedes:** ADR-0004 (ChromaDB) and Azure SQL as the relational store

## Context

Three mandatory requirements meet here: a GCP-hosted relational store, a GCP-hosted vector store, and **row-level security**. Today relational data is on Azure SQL (`mssql+pyodbc`) and vectors are in ChromaDB. Alternatives for vectors were reviewed: Vertex AI Vector Search (always-on endpoint, expensive), Vertex AI RAG Engine (paid default backend), AlloyDB (expensive), Firestore / BigQuery vector search (cheap but a second store). The user chose **pgvector**.

## Decision

- **Cloud SQL for PostgreSQL** (smallest shared-core instance, single zone, no HA) replaces Azure SQL.
- **pgvector** in the same database replaces ChromaDB: a `rag_chunks` table with `embedding vector(768)` + an HNSW index, and the same metadata columns Chroma used (`counterparty_id`, `doc_type`, `effective_date`, `source_file`, `section`) for filtered, cited retrieval. `src/rag/retriever.py`'s interface is unchanged.
- **Row-level security** via Postgres `CREATE POLICY` on counterparty-scoped tables (`margin_calls`, exposures, collateral, trades, audit, `rag_chunks`):
  - Each request sets `app.user_role` and `app.counterparty_scope` with `SET LOCAL` inside its transaction, from the authenticated JWT (MM-57).
  - The app connects as a non-owner role with `FORCE ROW LEVEL SECURITY`, so the policy can't be bypassed by the app itself.
  - Roles: `viewer` / `approver` / `manager` see only their assigned counterparties; an `auditor` role gets read-only access to everything.
  - RLS on `rag_chunks` means retrieval can never surface another counterparty's CSA.
- **Connectivity:** Cloud Run → Cloud SQL via the Cloud SQL Python Connector with IAM database auth; no public IP allow-listing.
- **Driver:** `psycopg` (v3) for Postgres alongside `pyodbc` for SQL Server, chosen by `DB_DIALECT` (MM-104). LangGraph checkpoints keep using our own SQLAlchemy-based `SqlCheckpointSaver` on both databases (MM-105) — not the official Postgres checkpointer.

### As built (MM-106, 2026-09-30)

- **Scope values:** `app.scope` = `*` (approver, manager, auditor, internal jobs), a comma list of counterparty ids (a margin analyst's book, from table `user_counterparty_access`), or empty (sees nothing).
- **Role:** every Postgres transaction runs `SET LOCAL ROLE mm_app` (non-owner, no BYPASSRLS; tables have `FORCE ROW LEVEL SECURITY`), so even a superuser login is subject to the policies. The login user only needs membership in `mm_app` — in Cloud SQL the IAM app user is granted it in MM-108.
- **Where the scope comes from:** API read endpoints require a JWT (`require_user`) and open a session tagged with the caller's scope; a SQLAlchemy `after_begin` listener applies it. Sessions without a scope are internal jobs (orchestrator, event agent, loaders) and run firm-wide.
- **Policies:** `counterparties`, `portfolios`, `positions` (via its portfolio), `ratings`, `collateral_items`, `tickets`, `audit_log` (rows with no counterparty are firm-wide only), `orchestrator_checkpoints*` (counterparty = suffix of `thread_id`). Market data, reference rates, processed events and users are global. `rag_chunks` gets its policy with the pgvector store in G2.
- **Reads outside a session** (`/trace`, `/audit-log` fetch one run from the orchestrator) check the same rule in code and return **404** (not 403) when out of scope, so a run's existence isn't revealed.
- **Public:** `/public/stats` returns only totals (counts) for the landing page.
- **SQL Server** gets the access table but no row filtering — it's retired in G9.

## Rationale

- One store gives relational data, vectors and RLS together, and RLS then applies to RAG retrieval too.
- Postgres RLS is a real, database-enforced control — stronger than filtering in application code.

## Consequences

- **Migration work:** Alembic migrations re-validated for Postgres (SQL Server types, identity columns, `bootstrap.py`'s `mssql+pyodbc` URL); data re-seeded via `batch_loader` / `seed_users`; RAG corpus re-ingested (ADR-0009).
- Tests: RLS policy tests proving a user cannot read another counterparty's rows even with a crafted query.
- Local dev: `pgvector/pgvector` Postgres container replaces SQL Server + Chroma in Docker Compose.
- **Cloud SQL has no free tier — the largest post-trial cost.** Fallback (ADR-0017): Neon or Supabase free-tier Postgres (both support pgvector and RLS), a config-only swap of the connection string.
