# ADR-0015: Mandatory data governance on GCP

- **Status:** Accepted
- **Date:** 2026-09-28
- **Replaces:** old ROADMAP Phase 15 "OPTIONAL: Data governance" (now mandatory)

## Context

Governance today is limited to the audit table, Pydantic validation at boundaries, secrets management and CSA citations. It must become a complete, demonstrable model.

## Decision

| Pillar | Implementation |
|---|---|
| **Catalog** | **Dataplex Universal Catalog**: every Cloud SQL table, BigQuery table and GCS document family registered with owner, description, sensitivity and freshness. Catalog source-of-truth also kept in-repo (`docs/data_catalog.yaml`) and synced. |
| **Classification** | Three classes: `public` / `internal` / `confidential`. Counterparty identity, exposures and collateral are `confidential`. Implemented as BigQuery **policy tags** + resource labels. Only allowed classes may be sent to the LLM (enforced by the guardrail layer, ADR-0014). |
| **Access control** | Postgres RLS (ADR-0011) + BigQuery row access policies + column-level masking via policy tags; least-privilege IAM, one service account per service, no user-managed keys. |
| **Lineage** | Per margin call: source price event → impact set → calc inputs → CSA chunk ids → call → approval → notification, recorded in the audit trail and emitted to **Dataplex lineage** (OpenLineage API). |
| **Data quality** | Fail-loud checks at ingestion (stale/zero/negative price, missing FX, collateral without haircut) in code; **Dataplex data quality scans** on BigQuery tables. |
| **Sensitive data** | **Sensitive Data Protection** scans on GCS documents and BigQuery tables; masking before LLM calls. |
| **Audit** | **Cloud Audit Logs** (admin + data access) on Cloud SQL, BigQuery, GCS, Secret Manager; application audit trail stays append-only (enforced by DB grants). |
| **Retention** | Documented retention per class; **GCS bucket retention policy** for source documents; BigQuery table expiration for telemetry; audit history retained for the demo lifetime. |
| **Encryption** | Google-managed encryption by default. CMEK (Cloud KMS) documented as the production-grade option, not enabled for the demo (cost). |

## Consequences

- Governance stories ship with tests: quality rules, masking rules, the LLM data-class filter, and RLS/row-policy isolation.
- `docs/ARCHITECTURE.md` and `docs/DATA_SOURCES.md` gain a governance section.
- Dataplex scans are billed per processing — post-trial fallback is governance-as-code (in-repo catalog + code-level checks), with BigQuery policy tags kept since they are free.
