# MarginMaestro — Dispute Exception Rules

This document governs how MarginMaestro's Reconciliation Agent handles
disagreements between our computed margin call and a counterparty's own
view of that call. It applies uniformly across all counterparty
relationships. It does not itself define the margin math (see the
Calculation Agent) or the escalation path for non-response (see the
separate escalation-procedures document) — this covers disputes only,
where the counterparty *has* responded, but with a different number.

## Materiality Tolerance

A discrepancy between our computed call and the counterparty's stated call
is treated as immaterial, and not escalated to a dispute, when it falls
within the agreed tolerance band for that relationship. Below tolerance,
the call proceeds as originally computed. Above tolerance, the trade
population is isolated for review before any resolution is proposed.

## Stale Price Exception

If a break is traced to one side using a stale price (a quote older than
the current valuation date), the more recent, verifiable price is treated
as authoritative, provided it comes from the same pricing source
convention already used for that security. A stale-price break does not
require escalation once the correct price is confirmed — it is resolved by
recomputation, not negotiation.

## Missing or Extra Trade Exception

If a break is traced to a trade present in our book but absent from the
counterparty's view (or vice versa), the trade's confirmation record is
the deciding evidence. A confirmed trade missing from a counterparty's
view is treated as their omission, to be corrected on their side, not
grounds to reduce our computed call. An unconfirmed trade present in only
one side's view is excluded from both sides' totals until confirmation
resolves it.

## Quantity Mismatch Exception

A quantity mismatch on an otherwise-confirmed trade is not resolved by
splitting the difference. The trade's original confirmation record
governs; if no confirmation record can settle it, the position is flagged
for manual operations review rather than resolved automatically.

## When to Escalate a Dispute

A dispute is escalated to manual operations review — rather than resolved
automatically by these rules — when: the break exceeds a material
threshold, more than one exception type applies to the same trade, or no
past precedent closely matches the current break pattern. Disputes that
match established precedent (see the historical dispute notes) may be
proposed automatically, but always require human confirmation before the
call amount is adjusted.
