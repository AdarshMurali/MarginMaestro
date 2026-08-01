# MarginMaestro — Margin Call Escalation Procedures

This document governs what happens after a margin call has been approved and
sent, but the counterparty has not responded within the agreed SLA window
(`MARGIN_CALL_SLA_MINUTES`). It applies uniformly across all counterparty
relationships. Bilateral notice terms are set per counterparty in that
counterparty's Credit Support Annex; this document covers the internal
operational response to non-response, not contractual notice periods.

## Escalation Trigger

A margin call is escalated when the SLA timer elapses with no acknowledgement
from the counterparty — the counterparty has neither confirmed receipt nor
posted the required collateral. A call that is met within the SLA window,
even close to the deadline, is not escalated. Escalation is triggered
automatically once the deadline passes; it is not itself subject to a
separate human approval gate, since the underlying call was already approved
before being sent.

## Incident Priority

Escalations are logged with priority based on the call amount relative to
the counterparty's threshold: a call exceeding the threshold by more than
5x is High priority; otherwise it is Moderate priority. Priority reflects
urgency of internal follow-up, not a reflection on the counterparty's
creditworthiness.

## Incident Creation

An incident is opened in the ticketing system with the following context
included in full: the counterparty identifier, the approved call amount and
currency, the original notification timestamp, the SLA deadline that was
missed, and the correlation id of the originating margin call run — so any
operations team member can trace the full history of the run from the
incident alone, without needing separate access to the orchestration logs.

## Ownership and Next Steps

Once an incident is opened, it is owned by the operations team, not by
MarginMaestro itself — the system's responsibility ends at raising a
complete, well-contextualized incident. Follow-up contact with the
counterparty (phone, relationship manager escalation, or formal notice per
the CSA) happens outside this system.

## Resolution

An escalation is not automatically closed by a late response — closing the
incident is a manual operations step once the call is actually satisfied or
otherwise resolved, so that a delayed response doesn't silently erase the
record that an SLA was missed.
