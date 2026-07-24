# MarginMaestro — Progress & Handoff Log

> **This is the living handoff log. Update it at the end of EVERY story** (part of the Definition of Done). A fresh session should be able to read the latest entry and resume with zero context loss. Newest entries at the top.

## How to use this file

At the end of each story, prepend an entry using this template:

```markdown
### <YYYY-MM-DD> — <STORY KEY>: <title>
- **Done:** what was completed
- **Decisions:** key decisions (link ADR if any)
- **Changed:** files / modules / architecture touched
- **Known issues / tech debt:** anything deferred
- **Next step:** the exact next action
```

## Current state (snapshot)

- **Phase:** 0 — Foundations. Jira epic MM-1 + stories MM-2..MM-9 created. MM-2 (scaffold) done on branch `feature/MM-2-scaffold-project-structure`, not yet pushed/merged.
- **Docs:** complete — README, CLAUDE.md, ARCHITECTURE, AGENTS, DATA_SOURCES, ROADMAP, ADRs, CONTRIBUTING, TESTING.
- **Next up:** **MM-3** — pre-commit hooks (ruff, black, mypy).
- **Blockers:** none. Note: `ROADMAP.md` MM-# numbering for Phase 0 was corrected to match real Jira keys (epic took MM-1, not a story); later phases still show the original placeholder scheme pending ticket creation.

---

## Log

### 2026-07-24 — MM-2: Scaffold project structure, pyproject.toml, Makefile
- **Done:** Created `src/` (agents, calc, streaming, rag, api, mcp, persistence — each a top-level package), `tests/` (unit, integration, agent, e2e, mirroring TESTING.md's layers) with a smoke test proving the pytest+coverage pipeline works, placeholder `infra/README.md` and `frontend/README.md`, `pyproject.toml` (Python 3.11+, core deps + optional groups per future phase, ruff/black/mypy/pytest/coverage config), and `Makefile` (install, install-dev, test, test-unit, cov, lint, fmt, clean). Also bootstrapped git: repo had zero commits before this story — created `main` with a baseline commit of the existing docs, then branched `feature/MM-2-scaffold-project-structure` off it.
- **Decisions:** `src/` uses one top-level package per area (no umbrella package name), per CLAUDE.md's target structure literally. `pyproject.toml` declares forward-looking optional-dependency groups (`rag`, `streaming`, `llm`, `data`, `db`) now so later phase stories only add package names, not restructure the file.
- **Changed:** new files — `Makefile`, `pyproject.toml`, `src/**/__init__.py`, `tests/**`, `infra/README.md`, `frontend/README.md`. Git: `main` branch created (root commit = docs baseline), `feature/MM-2-scaffold-project-structure` branch created off it.
- **Known issues / tech debt:** `make simulate` intentionally not added yet — depends on the Phase 4 simulator module (MM-41). This dev machine has no `make` binary on PATH (Git Bash / Windows); verified all Makefile targets by running the underlying commands directly (`pytest --cov=src`, `ruff check .`, `black --check .`, `mypy src` — all green) via a `py -3.11` venv, since the system default `python` resolves to 3.10.6. Branch not yet pushed to `origin`; PR not yet opened (pending user go-ahead).
- **Next step:** Push `feature/MM-2-scaffold-project-structure` and open a PR (needs explicit go-ahead), then start **MM-3** (pre-commit hooks: ruff, black, mypy).

### 2026-07-23 — MM-0: Project documentation & design baseline
- **Done:** Established the full design-doc set for MarginMaestro: README, CLAUDE.md (agent operating guide), ARCHITECTURE, AGENTS, DATA_SOURCES, ROADMAP (phased/Jira-ready), CONTRIBUTING, TESTING, and ADRs 0001–0005. Repo scaffolding decisions (structure, stack, conventions, guardrails) recorded.
- **Decisions:** Stack locked (LangGraph, local LLM/embeddings, ChromaDB, Kafka/Redpanda, FastAPI, Next.js, Terraform, SonarCloud). Flink deferred to optional Phase 11 (ADR-0003). LLM-for-reasoning-code-for-math rule (ADR-0005). Vector store = ChromaDB (ADR-0004). Orchestration = LangGraph (ADR-0002).
- **Changed:** `/` root docs + `docs/` + `docs/adr/`.
- **Known issues / tech debt:** none yet. Actual code (Phase 0) not started.
- **Next step:** Begin **MM-1** (scaffold structure) following the ROADMAP; keep coverage ≥ 80% from the first line of code.
