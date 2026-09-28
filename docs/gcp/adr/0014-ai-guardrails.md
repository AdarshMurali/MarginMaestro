# ADR-0014: Mandatory guardrails for every LLM interaction

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

Guardrails are now mandatory. The system sends client-facing text, reads external documents, and handles confidential counterparty data. Risks: prompt injection (directly, or via retrieved documents and client replies), PII/confidential-data leakage to the model or in outputs, hallucinated amounts, off-topic or unsafe output, and runaway cost.

## Decision

Defense in layers, all wrapped behind one `Guardrail` interface called before and after every LLM call:

| Layer | Control | Service |
|---|---|---|
| Input screening | Prompt-injection / jailbreak detection, malicious URL checks on client replies and retrieved chunks | **Model Armor** |
| Data minimization | Detect and mask PII / account numbers before text reaches the model or the RAG index | **Sensitive Data Protection** (de-identification) |
| Model-level | Gemini safety settings at block-medium-and-above | Vertex AI |
| Output validation | Structured output + Pydantic schema; any amount, date or counterparty in drafted text must exactly match calc output, otherwise the draft is rejected | In-code |
| Output screening | Model Armor response screening + SDP scan before anything is sent to Slack/WhatsApp | Model Armor, SDP |
| Grounding | Retrieved text is treated as data, never instructions; every RAG-backed claim carries a citation, and uncited claims are rejected | In-code |
| Human gate | No client-facing message without human approval (golden rule) | Existing |
| Cost / loop limits | Per-run token cap, max agent steps, per-user rate limit | In-code |

Every guardrail verdict is written to the audit trail and to BigQuery telemetry (ADR-0013). Guardrails **fail closed**: if Model Armor is unreachable, the call is held for human review rather than sent unscreened.

## Consequences

- Tests: mocked Model Armor/SDP verdicts; assert that blocked input stops the run, mismatched amounts are rejected, and a guardrail outage fails closed.
- Model Armor and SDP have limited free quotas — post-trial fallback is the in-code layer plus Presidio for PII (ADR-0017).
