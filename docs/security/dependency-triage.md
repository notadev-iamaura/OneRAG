# Dependency Triage

This guide defines how OneRAG handles dependency and supply-chain updates.

Reference: [GitHub Dependabot supported ecosystems](https://docs.github.com/en/code-security/dependabot/ecosystems-supported-by-dependabot/supported-ecosystems-and-repositories).

## Automated Coverage

Dependabot is configured for:

- `uv` at the repository root for Python project metadata and lockfile updates.
- `npm` in `frontend/` for the Vite/React application.
- `github-actions` at the repository root for workflow action updates.
- `pre-commit` at the repository root for hook revision updates.

Weekly update PRs are intentionally separate by ecosystem so CI failures can be
isolated quickly.

## Triage Rules

- Security updates for direct runtime dependencies take priority over routine
  version bumps.
- Critical and high vulnerability PRs should include a short risk note, affected
  surface, and verification evidence before merge.
- Routine minor and patch updates may be merged after the normal CI matrix
  passes.
- Major updates require a compatibility note and should not be grouped with
  unrelated maintenance changes.
- Do not add a strict audit gate until the current vulnerability baseline is
  documented and either fixed or explicitly accepted.

## Verification Matrix

Use the smallest sufficient command set for the dependency surface:

- Python runtime or tooling: `uv sync --frozen`, `uv run ruff check .`,
  `uv run mypy .`, and targeted `ENVIRONMENT=test uv run pytest ...`.
- Frontend runtime or tooling: `npm ci`, `npm run build`, `npm run lint`, and
  `npm run test:run` from `frontend/`.
- GitHub Actions: workflow YAML parse plus the pull request's own Actions run.
- Pre-commit hooks: `uv run pre-commit run --all-files` when hook behavior
  changes.

## Risk Acceptance

If a vulnerability cannot be fixed immediately, record:

- Package name and advisory identifier.
- Affected runtime path.
- Why the package is not exploitable or why mitigation is temporary.
- Owner and target date for revisiting the decision.

Risk acceptance should be visible in a pull request, issue, or release-readiness
note, not only in local chat history.
