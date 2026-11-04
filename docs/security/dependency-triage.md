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
- Frontend runtime or tooling: `npm ci`, `npm run warning-gate:self-test`,
  `npm run build:warning-gate`, `npm run lint`, and
  `npm run test:warning-gate` from `frontend/`.
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

## Automated Audit (CI)

- `make audit` exports the runtime lock (`uv export --no-dev`) and runs
  `pip-audit --no-deps` against the pinned versions.
- The GitHub Actions job `Security Audit` runs the same check on every push and
  pull request and writes the report to the job summary and an artifact.
- The job is **non-blocking** (`continue-on-error: true`) until the baseline
  below is empty. When it is, remove `continue-on-error` so the audit becomes a
  merge gate.

## Current Baseline (2026-11-02)

The 2026-11-02 remediation moved FastAPI 0.104 / Starlette 0.27 to the current
Starlette 1.x line and refreshed 28 vulnerable transitive packages (pypdf, pillow,
aiohttp, anyio, cryptography, urllib3, requests, lxml, nltk, pymongo, ...),
bringing pip-audit from 409 findings in 33 packages down to the list below.
Every item here is an **accepted, temporary** risk with an owner action:

| Package | Pinned | Why it is still here | Planned action |
|---|---|---|---|
| `langchain`, `langchain-core`, `langchain-openai`, `langchain-anthropic`, `langchain-text-splitters` | 0.2.x | The 0.2 line is end-of-life; fixed versions are on the 0.3/1.x lines, which change the serialization and splitter APIs. OneRAG only imports `langchain_core.documents/messages/chat_history` and the text splitters, so the surface is small but needs a dedicated migration PR with the ingestion tests. | Migrate to the 1.x line in a separate PR; re-run `make audit`. |
| `langsmith` | 0.1.x | Follows the langchain pin above. | Upgrade together with langchain. |
| `chromadb` | 0.5.0 | 1.x is a major release with a new client API and pulls in a much larger dependency tree. Chroma is the `easy_start` local store, not the production default (Weaviate). | Evaluate 1.x in the optional-providers job before moving the pin. |
| `protobuf` | 4.25.x | Fixed versions are 5.29.6+/6.33.5+, blocked by the `google-generativeai` pin. | Upgrade when the Gemini SDK pin moves. |
| `fsspec` | 2026.2.x | Fixed in 2026.6.0, blocked by the `datasets`/`huggingface-hub` resolution. | Re-check after the next `uv lock --upgrade-package fsspec`. |

Re-run the audit after any of these pins change and shrink the table.
