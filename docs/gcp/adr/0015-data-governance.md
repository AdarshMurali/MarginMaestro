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

## Amendment (2026-10-05): as built in G8 without BigQuery (MM-135, MM-136, MM-137)

The user decided on 2026-10-05 to park Phase G7 (BigQuery). G8 was built without it. Each pillar now stands as follows.

| Pillar | Built now | Deferred with G7 |
|---|---|---|
| **Catalog** | `docs/data_catalog.yaml` covers every Cloud SQL table and column and every GCS document family, and is kept in sync by a unit test. Dataplex Universal Catalog holds one custom entry per table/family (entry group `marginmaestro`, entry type `marginmaestro-data-asset`, required aspect `marginmaestro-governance`: owner, class, freshness, source, confidential fields). Terraform reads the YAML, so nothing is maintained twice. | BigQuery tables |
| **Classification** | Per-column classes, plus an LLM handling for every confidential column (`pseudonymize` / `mask` / `deny`). The LLM data-class filter runs in `GuardedLLM` before every app prompt (`LLM_DATA_CLASS_FILTER=catalog` on Cloud Run) and on the MCP RAG tool's output. Labels `data-class` / `owner` are set on the Dataplex entries. | BigQuery policy tags and dynamic masking |
| **Access control** | Unchanged: Postgres RLS (ADR-0011), one service account per service. | BigQuery row access policies |
| **Lineage** | OpenLineage events to the Data Lineage API (`processOpenLineageRunEvent`), one run per margin call, best effort. Datasets use the same `custom:marginmaestro.*` names as the catalog entries, plus `gs://` for documents. | Automatic BigQuery lineage |
| **Data quality** | Fail-loud ingestion checks in code (unchanged). | Dataplex data-quality scans (they target BigQuery) |
| **Sensitive data** | A scheduled SDP inspection job over the documents bucket. Masking before LLM calls (MM-115) plus the data-class filter. | SDP scans of BigQuery tables |
| **Audit** | Cloud Audit Logs data access (ADMIN_READ / DATA_READ / DATA_WRITE) on Cloud SQL, Cloud Storage and Secret Manager. `audit_log` is append-only by grant: UPDATE/DELETE/TRUNCATE are revoked from `mm_app`. | BigQuery audit logs |
| **Retention** | A 30-day GCS retention policy on the documents bucket (unlocked). | BigQuery table expiration |

**Decisions.**
- **The classification sits in the data.** Confidential means "never reaches the model unmasked".
  - Counterparty identity is pseudonymized (the model never needs the legal name to read a CSA).
  - Position sizes and collateral values are masked.
  - Secrets and blobs are denied.
  - CSA *terms* (threshold, MTA, haircuts) are `internal`: extracting them is the CSA agent's job.
- **One recorded exception:** the desk assistant quotes call amounts to the analyst who owns the book (RLS-scoped). That is its purpose. The amount comes from code, and the model is told to quote it, not compute it. The exception is listed under `llm_exceptions` in the catalog, and a test pins that list.
- **Lineage carries ids, not values.** Lineage metadata leaves the database's RLS boundary, so amounts and names stay out of it.
- **The filter is on only on GCP** (`LLM_DATA_CLASS_FILTER`, default `none`). It reads the counterparty names from the database, and the AWS/local default stays unchanged.
- **The retention policy is not locked.** Locking is irreversible: the period could never be shortened, and the bucket couldn't be deleted before every object ages out. `rag.gcs_documents` skips unchanged files, so re-uploads stay idempotent under the policy.
- **SQL statement auditing (pgaudit) is off.** It would log every query. Cloud Audit Logs plus the append-only `audit_log` cover who read or changed data.

**Cost.** Dataplex catalog and lineage metadata are free up to 1 MiB (monthly average), then $2/GiB-month. About 21 entries and a few lineage events per call come to $0, or cents at worst. SDP storage inspection is free up to 1 GB a month; the corpus is under 100 KB. Cloud Audit Logs data access stays well under the 50 GiB/month free ingestion (estimate: under 100 MB). No Dataplex scans are created, because they are billed per DCU.

## Update (2026-10-06): the BigQuery items, built with G7 (MM-139, MM-142)

- **Catalog:** `docs/data_catalog.yaml` has a `warehouse_tables` section (every column classified; a test keeps it equal to `src/warehouse/schemas.py`), and Dataplex gets one custom entry per warehouse table (`custom:marginmaestro.bigquery.<table>`).
- **Classification → policy tags:** every `confidential` warehouse column (quantities, market values, collateral, headroom, legal names, call rationale) carries the `confidential` policy tag of the `MarginMaestro classification` taxonomy, with a `DEFAULT_MASKING_VALUE` data policy: masked readers see 0 / empty.
- **Access control:** BigQuery row access policies mirror Cloud SQL RLS (see the ADR-0013 amendment).
- **Still deferred:** Dataplex data-quality scans and SDP scans of BigQuery (billed per DCU / per GB; the loaders fail loud instead), BigQuery audit logs and table expiration (the warehouse is the long-term history).
