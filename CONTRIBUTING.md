# Contributing to MarginMaestro

This project is built **story by story**, with a clean handoff between each. Whether the author is a human or a Claude agent, the same discipline applies. The goal is a codebase that reads like a top-grade production application.

## The development loop (per story)

Every unit of work follows this cycle. Do not start the next story until the current one is fully finished and handed off.

1. **Pick the next story** from [`docs/ROADMAP.md`](docs/ROADMAP.md) / the Jira board. Work one story at a time.
2. **Read the Definition of Done (DoD)** and acceptance criteria *before* writing code.
3. **Plan** the change (in Claude Code, use plan mode / produce a plan and review it before implementing).
4. **Write the test first** where practical (TDD), then the implementation.
5. **Run tests + lint locally** until green: `make test && make lint` (see [`TESTING.md`](TESTING.md)).
6. **Update docs** — if a decision was made, add an ADR under `docs/adr/`; if a convention changed, update [`CLAUDE.md`](CLAUDE.md).
7. **Update [`docs/PROGRESS.md`](docs/PROGRESS.md)** — the handoff log (see format below).
8. **Commit** with the Jira key in the message (smart commit), one story per PR.
9. **Attach evidence** to the Jira story (test output, coverage delta, screenshots).
10. **Open a PR** — CI must pass (tests, coverage gate, Sonar quality gate) before merge.

## Definition of Done (applies to every story)

A story is **done** only when *all* of the following are true:

- Acceptance criteria met.
- Unit tests written and passing; coverage does not drop below the project threshold.
- Lint, format, and type checks pass (`ruff`, `black`, `mypy`).
- No secrets in code — config via env / Parameter Store.
- Relevant docs updated (ARCHITECTURE / AGENTS / DATA_SOURCES as needed).
- `docs/PROGRESS.md` updated with the handoff entry.
- ADR added if a non-trivial decision was made.
- CI green (including SonarCloud quality gate).
- Evidence attached to the Jira story.

## The handoff entry (PROGRESS.md)

At the end of each story, append an entry with this exact shape so any fresh session can resume with zero context loss:

```markdown
### <DATE> — <STORY KEY>: <title>
- **Done:** what was completed
- **Decisions:** key decisions (link ADR if any)
- **Changed:** files/modules/architecture touched
- **Known issues / tech debt:** anything deferred
- **Next step:** the exact next action
```

## Branching & commits

- Branch per story: `feature/MM-123-short-description`.
- Conventional commits: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`.
- Include the Jira key so commits auto-link: `feat(events): add tick consumer [MM-123]`.
- Small, focused PRs — one story each.

## Code standards

- **Python:** `ruff` (lint) + `black` (format) + `mypy` (types). Enforced via pre-commit and CI.
- **Never use the LLM for numeric/financial computation** — see [ADR-0005](docs/adr/0005-llm-for-reasoning-code-for-math.md). Math is deterministic code with tests.
- **Type everything** at module boundaries; validate external data with Pydantic.
- **No business logic in the frontend** — it visualizes; the backend decides.
- Keep functions small and testable; prefer pure functions for calculations.

## Pre-commit

```bash
pip install pre-commit
pre-commit install
# runs ruff, black, mypy on staged files before each commit
```
