# ADR-0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

MarginMaestro is built story by story, often across separate sessions (including by Claude agents). Decisions and their *reasoning* must survive across sessions, or they get silently reversed and re-litigated.

## Decision

We keep lightweight **Architecture Decision Records** (ADRs) in `docs/adr/`, one file per significant decision. Format: Context → Decision → Consequences. Numbered sequentially. When a decision changes a project convention, we also update `CLAUDE.md`.

A decision warrants an ADR if it: picks between competing technologies, sets a cross-cutting rule, or has consequences that a future contributor would otherwise question.

## Consequences

- The *why* behind each choice is durable and discoverable.
- New contributors (human or agent) can get up to speed from `docs/adr/` + `CLAUDE.md`.
- Small overhead per decision — accepted as worthwhile for a project meant to read as production-grade.
