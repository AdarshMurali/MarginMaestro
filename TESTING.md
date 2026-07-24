# Testing & Quality

Quality is enforced, not optional. CI fails if tests fail, coverage drops below threshold, or the SonarCloud quality gate is breached.

## Test layers

| Layer | Tool | What it covers |
|---|---|---|
| Unit | `pytest` | Pure logic — margin math (MTM/VM/IM), CSA rule evaluation, threshold/MTA checks, SLA timer. **Highest priority** — the financial math must be exhaustively tested. |
| Integration | `pytest` + `testcontainers` | Kafka produce/consume, DB reads/writes, RAG retrieval, MCP tool calls. |
| Agent / orchestration | `pytest` | LangGraph flows with mocked LLM + mocked tools — assert the graph takes the right branch (approve vs escalate) given an input event. |
| Contract | `schemathesis` (optional) | FastAPI endpoints against the OpenAPI schema. |
| End-to-end (scenario) | `pytest` | Inject a synthetic price shock → assert a call is raised → notified → escalated after SLA. Uses the simulator, fully deterministic. |

## Principles

- **Deterministic tests.** The market simulator publishes scripted scenarios so tests are repeatable. Never depend on a live feed in tests.
- **Mock the LLM in unit/agent tests.** LLM calls are stubbed; we assert on the *orchestration decisions and tool calls*, not on model prose.
- **The math is tested to the number.** VM/IM/threshold/MTA calculations have explicit, hand-computed expected values.
- **Test the branches that matter.** Especially: breach vs no-breach, dispute vs agree, met vs escalated, idempotent replay of the same event.

## Coverage

- Generate coverage: `pytest --cov=src --cov-report=xml --cov-report=term`.
- Threshold: **≥ 80%** overall (enforced in CI and the Sonar quality gate).
- `coverage.xml` is uploaded to SonarCloud in the CI pipeline.

## Common commands

```bash
make test          # run all tests
make test-unit     # unit tests only (fast)
make cov           # tests + coverage report
make lint          # ruff + black --check + mypy
make fmt           # auto-format
```

## CI quality gate (GitHub Actions → SonarCloud)

On every PR the pipeline:
1. Installs deps, runs `ruff`/`black`/`mypy`.
2. Runs `pytest` with coverage → `coverage.xml`.
3. Runs the SonarCloud scan (uploads coverage + static analysis).
4. **Fails the build** if: any test fails, coverage < 80%, or the Sonar quality gate reports new bugs/vulnerabilities/critical smells.

A green pipeline is a precondition for merge. See [`docs/ROADMAP.md`](docs/ROADMAP.md) Phase 0 for the CI setup story.
