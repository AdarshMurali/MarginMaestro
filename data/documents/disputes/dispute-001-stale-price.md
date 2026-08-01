# Dispute Note DN-001 — Stale Price Break (CP-3, 2026-03-14)

## Summary

CP-3 disputed a margin call, citing a lower exposure figure than our
computed call. The discrepancy traced to a single equity position where
the counterparty's valuation used a closing price from two trading days
prior, rather than the current valuation date's close.

## Break Details

One position (a mega-cap equity holding) accounted for the entire
discrepancy. Our valuation used the current-day close; the counterparty's
figure matched a stale close from 2026-03-12, not 2026-03-14. No trade
population mismatch — both sides agreed on quantity and trade identity.

## Resolution

Applied the Stale Price Exception: the current-day close was confirmed
against the same pricing source both sides normally use, and treated as
authoritative. The counterparty accepted the corrected figure once shown
the verifiable current-date quote. No escalation was required — resolved
same-day by recomputation, not negotiation.
