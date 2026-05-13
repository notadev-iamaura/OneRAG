# OneRAG Current Status

Last updated: 2026-05-13

This page is the canonical current status for git-tracked documentation. Older
roadmaps and reports may preserve their original historical findings, but this
page reflects the current `main` branch after PR #48.

## Source Of Truth

| Item | Current value |
|---|---|
| Repository | `notadev-iamaura/OneRAG` |
| Current release-readiness baseline | `main` after PR #48 |
| Latest merged operational-stability commit | `fe87219fde0c07ceae61880d93851bee24abca69` |
| Runtime readiness model | `/health` for liveness, `/ready` for readiness |
| Retrieval startup policy | `RETRIEVAL_STARTUP_POLICY=required|degraded` |
| Local Docker default | degraded retrieval startup allowed |
| Production Docker default | retrieval readiness required |

## CI Gates

The GitHub Actions CI pipeline currently covers:

- `Lint`: `uv run ruff check .`
- `Type Check`: `uv run mypy .`
- `Architecture`: `uv run lint-imports`
- `Test + Coverage`: backend pytest with coverage artifact generation
- `Runtime Smoke`: `make test-operational-smoke`
- `Frontend`: `npm run build:warning-gate`, `npm run lint`, `npm run test:warning-gate`
- `LLM Cost Analysis`: token/cost reporting workflow

Remote verification for PR #48 passed all of the above gates before merge.

## Runtime Contracts

- `/health` is a lightweight liveness endpoint. It should answer when the API
  process is alive.
- `/ready` is the deployment readiness endpoint. It checks startup state and
  retrieval health.
- If retrieval is unhealthy and `RETRIEVAL_STARTUP_POLICY=required`, `/ready`
  returns HTTP 503.
- If retrieval is unhealthy and `RETRIEVAL_STARTUP_POLICY=degraded`, `/ready`
  can return `status: "degraded"` while the process remains live.
- Docker API healthchecks use `/ready`, not `/health`.

## Quickstart Data Safety

- `quickstart/load_sample_data.py` no longer resets the target Weaviate
  collection by default.
- `easy_start/load_data.py` no longer resets the local Chroma collection by
  default.
- Use `--reset`, `ONERAG_QUICKSTART_RESET=true`, or
  `ONERAG_EASY_START_RESET=true` only when an intentional sample-data reset is
  desired.
- Quickstart sample objects use deterministic IDs so reruns update the sample
  set instead of duplicating it.

## Documentation Status

- Current setup and operational status should be read from this page,
  `README.md`, `docs/SETUP.md`, `CONTRIBUTING.md`, and `docs/CODEX_HARNESS.md`.
- Files under `docs/release-readiness/` and older phase reports are historical
  execution records unless they explicitly say they are current.
- Version labels in older reports are historical. Use the Git SHA and CI gates
  above for current release-readiness evidence.
