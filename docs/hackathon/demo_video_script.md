# Demo video script (3:00)

Record a screen with your phone visible (or cut to it). Log in beforehand. Keep `demo_online` on.

The "Say" column is a draft, not a rigid requirement — read it close to verbatim if you want
the tight 3:00, or paraphrase in your own words as long as you hit the same beats and timing.
Just keep every claim accurate (the LLM never computes a number — code does).

## 1. Recording setup

- **Screen recorder: Windows 11's Snipping Tool.** It has a built-in video recorder (camera
  icon in its toolbar) that captures screen + mic audio — no OBS or extra software needed.
  It doesn't capture system audio, which doesn't matter here since you're narrating live or
  dubbing over afterward anyway. (Game Bar, `Win+Alt+R`, is an equally fine alternative.)
- **Browser:** Chrome in a clean window, zoomed to 100%, no bookmarks bar — incognito or a
  fresh profile so no other tabs/extensions show.
- **Two browser windows side by side**, for the 1:05–1:35 beat — one logged in as `approver`,
  one as `analyst1` — so you can show Firestore's live push without refreshing either one.
- **Phone:** have WhatsApp open on the counterparty's test number *before* you start recording.
  If you can mirror your phone screen (scrcpy for Android, QuickTime for iPhone) that's cleaner
  on camera than hand-holding the phone.
- A separate narration take (recorded over the muted screen capture afterward) is usually
  easier than narrating live — see "Narration," below.

## 2. Before you hit record — dry run

Log into both roles and run the whole flow once, unrecorded, so Cloud Run is warm (no
cold-start lag on camera) and the agent/RAG calls are fast. Pick a ticker/counterparty pair
that hasn't already bred a pending call, so Approvals isn't cluttered with old test data.

## 3. Shot-by-shot

| Time | Screen / click path | Say |
|---|---|---|
| 0:00–0:20 | `/` (landing) → `/dashboard`, no clicks, just pan | "Margin desks still run calls by hand. MarginMaestro automates the whole lifecycle on Google Cloud: Gemini for reasoning, code for every number, a human for every decision." |
| 0:20–0:45 | Log in as `approver` → `/simulate`: "Price shock", ticker **HPE**, `% change` **-10**, submit | "A market shock comes in through Pub/Sub. The calculation engine reprices every book; agents read each client's CSA with RAG to get its threshold and minimum transfer." |
| 0:45–1:05 | `/agent-trace` → click the counterparty that just bred a call | "Each step is traced: exposure computed by code, CSA terms extracted by Gemini with citations, every call screened by Model Armor." |
| 1:05–1:35 | `/approvals` → approve the call; switch to the second browser window and show the status flip live, no refresh | "Nothing reaches a client without approval. Firestore pushes the status to every screen at once." |
| 1:35–2:00 | Cut to phone: WhatsApp notice + PDF → tap Acknowledge → back to `/approvals`, SLA now shows "met" | "The client gets a personalised notice: their own calculation and CSA terms. One tap acknowledges it, and the SLA closes. Miss the deadline and it escalates to ServiceNow." |
| 2:00–2:25 | `/desk` ("Ask the Desk"), as `analyst1` | Ask "Which of my calls are awaiting approval?" → "An ADK agent on Vertex AI Agent Runtime picks MCP tools, scoped to this analyst, with memory across sessions." |
| 2:25–2:45 | `/reports`, scroll the 5 tiles; flash a Tableau screenshot for 1–2s | "Every day lands in a BigQuery warehouse: 5 years, 62 million position-days. Here are exposure, headroom and stress reports." |
| 2:45–3:00 | Full-screen `docs/architecture/gcp-tech-architecture-blue.png` | "Cloud Run, Gemini, Firebase, Firestore, BigQuery, governed end to end. MarginMaestro." |

**Tips:**
- Do a dry run first, so the API and agent are warm and there are no cold starts on camera.
- Use `analyst1` for Ask the Desk and `approver` for approvals.
- If the counterparty you pick is elite-tier, approving needs `manager`'s second sign-off too
  — fine to show, but plan for the extra step so it doesn't surprise you mid-recording.

## 4. Narration

- **Live:** talk while you click, following the script loosely. Riskier — a mistake means
  re-recording the whole take.
- **Dubbed (recommended):** record the screen silently first, using the Time column as a
  pacing guide, then record voiceover separately watching the muted capture back, and mix in
  a simple editor (CapCut, DaVinci Resolve free, or even PowerPoint's record-narration-over-video).
  Much easier to get clean audio and fix a flubbed line without redoing the screen capture.

## 5. Editing

- Trim dead air (page loads, typing delays).
- Optional: captions for key terms (RAG, SLA, Model Armor) — helps non-technical judges.
- Keep it at or under 3:00; most rubrics penalize overlength.
- Export 1080p MP4.
