# MarginMaestro — Enhancement Backlog (good-to-have)

> **Status:** Ideas only, not scheduled (2026-10-01). Nothing here is in `docs/ROADMAP.md` or `docs/gcp/GCP_ROADMAP.md` yet. Review each item before moving it into a roadmap phase with a Jira key.
>
> **Ground rules still apply:** every number is computed in deterministic Python (ADR-0005). The LLM only explains, summarises or drafts. Human approval stays in front of any client-facing action.

## Why this file exists

The demo shows the *mechanics* of a margin call: breach → call → approval → notification → SLA → escalation. Real margin disasters weren't caused by slow mechanics. They came from risks the mechanics didn't see: **concentration, illiquidity, hidden leverage, stress spikes and clients who can't pay**. The items below add small, realistic controls for those risks. The demo can then tell a story like *"MarginMaestro would have flagged Archegos days before the fire sale."*

---

## 1. Real-world cases these items address

| Case | What happened | Lesson | Items |
|---|---|---|---|
| **Archegos Capital (Bill Hwang, March 2021)** | Highly leveraged, concentrated positions in a few stocks, held through total return swaps at several prime brokers. When the stocks fell, margin calls went unmet and the banks raced each other to sell. Bank losses were over $10B (Credit Suisse about $5.5B). | Concentration, positions too big to sell quickly, leverage nobody saw in full, first-mover close-out | E1, E2, E3 |
| **UK LDI pension crisis (September 2022)** | A gilt yield spike caused huge collateral calls on liability-hedging funds that couldn't raise cash fast enough. The Bank of England intervened. | Solvent but illiquid: can the client actually pay today? | E2, E4 |
| **March 2020 "dash for cash"** | Margin requirements jumped across the market on the same days. | Procyclical margin; correlated breaches | E2, E6 |
| **LME nickel squeeze / EU energy hedgers (2022)** | Extreme price moves caused multi-billion daily variation margin calls on firms that were hedging, not speculating. | Extreme moves; liquidity buffer vs next-day call | E2, E4 |
| **LTCM (1998), Amaranth (2006)** | Leveraged, concentrated bets that unwound faster than they could be exited. | Concentration and liquidity, again | E1, E2 |

> To check: a case mentioned in discussion ("lost ~$35B in one week, about to get married") couldn't be identified with confidence. Confirm the name before citing it in any demo material.

---

## 2. Proposed enhancements

### E1 — Concentration and liquidity add-on *(Archegos)* — **recommended**
- **What:**
  - Per counterparty and ticker, calculate **days to liquidate** = position size ÷ 20-day average daily volume (ADV).
  - Calculate **single-name concentration** = one ticker's share of the counterparty's gross exposure.
- **Action:**
  - Add a deterministic **add-on to the margin requirement** when either crosses a CSA/policy threshold. Examples: > 3 days of ADV, or > 25% in one name.
  - Raise a flag on the exposure board, e.g. "CP-3 holds 9 days of ADV in ticker X".
- **Where:** new `src/calc/concentration.py`. ADV comes from yfinance volume, which the market-data path already uses. Thresholds live in counterparty/CSA config. The LLM drafts only the plain-English explanation.
- **Effort:** small–medium. **Tests:** exhaustive unit tests on the add-on maths and threshold edges.

### E2 — Named-crisis stress replay — **recommended**
- **What:** replay real historical windows on today's book:
  - the Archegos week (late March 2021)
  - March 2020
  - September 2022 (the gilt/LDI window, used as a rates/vol proxy)
  - a synthetic "worst single-name −50%" shock
- **Output:**
  - Day by day, which counterparties breach, call amounts, and the **peak total collateral demand**.
  - The firm-level 99th-percentile daily margin-call amount (a **liquidity forecast** for treasury).
- **Where:** extends `make simulate` / `src/streaming/simulator.py` with scenario files and real prices. Results land in BigQuery (G7) for analysis and a dashboard.
- **Effort:** medium. Reuses the existing calc engine unchanged.

### E3 — Early-warning signals and default / close-out path — **recommended**
- **Early warning:** escalate *before* a missed call when deterministic signals combine:
  - fast drawdown in the counterparty's book
  - margin utilisation rising toward the threshold
  - repeated late payments or disputes
  - concentration flags from E1
  - The LLM writes the escalation summary only.
- **Default branch:** if a call is unpaid past the CSA/ISDA grace period, the orchestrator branches to an **Event of Default → close-out** workflow instead of raising another call:
  - freeze new calls
  - compute a close-out netting amount (deterministic)
  - human approval
  - ServiceNow incident
- **Links:** this is the "make ISDA necessary" open item in `docs/gcp/GCP_ROADMAP.md`, because the ISDA terms decide the grace period and the netting set.
- **Effort:** medium–large (a new LangGraph branch + ISDA RAG).

### E4 — "Can they actually pay?" liquidity check *(LDI, energy hedgers)*
- **What:**
  - Compare the **stressed next-day call** (from E2's worst scenario) with the client's **liquidity buffer** (unencumbered eligible collateral + a cash line, synthetic).
  - Alert when the projected call exceeds the buffer.
- **Effort:** small, once E2 exists.

### E5 — Wrong-way collateral haircut
- **What:** if a client posts collateral that's correlated with its own exposure (e.g. the same stock it is long), apply an extra haircut on top of the CSA haircut. Haircuts already exist in the collateral path.
- **Effort:** small.

### E6 — Correlated-breach monitor
- **What:** flag when several counterparties breach on the same day or the same ticker move, which signals systemic or clustered risk (March 2020 pattern). Simple and deterministic; a good dashboard tile.
- **Effort:** small.

**Suggested demo bundle:** E1 + E2 + E3 → *concentration flag → stress replay shows the breach → early warning → close-out path.*

---

## 3. BigQuery (G7) — data volume and reporting requirement

Context: live data is small, and daily prices alone are about 75k rows (≈30 tickers × 252 days × 10 years). BigQuery's value here is history scans kept away from the live approval DB, an append-only audit record and governance features, **not data size**. Don't pitch it as "big data".

- **Primary reporting requirement (proposed):** **stress replay → liquidity forecast** (E2 output). This closes the roadmap open item "BigQuery needs a firm reporting requirement".
- **MM-G76 (proposed) — synthetic history generator:**
  - Scale to ~500 synthetic counterparties.
  - Replay several years of real prices through the real calc engine plus a simulated lifecycle (calls, approvals, disputes, SLA outcomes).
  - This produces millions of realistic rows for query load-testing, KPIs and the BigQuery ML model.
  - Deterministic (seeded) and free.
- **Analyses enabled:**
  - threshold calibration ("raise CP-5's threshold 20% → calls/year drop from 14 to 4")
  - stress replay and the 99th-percentile liquidity need
  - concentration drivers
  - intraday vs end-of-day detection lead time (justifies the real-time pipeline)
  - ops KPIs
  - audit queries

---

## 4. Other follow-ups noted (not features)

- **Audio summaries of agent answers:** discussed, not set up. Easiest is a local Claude Code `Stop` hook using Windows' built-in text-to-speech. Cloud sessions would need `espeak-ng` in the environment's setup script.
