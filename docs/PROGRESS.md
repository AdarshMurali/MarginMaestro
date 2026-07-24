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

- **Phase:** 0 — Foundations. Jira epic MM-1 + stories MM-2..MM-9 created. MM-2 through MM-6 all merged to `main` (MM-4/MM-5 execution order was swapped — see MM-5's log entry). CI is fully green including the live Docker Hub push. MM-7 (SonarCloud) done on branch `feature/MM-7-sonarcloud`, not yet pushed/merged; quality gate verified passing on PR #6. SonarCloud project: org `adarshmurali`, project key `AdarshMurali_MarginMaestro` (auto-assigned by SonarCloud, not the literal repo name — see MM-7's log entry), Automatic Analysis turned off in favor of CI-based, `SONAR_TOKEN` set as a GitHub Actions repo secret.
- **Docs:** complete — README, CLAUDE.md, ARCHITECTURE, AGENTS, DATA_SOURCES, ROADMAP, ADRs, CONTRIBUTING, TESTING.
- **Next up:** **MM-8** — Terraform skeleton for AWS (Parameter Store, IAM least-privilege, compute placeholders).
- **Blockers:** none. Note: `ROADMAP.md` MM-# numbering for Phase 0 was corrected to match real Jira keys (epic took MM-1, not a story); later phases still show the original placeholder scheme pending ticket creation.

---

## Log

