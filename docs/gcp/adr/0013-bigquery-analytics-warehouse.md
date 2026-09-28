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
