# Demo video script (3:00)

Record a screen with your phone visible (or cut to it). Log in beforehand. Keep `demo_online` on.

| Time | Screen | Say |
|---|---|---|
| 0:00–0:20 | Landing / Dashboard | "Margin desks still run calls by hand. MarginMaestro automates the whole lifecycle on Google Cloud: Gemini for reasoning, code for every number, a human for every decision." |
| 0:20–0:45 | Simulate Event (approver): HPE −10% | "A market shock comes in through Pub/Sub. The calculation engine reprices every book; agents read each client's CSA with RAG to get its threshold and minimum transfer." |
| 0:45–1:05 | Agent Trace for one call | "Each step is traced: exposure computed by code, CSA terms extracted by Gemini with citations, every call screened by Model Armor." |
| 1:05–1:35 | Approvals → Approve CP-2; second browser updates instantly | "Nothing reaches a client without approval. Firestore pushes the status to every screen at once." |
| 1:35–2:00 | Phone: WhatsApp notice + PDF → tap Acknowledge; Approvals shows SLA met | "The client gets a personalised notice: their own calculation and CSA terms. One tap acknowledges it, and the SLA closes. Miss the deadline and it escalates to ServiceNow." |
| 2:00–2:25 | Ask the Desk | Ask "Which of my calls are awaiting approval?" → "An ADK agent on Vertex AI Agent Runtime picks MCP tools, scoped to this analyst, with memory across sessions." |
| 2:25–2:45 | Reports (+ Tableau flash) | "Every day lands in a BigQuery warehouse: 5 years, 62 million position-days. Here are exposure, headroom and stress reports." |
| 2:45–3:00 | Architecture slide | "Cloud Run, Gemini, Firebase, Firestore, BigQuery, governed end to end. MarginMaestro." |

**Tips:**
- Do a dry run first, so the API and agent are warm and there are no cold starts on camera.
- Use `analyst1` for Ask the Desk and `approver` for approvals.
