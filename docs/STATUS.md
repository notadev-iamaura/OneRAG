# OneRAG Current Status

Last updated: 2026-06-10

This page is the canonical current status for git-tracked documentation. Older
roadmaps and reports may preserve their original historical findings, but this
page reflects the current `main` branch after PR #74.

## Source Of Truth

| Item | Current value |
|---|---|
| Repository | `notadev-iamaura/OneRAG` |
| Current release-readiness baseline | `main` after PR #74 |
| Latest merged commit | `c9036c8` (Merge PR #74) |
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

PRs #70–#74 passed `Lint`, `Type Check` (mypy, 560 source files), `Architecture`
(3 contracts kept, 0 broken), and the backend test suite (0 failures) before
merge.

## Recent Remediation (PR #70–#74)

A `max`-level code review surfaced 28 defects, all fixed across PR #70 (28
defects), PR #71/#72 (5 deferred-improvement items), and PR #74 (integration
verification + 1 regression caught). Each fix used TDD and strict-signature
stubs (not permissive `AsyncMock`) so signature/wiring drift is caught in CI.

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

## Verification: Static Gates + Integration

### Static gates (every PR, fast, no external deps)

`lint` (ruff), `mypy` (strict), `lint-imports` (3 contracts, 0 broken), and the
backend test suite all pass. These are necessary but NOT sufficient for
production confidence — they exercise external services via strict-signature
fakes, not live connections.

### Integration verification (PR #74, reproducible)

`make verify-integration` (see `docs/INTEGRATION_VERIFICATION.md`) stands up a
local **Weaviate + PostgreSQL** stack (`docker-compose.verify.yml`) and runs the
integration suite plus optional-provider tests with real connections.

Verified against live services on 2026-06-10:

- ✅ Weaviate hybrid search (real connection): 21 passed
- ✅ PostgreSQL session race-condition / persistence: 9 passed
- ✅ spaCy Korean NER (PII detector): 18 passed (previously skipped)
- ✅ `sentence-transformers` local embedder: 10 passed (previously skipped)

Integration verification caught a regression that static gates missed: the
`test_session_race_condition` duplicate-ID test predated the IDOR fix (weak
`session_id` rejection, PR #70) and failed; it was updated to use a valid UUID4.
This is the concrete reason static-gate green ≠ production-verified.

### Still not asserted here

- **Neo4j GraphRAG** integration runs only when Neo4j is started separately
  (`docker-compose.neo4j.yml`, `NEO4J_URI`).
- **Live LLM** tests (real token cost) run when `GOOGLE_API_KEY` / `OPENAI_API_KEY`
  / `OPENROUTER_API_KEY` is set; skipped otherwise.
- **Multi-worker scenarios** (SQLite job store, prompt-cache invalidation
  propagation) are single-worker-safe but not exercised under multiple workers.

For release decisions, run `make verify-integration` with optional extras
installed (see the guide) and, if needed, Neo4j + live LLM keys.

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
