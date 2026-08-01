# Dispute Note DN-002 — Missing Trade Break (CP-6, 2026-04-02)

## Summary

CP-6's stated call was materially lower than our computed call. The
counterparty's position view was missing one crypto holding entirely,
understating their exposure.

## Break Details

A single crypto position, confirmed on our side via a signed trade
confirmation from the original booking date, did not appear in the
counterparty's submitted position list. All other positions matched
exactly.

## Resolution

Applied the Missing or Extra Trade Exception: the confirmed trade
governed, and the omission was treated as an error on the counterparty's
side, not a reduction to our computed call. The counterparty located the
missing booking in their own systems within one business day and
corrected their view. The call amount was not adjusted.