### 2026-07-24 — MM-7: SonarCloud integration (coverage upload, quality gate, README badge)
- **Done:** `sonar-project.properties` (org `adarshmurali`, project key `AdarshMurali_MarginMaestro`, `sonar.sources=src`, `sonar.tests=tests`, `sonar.python.coverage.reportPaths=coverage.xml`). New `sonarcloud` job in `ci.yml` (needs `lint-test`): downloads the `coverage-xml` artifact, runs `SonarSource/sonarqube-scan-action@v8.2.1` (current unified SonarQube/SonarCloud action per SonarSource's own repo — the older `sonarcloud-github-action` is its predecessor), then `SonarSource/sonarqube-quality-gate-action@v1.2.0` to actually fail the build on a gate failure, not just report one. Added Quality Gate + Coverage badges to `README.md` (with the project's badge token — safe to embed publicly, scoped to read-only badge display).
- **Decisions:** Relying on SonarCloud's default "Sonar way" quality gate (≥80% coverage-on-new-code, blocks new critical/blocker issues) rather than authoring a custom gate. When the user connected the repo to SonarCloud, it defaulted to **Automatic Analysis** and auto-provisioned the project under key `AdarshMurali_MarginMaestro` (`<github-org>_<repo>` convention) — our first attempt used the wrong key (`MarginMaestro`), which both missed the real project's data and caused CI to auto-create a second, orphan, unbound project under the literal key. Used Chrome DevTools MCP (with the user logged into their own SonarCloud session in an automated browser window) to find the real project key, turn off Automatic Analysis (required — it conflicts with CI-based analysis and doesn't pick up `coverage.xml`), get the project's badge token, and delete the stray orphan project. Fixed the key in `sonar-project.properties`/`README.md`, re-ran CI — PR #6's SonarCloud analysis now shows **Quality gate: Passed** with real coverage data. Badges themselves will render correctly once merged to `main` (SonarCloud badges reflect the default branch; PR analysis is scoped separately) — same pattern as MM-6's Docker Hub push.
- **Changed:** new file `sonar-project.properties`; modified `.github/workflows/ci.yml`, `README.md`. SonarCloud project settings: Automatic Analysis turned off; stray `MarginMaestro` project deleted.
- **Known issues / tech debt:** none — root cause (wrong project key) fully resolved and verified against a real, passing quality gate.
- **Next step:** **MM-8** — Terraform skeleton for AWS.

### 2026-07-24 — MM-6: GitHub Actions CI (lint, type-check, test+coverage, build, push to Docker Hub)
- **Done:** `.github/workflows/ci.yml` with two jobs. `lint-test` (runs on every push and PR): checkout, Python 3.11 with pip caching, `pip install -e ".[dev]"`, `ruff check .` / `black --check .` / `mypy src`, `pytest --cov=src --cov-report=xml --cov-report=term`, uploads `coverage.xml` as a build artifact. `build-and-push` (needs `lint-test`): builds the Docker image via `docker/build-push-action`; on a PR it's build-only (`push: false`, just proves the Dockerfile still builds); on a push to `main` it logs into Docker Hub and pushes `adarshmurali/marginmaestro` tagged `latest` and the commit SHA.
- **Decisions:** Action versions pinned to current releases (checked via `gh api`, not guessed): `actions/checkout@v7.0.1`, `actions/setup-python@v7.0.0`, `docker/setup-buildx-action@v4.2.0`, `docker/login-action@v4.5.1`, `docker/build-push-action@v7.3.0`, `actions/upload-artifact@v7.0.1`. Docker Hub push is gated to `main`-branch pushes only, not PRs, to avoid pushing preview images for every PR. Coverage upload to SonarCloud itself is MM-7's job — this story only makes sure `coverage.xml` exists and is captured as an artifact.
- **Changed:** new file `.github/workflows/ci.yml`.
- **Known issues / tech debt:** none.
- **Next step:** see the follow-up entry below (Docker Hub login had to be debugged post-merge) before MM-7.

### 2026-07-24 — MM-6 follow-up: fixed Docker Hub login failure after merge
- **Done:** The first real push-to-`main` run failed at `docker/login-action` with `Error response from daemon: ... malformed HTTP Authorization header`. Added a temporary diagnostic step (prints only secret *lengths* and boolean flags for embedded newline/CR/quote/space — never actual content, to avoid any risk of leaking a secret past GitHub's log masking) to narrow it down. First round ruled out whitespace/newline corruption. Lengths looked suspicious (username 26 chars vs. the expected 12-char `adarshmurali`; token 36 chars vs. the ~40+ expected for a `dckr_pat_...` token), pointing at wrong *values* rather than formatting — user regenerated/re-pasted both `DOCKER_USERNAME` and `DOCKERHUB_TOKEN`, and the next run succeeded. Confirmed live: `adarshmurali/marginmaestro` now has both `latest` and a commit-SHA tag on Docker Hub, `last_pushed` matching the successful run. Removed the diagnostic step afterward — it was explicitly temporary.
- **Decisions:** Iterated by pushing directly to `main` rather than through a feature-branch PR for this diagnostic — user-approved, justified because the failure only reproduces on an actual push-to-`main` event (PRs skip the login/push steps by design) and the diagnostic itself was non-destructive/read-only in effect.
- **Changed:** `.github/workflows/ci.yml` (diagnostic step added then removed; net diff from the MM-6 PR is zero).
- **Known issues / tech debt:** none — root cause was bad secret values, not a workflow bug. Worth remembering for future secret setup: Docker Hub PATs should be copied in full including the `dckr_pat_` prefix from Account Settings → Security → New Access Token, not the account password.
- **Next step:** **MM-7** — SonarCloud integration (upload coverage, quality gate, README badge).

### 2026-07-24 — MM-4: Dockerize the API service; docker-compose for local stack
- **Done:** Multi-stage `Dockerfile` (`python:3.11-slim` builder stage → slim runtime stage, non-root `appuser`, venv copied over rather than rebuilt). `.dockerignore` excludes dev/CI cruft from the build context. `docker-compose.yml` (Compose v2, no `version:` key) with three services: `app` (builds from the Dockerfile, `8000:8000`), `redpanda` (`docker.redpanda.com/redpandadata/redpanda:v26.1.14`, single-node `--mode dev-container` with dual internal/external listeners per Redpanda's own quickstart — internal `redpanda:9092` for containers, external `localhost:19092` for host tools; also exposes pandaproxy/schema-registry/admin ports), `chroma` (`chromadb/chroma:1.5.3` pinned, container port 8000 → host 8100 to avoid clashing with `app`, volume at `/data` — the documented default persistence path for this image). Fixed `.env.example`'s `KAFKA_BOOTSTRAP_SERVERS` (was `localhost:9092`, matched neither the new internal nor external listener — now `localhost:19092` with a comment on the in-container override).
- **Decisions:** Pulled exact Redpanda command flags and the Chroma image/volume path from their official docs rather than guessing, since a wrong broker flag or persistence path would fail silently. Verified the whole stack for real: `docker compose build && up -d`, confirmed all three containers running, curled `/health` and `/ready` through the containerized app (both 200, correlation IDs present), hit Redpanda's admin API (`/v1/status/ready` → ready) and Chroma's heartbeat endpoint (200) directly, then `docker compose down -v`. Docker Desktop wasn't running at the start of this story — started it and waited for the daemon before building.
- **Changed:** new files `Dockerfile`, `.dockerignore`, `docker-compose.yml`; modified `.env.example`.
- **Known issues / tech debt:** Nothing in the app actually talks to Redpanda or Chroma yet (that's Phase 1/3/4 work) — this story only proves the containers exist, build, and are reachable. `app`'s `depends_on` on `redpanda`/`chroma` is startup-order only (no healthcheck condition), fine for now since nothing depends on them being ready yet.
- **Next step:** **MM-6** — GitHub Actions CI (install, lint, type-check, `pytest --cov`, build image, push to Docker Hub).

### 2026-07-24 — MM-5: Minimal FastAPI app with /health, /ready, structured logging, correlation-id middleware
- **Done:** `src/api/main.py` (FastAPI app), `src/api/schemas.py` (`HealthResponse` Pydantic model), `src/api/logging_config.py` (structlog configured in pure mode — JSON renderer, ISO timestamps, `merge_contextvars` processor — no stdlib `logging` interop yet), `src/api/middleware.py` (`CorrelationIdMiddleware`: reads/generates `X-Request-ID`, binds it into structlog context for the request, echoes it in the response header, logs one `request_handled` event per request). `/health` and `/ready` both return `200 {"status": ...}` — `/ready` has no real dependency checks yet since there's nothing to check against (DB/Kafka land in later phases). 12 tests added across `tests/unit/test_health.py` and `tests/unit/test_correlation_id.py` (correlation-id generation, echo-back, and structlog context binding via `structlog.testing.capture_logs`). Manually verified with a live `uvicorn` run — curled both endpoints, confirmed JSON log lines with correct correlation IDs in the output.
- **Decisions:** Swapped MM-4/MM-5 execution order (see snapshot above) — user-approved. Did not build the MM-9 config loader early; host/port stay hardcoded to `0.0.0.0:8000` defaults for now. Kept structlog un-integrated with stdlib logging (uvicorn's own access logs stay separate) to keep this story's scope minimal.
- **Changed:** new files `src/api/main.py`, `schemas.py`, `logging_config.py`, `middleware.py`; new tests `tests/unit/test_health.py`, `tests/unit/test_correlation_id.py`.
- **Known issues / tech debt:** `structlog.testing.capture_logs()` disables all configured processors by default unless passed explicitly (structlog 25.5.0+ behavior) — tests pass `processors=[structlog.contextvars.merge_contextvars]` explicitly; worth remembering for future structlog-based tests. A `StarletteDeprecationWarning` about `httpx`/`starlette.testclient` appears in test output (points at an `httpx2` package) — not addressed now, harmless, revisit if it becomes a hard error on a future Starlette upgrade.
- **Next step:** **MM-4** — Dockerize the now-real API service; docker-compose for local stack (Redpanda, ChromaDB, app).

### 2026-07-24 — MM-3: Pre-commit hooks (ruff, black, mypy)
- **Done:** Added `.pre-commit-config.yaml` with three hooks — `ruff` (astral-sh/ruff-pre-commit v0.16.0), `black` (psf/black 26.5.1), `mypy` (pre-commit/mirrors-mypy v2.3.0, scoped to `files: ^src/`, using the project's `pyproject.toml` config). Hook revs pinned to match the versions already installed in `.venv` (confirmed via `pip show` + `gh api repos/.../tags`). Ran `pre-commit install` (wired into `.git/hooks/pre-commit`) and `pre-commit run --all-files` — all three hooks pass on the current scaffold.
- **Decisions:** Kept the hook set to exactly ruff/black/mypy per the story's literal scope — did not add generic hygiene hooks (trailing-whitespace, end-of-file-fixer, etc.) from `pre-commit/pre-commit-hooks` to avoid scope creep beyond what MM-3 asked for.
- **Changed:** new file `.pre-commit-config.yaml`.
- **Known issues / tech debt:** none.
- **Next step:** **MM-4** — Dockerize the API service (multi-stage build); `docker-compose` for local stack (Redpanda, ChromaDB, app).

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
