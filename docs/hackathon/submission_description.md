# Brief description (paste into the submission form)

MarginMaestro automates the margin-call lifecycle for a collateral desk on Google Cloud.

1. A market move reprices the book, and a deterministic engine recomputes exposure, variation margin and initial margin.
2. Agents read each client's CSA with RAG to apply its thresholds.
3. A breach becomes a call that a human must approve.
4. The client gets a personalised WhatsApp notice with a PDF of their calculation and CSA terms.
5. An SLA timer runs, and non-response escalates to ServiceNow, with a full audit trail and lineage.

**How we use Google:**
- **Gemini (2.5 Flash, Vertex AI):**
  - Extracts CSA terms with citations, drafts notices with placeholders (code inserts every figure), and powers "Ask the Desk".
  - Ask the Desk is a Google ADK agent on Vertex AI Agent Runtime with Sessions, Memory Bank and MCP tools, evaluated with Gen AI evaluation in CI.
  - Every call is screened by Model Armor and Sensitive Data Protection.
- **Cloud Run:**
  - The FastAPI orchestrator (LangGraph) and three read-only MCP tool servers, scaling to zero.
  - Driven by Pub/Sub, Cloud Scheduler and Cloud Tasks (one SLA timer per call).
- **Firebase:** the Next.js frontend runs on Firebase App Hosting. Firebase Auth custom tokens carry each analyst's scope.
- **Firestore:** real-time margin-call status. Every screen sees approvals, acknowledgements and escalations instantly, while the backend stays scaled to zero. Security rules enforce per-analyst scope.
- **Data:**
  - Cloud SQL Postgres + pgvector with row-level security.
  - A BigQuery finance warehouse: 5 years, 62M position-days, five risk reports.
  - Dataplex catalog, Data Lineage per call, audit logs.
  - Secret Manager, Cloud Trace/Logging/Monitoring, and Terraform for all infrastructure.
