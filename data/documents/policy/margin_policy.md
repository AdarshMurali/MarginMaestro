# MarginMaestro — Internal Margin Call Policy

This policy governs how MarginMaestro handles margin call valuation, timing,
and notification across all counterparty relationships. It applies uniformly
regardless of counterparty — bilateral terms (threshold, MTA, eligible
collateral) are set per counterparty in that counterparty's Credit Support
Annex, not here.

## Valuation Timing

Portfolios are revalued whenever a qualifying market event occurs: a price
move on a held security, a volatility spike, a counterparty rating downgrade,
a change in the value of posted collateral, or a new trade booked into a
portfolio. Valuation uses the most recent available price for each position;
stale prices are never substituted silently.

## Call Notification Process

Once exposure is determined to exceed a counterparty's threshold by at least
their Minimum Transfer Amount, a margin call is drafted. Every call passes a
human approval gate before being sent — no call is issued to a counterparty
without an approving user reviewing the computed amount and underlying
exposure. Once approved, the counterparty is notified promptly through the
agreed communication channel.

## General Threshold Policy

Thresholds and MTAs are counterparty-specific and are always sourced from
that counterparty's CSA — this policy does not override or approximate them.
If a counterparty's CSA terms cannot be retrieved or are ambiguous, the call
is held for manual review rather than proceeding on an assumed value.

## Collateral Substitution

A counterparty may substitute posted collateral for another eligible
collateral type listed in their CSA, subject to that type's haircut. Requests
for collateral types not listed as eligible in the counterparty's CSA are
declined pending a documented exception.

## Escalation

If a counterparty does not respond to a margin call within the SLA window,
the matter is escalated per the separate escalation-procedures document —
this policy does not itself define escalation steps.
