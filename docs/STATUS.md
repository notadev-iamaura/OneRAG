# OneRAG Current Status

Last updated: 2026-06-10

This page is the canonical current status for git-tracked documentation. Older
roadmaps and reports may preserve their original historical findings, but this
page reflects the current `main` branch after PR #72.

## Source Of Truth

| Item | Current value |
|---|---|
| Repository | `notadev-iamaura/OneRAG` |
| Current release-readiness baseline | `main` after PR #72 |
| Latest merged commit | `51c944e` (Merge PR #72) |
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

PRs #70–#72 passed `Lint`, `Type Check` (mypy, 560 source files), `Architecture`
(3 contracts kept, 0 broken), and the backend test suite (0 failures) before
merge.

## Recent Remediation (PR #70–#72)

A `max`-level code review surfaced 28 defects, all fixed across PR #70 (28
defects) and PR #71/#72 (5 deferred-improvement items). Each fix used TDD and
strict-signature stubs (not permissive `AsyncMock`) so signature/wiring drift is
caught in CI.

Fully resolved:

- **Security/data (P0):** PII masking re-enabled (missing `base.yaml` imports),
  IDOR closed (UUID4 capability sessions), prompt-injection truncation bypass.
- **Silent failures (P0):** `/v1` RAG signature, ingest 500 (`container.wire()`),
  reranker v2.1 wiring, document-management for 4 vector DBs, cost/realtime
  metrics (no more `random` values), Grok/Agentic dependencies, circuit breaker.
- **Generality:** output language, BM25 tokenizer Protocol, Korean prompt/trigger
  externalization, OpenAI provider direct support.
- **Stability:** evaluation datetime, event-loop blocking (`to_thread`),
  WebSocket reconnect race, `quality_score` propagation, streaming fallback + PII
  chunk buffering, rate-limiter `None` return.
- **Cleanup:** dead-code removal, cache-key params, semantic-cache leak, tenacity
  backoff standardization (+jitter), prompt-content TTL cache, shared `l2_norm`.

Resolved conditionally / deferred by design (NOT silently — documented in code):

- **SQLite upload-job store (multi-worker):** defended for single-worker deploys
  and warned in code; multi-worker + SQLite still risks job loss → use Postgres.
- **Prompt cache (multi-worker):** Level 2 (TTL + write invalidation) only.
  Multi-worker needs Level 3 (Postgres `LISTEN/NOTIFY`) — noted in code.
- **Deferred by design:** `session_manager._cleanup_loop` (infinite loop — jitter
  only), embedder normalization bodies (intentionally different; only `_l2_norm`
  shared), prompt cache Level 3.

## Verification Scope and Limits

CI static gates (lint, mypy, import-linter, backend tests) pass, but this is NOT
equivalent to full production verification:

- `spaCy`/`ko_core_news_sm` and `sentence-transformers` are not installed in the
  default env, so **PII-detector and local-reranker behavior tests are skipped**.
- **External-service E2E** (Weaviate, live LLM providers, PostgreSQL) is exercised
  via stubs/fakes or skipped; real-connection behavior is not asserted here.
- The added "mock-free smoke" tests use strict-signature **fakes**, which catch
  wiring/signature drift but are not live-dependency integration tests.

For release decisions requiring real-backend confidence, run the integration
suites with optional extras installed and a live Weaviate/PostgreSQL/LLM target.

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
