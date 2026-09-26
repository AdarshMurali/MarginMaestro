# GCP Architect Questions & AI Governance Checklist

> Prep notes for the Google Cloud technical-architect session (hackathon, 2026-09). Tied to Phase 14 in `docs/ROADMAP.md` (GCP portability) — additive, not a replacement for the AWS primary stack.

## Questions for Google architects

- **Kafka → GCP:** We stream price ticks through Kafka (Redpanda) with consumer offsets and a dead-letter topic. Would you use Managed Service for Apache Kafka to keep our code as is, or move to Pub/Sub, and what do we give up on ordering and exactly-once?
- **Long-running consumers on Cloud Run:** Our Event Agent is an always-on Kafka consumer, and our SLA timers pause for minutes. Does that fit Cloud Run (always-on CPU, min instances), or should it go on GKE Autopilot or Cloud Run worker pools?
- **LangGraph state and human approval:** Our LangGraph runs save a checkpoint and pause for a human to approve the margin call. What's the recommended store for durable agent state on GCP (Cloud SQL, Firestore, AlloyDB), and does Vertex AI Agent Engine support a pause-and-resume approval step?
- **Gemini vs. gpt-4o-mini:** We use the LLM only for RAG answers, drafting notices and dispute rationales, never for the math. Which Gemini model fits that at the lowest cost, and how do we get strictly structured JSON output that we can validate?
- **Embeddings and vector store:** We use ChromaDB with OpenAI embeddings and filter by counterparty and document type. Is Vertex AI Vector Search, AlloyDB with pgvector, or Vertex AI Search the best fit for a small corpus (tens of documents) with strict metadata filtering and citations?
- **Grounding and citations:** Every CSA term we return (threshold, minimum transfer amount, haircuts) must cite its source text. Can Vertex AI's grounding or its RAG Engine return chunk-level citations reliably enough for regulated finance?
- **Relational DB:** We're on Azure SQL (SQL Server dialect) through SQLAlchemy. Is Cloud SQL for SQL Server the low-effort path, or would you push AlloyDB/Postgres, and what are the migration traps with Database Migration Service?
- **Observability:** We already emit OpenTelemetry traces (one span per lifecycle step) and Prometheus metrics. Can Cloud Trace and Managed Service for Prometheus take these as they are, with no code changes?
- **Secrets and identity:** We move from AWS Secrets Manager to Secret Manager. What's the best practice for Workload Identity so Cloud Run reaches Secret Manager and Vertex AI with no service-account keys at all?
- **BFSI compliance:** For a margin-call system handling counterparty data, which GCP controls (VPC Service Controls, CMEK, data residency, Assured Workloads) would a bank reviewer expect to see, even in a proof of concept?
- **Cost for a demo:** What's the cheapest setup to keep this demo live (scale-to-zero, free tiers, hackathon credits), given a Kafka consumer and a database that ideally shouldn't run 24/7?

### Governance follow-ups to ask

- **Catalog:** Is Dataplex Universal Catalog the GCP equivalent of Databricks Unity Catalog for us, and can it catalog Cloud SQL tables and Vertex AI vector indexes, not just BigQuery?
- **Lineage for AI outputs:** Can Dataplex data lineage trace a margin call back to the source price tick and the CSA chunk that set its threshold, or do we keep that in our own audit table?
- **Prompt safety:** Where does Model Armor sit in a LangGraph + Gemini flow (per call, or at a gateway), and does it catch prompt injection hidden inside retrieved RAG documents?

## Data governance we have not implemented yet

What exists today: an immutable audit table with a correlation id per run, Pydantic validation at boundaries, secrets in AWS Secrets Manager, and CSA citations. What's missing, with the GCP-native option:

| Gap | GCP option | Why it matters here |
|---|---|---|
| **Central data catalog** (Unity Catalog equivalent) | **Dataplex Universal Catalog** — business glossary, data owners, and search across Cloud SQL, BigQuery, GCS | Nobody can find out what `positions`, `collateral` or `csa` documents mean, who owns them, or how fresh they are |
| **Data lineage** | Dataplex lineage (automatic for BigQuery; OpenLineage API for custom pipelines) | Tracing a margin call → exposure → price tick → source feed, end to end |
| **Column-level security / masking** | BigQuery policy tags and dynamic data masking; Cloud SQL IAM auth + views | Counterparty names and exposures should be masked for non-privileged roles |
| **Sensitive-data discovery** | **Sensitive Data Protection (Cloud DLP)** — scans GCS, BigQuery and prompts | Detects PII or account numbers leaking into RAG documents, logs or LLM prompts |
| **Data quality rules** | Dataplex auto data quality (null / range / freshness checks) | A stale or negative price should fail loudly before it moves an exposure |
| **Data classification labels** | Resource labels + policy tags (public / internal / confidential) | Drives who can access what and which data may go to the LLM |
| **Retention & legal hold** | GCS object retention locks, bucket lock, BigQuery table expiration | The audit trail must be tamper-proof and retained per policy |
| **Perimeter controls** | VPC Service Controls around Vertex AI, Cloud SQL, GCS | Stops data exfiltration even with stolen credentials |
| **Encryption key control** | CMEK via Cloud KMS | Banks expect customer-managed keys |
| **Access audit** | Cloud Audit Logs (Data Access logs on), Access Transparency | Records who read counterparty data, including Google staff access |

## AI application hygiene on GCP

**Identity & secrets**
- One service account per workload (API, Event Agent, orchestrator), least-privilege roles, no downloaded JSON keys — use Workload Identity.
- All secrets in Secret Manager with rotation; nothing in env files baked into images.

**Model & prompt safety**
- **Model Armor** to screen prompts and responses for prompt injection, jailbreaks and sensitive-data leakage — especially for RAG content, which is untrusted input.
- Gemini safety settings set explicitly, not left at defaults.
- Structured output (response schema) + Pydantic validation on every LLM response; reject and fail loud on schema violations.
- Keep the golden rule: the LLM never produces a number that reaches `calc/` (ADR-0005).

**Grounding & quality**
- Every RAG answer must carry citations; fail the answer if a citation is missing.
- **Vertex AI Gen AI evaluation service** for regression evals (retrieval precision, faithfulness) run in CI on prompt or model changes.
- Pin model versions (e.g. a specific `gemini-2.x` version, not an alias) so behaviour doesn't drift silently.

**Data sent to the model**
- Run DLP de-identification on anything sent to the LLM that could contain PII.
- Confirm the data-governance terms: Vertex AI does not train on customer data; choose the region for data residency.
- Only send the minimum context needed (the retrieved chunks, not whole tables).

**Observability & audit**
- Log prompt, model version, retrieved chunk ids, token counts and latency per call, linked by correlation id (no raw secrets or PII).
- Cloud Trace spans per agent step; alerts on LLM error rate, latency and token spend.
- Keep the human-approval decision (who, when, what changed) in the immutable audit trail.

**Cost & abuse controls**
- Budget alerts and quota caps on Vertex AI; rate-limit the public API.
- Cache repeated RAG queries; use the smallest Gemini model that passes the evals.

**Supply chain**
- Artifact Registry with vulnerability scanning; Binary Authorization so only CI-signed images deploy to Cloud Run.
- Org policy constraints: no public IPs, no service-account key creation, restricted resource locations.
