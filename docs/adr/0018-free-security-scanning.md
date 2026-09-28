# ADR-0018: Free security scanning with GitHub Advanced Security instead of Black Duck / Checkmarx

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

A regulated-finance system is expected to show supply-chain and code security controls: dependency vulnerability scanning (typically Black Duck), static application security testing (typically Checkmarx) and secret detection. Black Duck and Checkmarx are licensed products; this project must stay free (`CLAUDE.md`: "free + synthetic"). Until 2026-09-28 the only automated check was SonarCloud's quality gate, which covers code quality and some security rules but not dependency CVEs or leaked secrets.

The repository is public, so GitHub's security features are free for it.

## Decision

Enable GitHub's built-in security features (repo **Settings → Advanced Security**) as the baseline, with free open-source scanners added in CI later:

| Concern | Licensed tool | What we use |
|---|---|---|
| Vulnerable dependencies (SCA) | Black Duck | **Dependabot alerts** + **grouped Dependabot security updates** (auto fix PRs) |
| Static analysis of our code (SAST) | Checkmarx | **CodeQL default setup** (Python, TypeScript/JavaScript, GitHub Actions; on every push/PR to `main` + weekly), alongside **SonarCloud** |
| Leaked secrets | — | **Secret scanning** + **push protection** (blocks a push that contains a recognised token) |
| Python deps, containers, licences, Terraform, secrets in diffs | Black Duck | Planned: CI `security` job with **pip-audit**, **Trivy**, **Checkov**, **gitleaks** and a licence allow-list (MM-G88, `docs/gcp/GCP_ROADMAP.md`) |

Workflow rule that came out of the first CodeQL scan: `ci.yml` sets `permissions: contents: read` at workflow level, and any job needing more `GITHUB_TOKEN` scope must ask for it explicitly at job level (e.g. `id-token: write` for GCP Workload Identity Federation).

## Rationale

- Zero cost, no extra accounts, results in the repo's **Security** tab next to the code.
- Covers the same control categories a bank reviewer expects from Black Duck + Checkmarx; the open-source CI scanners close the gaps GitHub's features leave (Python deps while `pyproject.toml` is unpinned, container images, licences, IaC).

## Consequences

- **Definition of Done** (`CONTRIBUTING.md`): a story must not introduce new open high/critical CodeQL or Dependabot alerts; push protection must never be bypassed for a real secret.
- **Dependabot PRs** are never merged blind: build/lint/typecheck the change first (for the frontend, also check the Vercel preview), and bundle any follow-up fixes into one PR, as done in MM-103 (which superseded Dependabot PR #58).
- **First results (2026-09-28, MM-103):** 4 CodeQL medium alerts (missing workflow permissions) and 23 Dependabot alerts in frontend npm packages (`next` critical, incl. an RCE in `next/og`); 0 secret-scanning alerts. All fixed in MM-103; `npm audit` → 0 vulnerabilities.
- Known gap until MM-G88: Dependabot cannot evaluate the unpinned Python dependencies.
