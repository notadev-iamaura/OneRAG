# OneRAG Current Status

Last updated: 2026-06-10

This page is the canonical current status for git-tracked documentation. Older
roadmaps and reports may preserve their original historical findings, but this
page reflects the current `main` branch after PR #78.

## Source Of Truth

| Item | Current value |
|---|---|
| Repository | `notadev-iamaura/OneRAG` |
| Current release-readiness baseline | `main` after PR #78 |
| Latest merged commit | `43c4605` (Merge PR #78) |
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
- `Optional Providers`: optional-provider unit tests (vector stores, BM25,
  rerankers, embedders) run with extras installed and
  `ONERAG_RUN_OPTIONAL_PROVIDER_TESTS=1`. These are skipped by the default
  `Test + Coverage` gate (`pytest_ignore_collect`), so this job makes their
  staleness fail CI instead of hiding. Network-free by policy
  (`HF_HUB_OFFLINE=1`); real-model reranker inference stays in integration
  verification.
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

### Follow-up hardening (PR #76–#78)

A full optional-provider test run (normally skipped by the default gate) surfaced
and fixed three more issues:

- **Stale weaviate test (PR #76):** `add_documents` batch (`insert_many`, from
  backport #69) was asserted against the old single-`insert` API. The test had
  never run in CI because its directory is in the optional-provider skip list, so
  the drift went unnoticed for a full backport cycle.
- **`Optional Providers` CI gate (PR #77/#78):** a new CI job runs the
  optional-provider unit tests with extras installed and
  `ONERAG_RUN_OPTIONAL_PROVIDER_TESTS=1`, network-free by policy
  (`HF_HUB_OFFLINE=1`; real-model reranker inference stays in integration
  verification). This class of staleness can no longer hide.
- **pinecone extra conflict (PR #77):** the `pinecone`/`all-vectordb` extras
  pinned the deprecated `pinecone-client`, which broke `import pinecone` against
  base `pinecone>=7.0.1`; repointed to `pinecone>=7.0.1`.

All 14 open Dependabot PRs (#50–#68) were also verified and merged; the combined
`main` CI (including the new gate) is green.

### Structural hardening (PR #80–#81)

A second xhigh review confirmed 15 defects; PR #80 fixed the P0/P1 set (metrics
self-deadlock, DI async-Singleton Future unwrapping for `/v1`/agent, streaming
PII buffer, circuit-breaker HALF_OPEN accounting, pgvector filter-key SQL
parameterization, blocking `fetch_objects`, inline conversation persistence,
WS server-confirmed session id, shipped reranker default back to `google`).
PR #81 then attacked the recurrence mechanisms themselves:

- **Config liveness guard**: every `app/config/features/*.yaml` must be in
  `base.yaml` imports (explicit allowlist with reasons) and every imported
  yaml's top-level section must survive `load_config()` — replaces the stale
  hardcoded 3-section check. `tools.yaml`/`mcp` dead-config fixed (agent
  `output_language` now actually loads).
- **Wiring completeness**: `container.wire(packages=WIRED_PACKAGES)` replaces
  the hand-maintained module list; an AST-based guard test fails if any module
  uses `Provide[]`/`@inject` outside the wired packages.
- **Single source of truth for optional-provider tests**: the CI job runs the
  whole `tests/unit` tree with `ONERAG_RUN_OPTIONAL_PROVIDER_TESTS=1` instead
  of duplicating the conftest path list; real-model tests self-declare via
  `ONERAG_RUN_REAL_MODEL_TESTS` (and `make verify-integration` now actually
  runs them).
- **RetryPolicy adopted**: the three hand-rolled tenacity wait implementations
  (notion, llm_enricher, sitemap) and the demo cleanup-loop backoff now route
  through `app/lib/retry.py`; the LINEAR increment default matches its
  documented `initial*(attempt+1)` equivalence.

## Verification: Static Gates + Integration

### Static gates (every PR, fast, no external deps)

`lint` (ruff), `mypy` (strict), `lint-imports` (3 contracts, 0 broken), and the
backend test suite all pass. These are necessary but NOT sufficient for
production confidence — they exercise external services via strict-signature
fakes, not live connections.

### Integration verification (PR #74, extended by the live-provider matrix)

`make verify-integration` (see `docs/INTEGRATION_VERIFICATION.md`) stands up a
local **Weaviate + PostgreSQL(pgvector) + Qdrant** stack
(`docker-compose.verify.yml`) and runs the integration suite plus
optional-provider tests with real connections.

### Live provider matrix

Mock-based unit tests cannot catch external API contract violations (a pinecone
regression passed CI exactly this way). Coverage is now tiered:

| Provider | Tier | How |
|---|---|---|
| Weaviate | local verify stack | hybrid-search integration suite |
| PostgreSQL (sessions) | local verify stack | race/persistence suite |
| pgvector | local verify stack | `tests/integration/vector_stores/test_pgvector_live.py` (real parameterized-filter contract) |
| Qdrant | local verify stack | `tests/integration/vector_stores/test_qdrant_live.py` |
| Chroma | no service needed | `test_chroma_live.py` (PersistentClient — runs everywhere) |
| Pinecone | weekly cloud smoke | `.github/workflows/live-provider-smoke.yml` + `tests/integration/live/` (measures the `$in` mixed-type and unit-vector/top_k contracts) |
| MongoDB Atlas | weekly cloud smoke | document-management roundtrip (vector search needs a pre-built index — out of scope) |

The weekly smoke skips gracefully (success + notice) until the repository
secrets (`PINECONE_API_KEY`, `PINECONE_TEST_INDEX`, `MONGODB_ATLAS_URI`) are
configured. The `pgvector` extra now includes `psycopg[binary]` (the driver the
store actually imports — previously in no extra at all).

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
