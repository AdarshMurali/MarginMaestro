# Pitch deck content — AI Builder Cup 2026 (template order)

Paste each section into the matching slide of the official template, then export to PDF.

## 1. Team Details
- **Team name:** MarginMaestro
- **Team leader:** Adarsh Murali (team: Adarsh Murali, Lavanya Dwarkanath)
- **Problem statement (BFSI: Intelligent Risk, Fraud & Financial Experiences):** Collateral and margin desks run the margin-call lifecycle by hand. Analysts watch exposures in spreadsheets, read each client's CSA to work out thresholds, draft notices, chase replies and escalate breaches. It is slow, error-prone, hard to audit, and a missed or wrong call is direct credit and regulatory risk.

## 2. Brief about the idea
MarginMaestro automates the margin-call lifecycle end to end on Google Cloud. A market move reprices the book. A deterministic engine recomputes exposure, and agents read each client's CSA with RAG over the legal documents. Breaches become calls that a human approves. The client gets a personalised notice on WhatsApp, an SLA timer runs, and non-response escalates to ServiceNow, with a full audit trail and lineage throughout.

## 3. Opportunities
- **How is it different?**
  - **Gemini for reasoning, code for math.** Every amount is computed by deterministic Python; Gemini reads CSAs, drafts text and answers questions, with amounts inserted by code and never generated.
  - **A human approves every client message.** Approval is a gate in the workflow, enforced twice: elite clients need a manager's second signature.
  - **Guardrails on every LLM call:** Model Armor, Sensitive Data Protection masking, and a data-class filter driven by the data catalog.
- **How does it solve the problem?** Detection to client notice takes seconds instead of hours. Thresholds and terms come from the client's own CSA, with citations. SLA timers and escalation run automatically.
- **USP:** a *governed* agentic system for a regulated workflow. Row-level security follows each analyst everywhere (app, MCP tools, BigQuery, Firestore). Every call is traceable from price event to notification, and Gemini is evaluated in CI.

## 4. List of features
1. Live market prices → impact detection → margin-call runs with no human trigger (Pub/Sub + Cloud Scheduler).
2. Daily margin run plus an intraday materiality gate (only material moves raise calls); one open call per counterparty.
3. CSA-aware calculation: RAG over each client's CSA gives threshold, MTA, haircuts and rating triggers, with citations.
4. Human approval gate; second signature for elite clients.
5. **WhatsApp notice** with a **personalised PDF** (calculation breakdown and the client's CSA terms). The client taps **Acknowledge** to meet the SLA.
6. SLA timer per call (Cloud Tasks); breach → **ServiceNow incident** + Slack alert.
7. **"Ask the Desk":** a Gemini ADK agent on Vertex AI Agent Runtime with Sessions, Memory Bank and read-only MCP tools, scoped to the analyst.
8. **Real-time status** across all screens via Firestore.
9. **BigQuery finance warehouse:** 5 years of history, 62M position-days, five risk reports in the app plus Tableau.
10. Governance: Dataplex catalog, Data Lineage per call, data-access audit logs, append-only audit trail, Gen AI evaluation in CI.

## 5. Process flow
Price tick (Cloud Scheduler → Pub/Sub) → Event Agent detects a material move → Orchestrator (LangGraph on Cloud Run):
1. compute exposure (code)
2. read CSA terms (RAG + Gemini)
3. evaluate breach (code)
4. **approval gate (human)**
5. notify: WhatsApp PDF + Slack
6. SLA timer (Cloud Tasks)
7. Acknowledge → SLA met, *or* timeout → escalate (ServiceNow)

Every step goes to: the audit log, lineage, the BigQuery facts and the Firestore live status.

*(Use the diagram in `docs/architecture/` or redraw this flow.)*

## 6. Wireframes / mock diagrams (optional)
Use real screenshots instead (slide 10).

## 7. Architecture diagram
Use `docs/architecture/gcp-tech-architecture-multicolor.png`. Add Firebase App Hosting and Firestore if they're missing.

## 8. Technologies
- **Gemini 2.5 Flash on Vertex AI:** CSA extraction, notice drafting, desk assistant.
- **Vertex AI Agent Runtime + Google ADK:** Sessions, Memory Bank, Gen AI evaluation.
- **Cloud Run:** API, MCP servers.
- **Firebase App Hosting** (frontend), **Firestore** (real-time status), **Firebase Auth** custom tokens.
- **Cloud SQL Postgres + pgvector** (RLS), **Cloud Storage**.
- **Pub/Sub**, **Cloud Tasks**, **Cloud Scheduler**.
- **BigQuery** warehouse, **Dataplex** catalog, **Data Lineage**, **Sensitive Data Protection**, **Model Armor**.
- **Secret Manager**, **Cloud Trace / Logging / Monitoring**, **Terraform**, **GitHub Actions** (keyless WIF), **SonarCloud**, **CodeQL**, **Trivy**.
- Python (FastAPI, LangGraph, MCP), Next.js, WhatsApp Cloud API, Slack, ServiceNow, Tableau.

## 9. Estimated implementation cost
- **Total spent over ~10 days of building and running:** about ₹880 of trial credits.
- **Idle cost about ₹0:** everything scales to zero; Cloud SQL is the only always-on item (~₹28/day while the demo is on).
- **Per margin call:** ~₹0.05–0.10 in LLM cost.
- **Warehouse:** about 6 GB, inside BigQuery's free tier.

## 10. Snapshots
Dashboard, Approvals, Margin-call trace, Reports, Ask the Desk, the WhatsApp notice + PDF on a phone, Tableau dashboards, the lineage graph.

## 11. Performance / benchmarking
- **Tests:** 1,600+ automated tests, ~98% coverage; quality and security gates on every merge (SonarCloud, CodeQL, Trivy, Checkov, gitleaks).
- **AI quality:** Gen AI evaluation on 12 golden questions: 12/12 deterministic checks (tool choice, refusals, scope, every amount traceable to a tool); hallucination score 0.94, response quality 0.90.
- **End to end:** approval → WhatsApp delivered in ~2 s; client Acknowledge → SLA met in under 1 s.
- **Daily margin run:** all counterparties in ~90 s.
- **Desk assistant:** 4–8 s per answer when warm.
- **Warehouse:** 62.4M position-day rows; reports read pre-aggregated tables in about a second.

## 12. Future development
- BigQuery ML breach-likelihood score.
- Real counterparty contacts and a production WhatsApp number.
- More asset classes and CSA types.
- Agent Identity once Model Armor supports regional mTLS.
- Multi-desk tenancy.

## 13. Links
- **GitHub:** https://github.com/AdarshMurali/MarginMaestro
- **Demo video (3 min):** *(add after recording)*
- **Product:** https://marginmaestro-web--marginmaestro-demo.us-central1.hosted.app (also https://marginmaestro.vercel.app)
- **Demo logins:** approver / manager / analyst1 (passwords in the README)
