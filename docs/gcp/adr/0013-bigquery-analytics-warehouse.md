# ADR-0013: BigQuery as the analytics and audit warehouse

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

BigQuery must have a genuine role, not a decorative one. Cloud SQL (ADR-0011) remains the transactional store; BigQuery must never be on the approval/notification hot path.

## Decision

BigQuery is the **analytical and audit warehouse**, dataset `marginmaestro_analytics`, with these concrete use cases:

1. **Immutable audit and event history.** Every margin-call event and audit record lands via Pub/Sub BigQuery subscriptions (ADR-0012). Tables are partitioned by date and clustered by `counterparty_id`, and act as the long-term, tamper-evident record for regulators and reviewers.
2. **Threshold backtesting.** Multi-year daily prices for the `MARKET_UNIVERSE` tickers (yfinance, real data) + current CSA thresholds answer "on which historical days would each counterparty have received a call, and for how much?" The exposure math still runs in deterministic Python (ADR-0005); results are loaded into BigQuery for windowed analysis.
3. **Operational KPIs.** SLA met/breached rates, time-to-approval, dispute rates, escalation counts per counterparty and tier.
4. **Breach-likelihood model.** A **BigQuery ML** logistic regression on historical exposure/volatility features. It is advisory only and shown on the dashboard; it never raises or sizes a call.
5. **LLM and guardrail telemetry.** Tokens, cost, latency, Model Armor verdicts, blocked prompts, citation coverage per run.
6. **Governance showcase.** BigQuery **row access policies** (same counterparty scoping as Cloud SQL RLS), **policy tags** with dynamic masking on confidential columns, and Dataplex lineage (ADR-0015).

Dashboards: **Looker Studio** on top of BigQuery views, linked from the frontend.

## Consequences

- Free tier (1 TB queries, 10 GB storage per month) covers the demo if tables are partitioned and queries filter on the partition column. `require_partition_filter` is set on large tables.
- Post-trial: expected to stay within the free tier, so no fallback is needed. DuckDB is noted as an escape hatch only.

## Amendment (2026-10-06): as built in G7 (MM-139, MM-140, MM-141, MM-142)

The user unparked G7 on 2026-10-06 with a firmer scope than the original decision. What was built:

**Why BigQuery, honestly.** The live book is 8 counterparties; Cloud SQL handles that easily. The warehouse earns its place on *history*: daily exposure, positions and calls accumulate forever, and the reports (headroom trends, concentration, backtests) scan years of them. That is an analytical, append-mostly, columnar workload that doesn't belong on the transactional database behind the approval gate. To make the scale real rather than claimed, the warehouse also holds a **simulated historical book** (option B): 1,000 synthetic counterparties, ~50,000 positions over the real S&P 500 universe, five years (~1,256 trading days) of real Yahoo Finance closes — about 63M position-day rows, ~5.4 GB.

**Scope.**
- **Finance + app data only**, as a star schema: `fact_daily_exposure`, `fact_position_daily`, `fact_margin_call`, `fact_price_daily`; `dim_counterparty`, `dim_instrument`, `dim_csa_terms` (SCD2), `dim_date`; plus three pre-aggregated report tables (`rpt_counterparty_daily`, `rpt_concentration`, `rpt_margin_call`). Every row carries `book` = `live` | `historical-sim` (`dim_date` is the shared calendar).
- **Dropped from the original decision:** LLM/guardrail telemetry and raw audit/event mirrors (use cases 1 and 5; Cloud Logging and the append-only `audit_log` already cover them), and Pub/Sub → BigQuery subscriptions.
- **BigQuery ML (use case 4) is deferred.** No model is trained or served.
- **Warehouse only.** The simulated book never enters Cloud SQL and never reaches an LLM; its CSA terms are structured data drawn by code, not documents.

**How the numbers are made (ADR-0005).** The calc engine computes every figure. The backfill runs vectorized twins of `calc/` (proven equal by randomized tests) over the simulated book; the live load calls `calc/` directly with the CSA terms the orchestrator last extracted (read from its checkpoint — the load makes no LLM call). Calls follow the daily-run policy of ADR-0020: a standing breach is called unless a call is already open.

**Books and dates.** A date belongs to one book: `historical-sim` owns 2021-08-01 .. 2026-07-31, `live` every later date. Loads replace whole partitions — a `DELETE` filtered only on the partition column (BigQuery drops the partitions without scanning: 0 bytes) followed by a batch load (`WRITE_APPEND`; free). Re-running a load replaces, never duplicates, and never touches the other book. `WRITE_TRUNCATE` is never used: it would also remove the tables' row access policies.

**Access (mirrors Cloud SQL RLS, ADR-0011).**
- The app (mm-api-sa) and named loaders have a `TRUE` row access policy (needed for DML) and fine-grained read on the `confidential` policy tag.
- Firm-wide readers (e.g. the user's Tableau account) see every row with confidential columns masked (`DEFAULT_MASKING_VALUE`), unless also listed as unmasked readers.
- Scoped analysts see only their live counterparties: one row access policy per member, `book = 'live' AND counterparty_id IN (...)`.
- **The simulated book is firm-wide only.** It is a back-testing book with no analyst coverage, so scoped analysts never see it — in BigQuery (no policy grants it) or in the app's `/reports` (403).
- The in-app `/reports` endpoints query as mm-api-sa and apply the caller's RLS scope in SQL (`counterparty_id IN UNNEST(@ids)`), exactly as `user_session` does for Cloud SQL reads.

**Dashboards.** Instead of Looker Studio: an in-app **`/reports`** page (five reports, FastAPI + BigQuery, 10-minute server cache) and a **Tableau Desktop** guide (`docs/warehouse/tableau.md`: OAuth with the user's own Google account, extracts not live connections, report tables only).

**Cost guardrails ($0 target, ADR-0017).**
- Partitioning by date (by `book_key` for dimensions), clustering by counterparty (and ticker), `require_partition_filter` on the two big facts.
- Every query the code issues sets `maximum_bytes_billed` (capped at 8 GB by the client wrapper); report pages read `rpt_*` tables only.
- Batch loads only, no streaming inserts; no GCS staging (loads go from local gzip CSV, which is free).
- Storage ~6 GB logical (inside the 10 GiB free tier); query volume a few GB once for the backfill, then MBs per day (1 TiB free).
- The only paid option is a dedicated 4th Cloud Scheduler job ($0.10/month), off by default: the daily margin run triggers the load.

**Known limitations.** Survivorship bias (current S&P 500 constituents back-tested over five years), static positions, synthetic lifecycle timings in the simulated book, and the simplified settlement/return rules are documented in `docs/warehouse/README.md`.
