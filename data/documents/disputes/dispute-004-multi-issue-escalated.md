# Dispute Note DN-004 — Multi-Issue Break, Escalated (CP-2, 2026-06-11)

## Summary

CP-2's stated call diverged from our computed call by a wide margin,
driven by more than one break type on the same trade population — a
combination the standard exceptions don't cleanly resolve on their own.

## Break Details

Two issues were found on inspection: one position had a stale price on the
counterparty's side (similar to DN-001), and a second, unrelated position
was missing from our own book — the reverse of the usual missing-trade
pattern, where the gap was on our side rather than the counterparty's.

## Resolution

Because more than one exception type applied to the same overall dispute,
it was escalated to manual operations review per the "when to escalate"
rule, rather than resolved automatically. Each break was worked
independently: the stale price was corrected the same way as DN-001, and
the position missing from our book was confirmed against the
counterparty's trade confirmation and added. The net effect on the call
amount was smaller than either individual break suggested, since the two
corrections moved in opposite directions. This case is the reference
precedent for combined/multi-issue breaks going forward.
