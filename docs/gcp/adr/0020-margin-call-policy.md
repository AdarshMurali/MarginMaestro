# ADR-0020: Margin-call policy — daily run, intraday materiality gate, one open call per counterparty

- **Status:** Accepted
- **Date:** 2026-10-05 (story MM-125, Phase G5b)

## Context

The first live run on GCP (2026-10-02) raised calls for CP-1, CP-3 and CP-7 when HPE moved +7.4%. HPE is a small part of those books: the move changed their exposure by about $1.8k, $1.4k and $4.1k, against MTAs of $11k, $19k and $47k. The calls ($250k, $162k and $3.75M) came from breaches that already existed. The HPE event only made the orchestrator re-check each whole book. Nothing stopped a second event from raising a second call on a counterparty that already had one open. The notice also said "next business day" while the SLA timer gave the client 60 minutes.

Real desks keep two things apart. A daily margin run calls standing exposure. Intraday calls are raised only when the event itself moves exposure materially.

## Decision

1. **Daily margin run.** `POST /internal/margin/daily-run` (OIDC, internal caller only). Cloud Scheduler calls it at **16:45 New York, Mon–Fri**, after `eod-prices` (16:30) has loaded the official closes. It is paused with the other jobs by `demo_online`. Every counterparty with a book is evaluated, and a standing breach raises a call that waits at the approval gate. The run is an impact set with the id `daily-margin-run:<date>`, so a retry or a second call on the same day skips counterparties already done.
2. **Intraday materiality gate.** An intraday price event raises a call only if **its own impact on the counterparty's exposure is greater than the CSA MTA**.
   - The impact is deterministic (`calc/materiality.py`, ADR-0005). It uses the same exposure math as the breach check (exposure = VM + IM), over the positions in the moved tickers, priced before and after the move: quantity × price change, plus the IM change.
   - The move (`price_moves`: prior close → shocked price) travels on the event, so a replay measures the same move.
   - A move that reduces exposure never passes.
   - Below the gate the run ends without a call. Its status is `below_materiality`, and the computed impact is logged and audited.
   - The gate applies to live shocks and to `/simulate`. It does not apply to downgrades or to the daily run.
3. **The rationale comes from code.** Every evaluation stores a `call_rationale` built from the calculated figures, for example "The NVDA move (USD 180.00 to USD 198.00) increased your exposure by USD 207,000.00, more than the minimum transfer amount of USD 19,000.00. Your exposure of … exceeds the threshold of …; after collateral held of …, USD … is due."
   - The client notice includes the rationale as a `{RATIONALE}` placeholder, filled in after validation. The model never sees or writes a figure (ADR-0005 amendment, MM-116).
4. **One open call per counterparty.** A call is open while it is awaiting approval, awaiting the manager's second signature, or awaiting the client's response under the SLA. All triggers go through `agents/margin_policy.dispatch_trigger`. When a counterparty has an open call:
   - **Awaiting its first approval (no signature yet):** the trigger re-evaluates that call in place. The call's graph restarts from START with the new trigger (exposure, CSA terms, breach), and the run pauses again at the approval gate with the new amount. The pending approval request is replaced, never answered. If the shortfall is gone (only the daily run can find this, because an intraday trigger must increase exposure past the MTA), the call ends as no-breach before anyone approves it.
   - **Already signed or sent** (awaiting the second signature, or notified and on the SLA clock): **nothing changes.** The trigger is recorded on that call's audit trail. Once the call resolves, the next daily run evaluates the counterparty again and raises a call for any remaining shortfall.
   - An intraday trigger must clear the gate first. The MTA comes from the open call's own CSA terms, so this check needs no LLM call.
   - A trigger already applied to the open call is a no-op. The per-(event, counterparty) claim also prevents replays.
5. **Concurrency.** A per-counterparty lease (a `processed_events` row; it expires after 15 minutes, longer than the 600 s request timeout) serialises triggers for one counterparty across Cloud Run instances. A trigger that finds the lease held is retried: Pub/Sub redelivers, and the daily run returns 503 so Cloud Scheduler retries. It never raises a parallel call.
6. **The notice quotes the enforced deadline.** `send_notification` fixes the send time first and passes `deadline = notification_sent_at + MARGIN_CALL_SLA_MINUTES` as the `{DEADLINE}` placeholder (for example "18:35 UTC on 5 October 2026"). This is the same instant the SLA timer enforces. A draft without the placeholder is rejected, and the model is told to state no other timeframe.

## Why not change a signed or sent call

The human approval gate (golden rule 5) approves a specific amount. Changing the amount after the first signature would make the second signature ratify a figure the first approver never saw. Changing it after the notice would make the client's obligation differ from what the client was told, and would move the SLA deadline under the client. Re-arming the approval (sending the call back to the first approver) was considered. It is safe, but it would cancel a decision a human already made because of an automated trigger, so it was rejected. The call that is out stays exactly as signed. A growing shortfall is visible in the audit trail and is called at the next daily run after the current call resolves.

## Consequences

- The 2026-10-02 replay raises no intraday HPE calls. The daily run raises the standing calls once each, with an exposure rationale. A second material shock updates the open call instead of raising another (tests in `tests/unit/test_margin_policy.py`).
- `/simulate` behaves like a live event. A move too small to matter, or one that lowers exposure, shows the reason instead of a call.
- A new lifecycle status, `below_materiality`, appears in the feed, the MCP status tool and the UI. It counts as neither a call nor a breach in the history roll-up.
- Cost: one more Cloud Scheduler job (the third; the free tier covers three per billing account), plus one CSA extraction per counterparty per day.
- Known limits: an SLA marked "met" doesn't book the collateral, so the next daily run can call the same standing shortfall again. Fixing this needs collateral booking, which is a separate story. The daily run's date is the UTC date, which is the same calendar day as 16:45 New York.
