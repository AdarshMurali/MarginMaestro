# ADR-0005: LLM for reasoning, code for math

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

The system mixes numeric work (MTM, VM, IM/SIMM, threshold/MTA checks, collateral optimization) with language work (interpreting CSAs, explaining disputes, drafting notices, mapping news to entities). LLMs are unreliable at arithmetic and expensive per call; the paid OpenAI budget is limited.

## Decision

**Never use the LLM for numeric or financial computation.** All math is deterministic Python with exhaustive unit tests. The LLM is used **only** for reasoning tasks: RAG over documents, dispute rationale, entity/impact judgment (within the curated universe), and drafting notification text.

## Rationale

- **Correctness:** deterministic code with hand-verified expected values is testable and trustworthy; LLM arithmetic is not.
- **Cost:** keeps LLM calls minimal, protecting the OpenAI budget; local models handle the reasoning that remains.
- **Auditability:** a regulated margin workflow must have reproducible numbers.
- **Interview narrative:** "LLM for reasoning, code for math" is a clear, senior design principle to articulate.

## Consequences

- Calculation and optimization agents are pure code (possibly wrapping a solver), fully unit-tested.
- Reasoning agents are grounded by RAG and their outputs (numbers parsed from documents) are validated before the math consumes them.
- Tests mock the LLM and assert on orchestration decisions, not model prose.

## Amendment (2026-10-01, MM-116): the model never sees the figures

Client notices used to pass the calculated figures to the model and instruct it to copy them exactly. Now the model drafts with placeholders only (`{COUNTERPARTY}`, `{CALL_AMOUNT}`, `{THRESHOLD}`, `{MTA}`); code rejects any draft with unknown or missing placeholders or **any digit at all** (one retry naming the problem, then a hard stop), and only then fills the values in from the calculation. A wrong amount can't be sent because the model can't write one. Live with Gemini: 8/8 notices passed first try.
