# Dispute Note DN-003 — Quantity Mismatch, Escalated (CP-8, 2026-05-20)

## Summary

CP-8 disputed the quantity booked on a Treasury ETF position, resulting in
a call disagreement beyond the materiality tolerance. Unlike most quantity
disputes, this one could not be resolved from the trade confirmation alone
and required manual operations review.

## Break Details

Our book showed a larger quantity than the counterparty's view for one
Treasury ETF position. The original trade confirmation record was
ambiguous — it referenced a since-superseded allocation instruction,
and did not cleanly settle which quantity was correct.

## Resolution

Per the Quantity Mismatch Exception, the ambiguous confirmation record was
insufficient to resolve automatically, so the position was flagged for
manual operations review rather than split or assumed. Operations traced
the allocation history directly with the counterparty's back office and
confirmed the smaller (counterparty) quantity was correct — the original
booking had double-counted a partial fill. The call was recomputed and
reduced accordingly, with the correction documented before any further
calls were issued against that position.
