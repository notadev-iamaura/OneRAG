# Admin AI Settings and Langfuse Tracking Plan

Date: 2026-06-25
Lead: Codex
Status: complete

## Objective

Implement and verify admin-facing operational controls for:

1. Selecting the active LLM provider/model from the GUI.
2. Replacing provider API keys from the GUI without exposing secrets to the browser.
3. Adding a Langfuse-backed tracking dashboard for recent question/answer activity trace summaries.
4. Adding product analytics for visitor/session/question/token usage, including 12-month summaries.

The work must follow a consensus-gated process: per-feature three-agent audit, documented unanimous decision before implementation, and a three-agent QA review after implementation.

## Initial Evidence

This table records the pre-implementation baseline. The final verified state is recorded in `Implementation Results`.

| Area | Evidence | Status |
|---|---|---|
| Admin settings UI | `frontend/src/pages/Admin/GlobalSettingsPage.tsx` already has a RAG settings tab and `defaultModel` select. | partial |
| Frontend runtime settings | `frontend/src/config/operatorSettings.ts` stores `defaultModel`, `ragProfile`, logo, and admin API key in local operator settings. | partial |
| Backend provider/model list | `app/api/services/openai_model_resolver.py` defines providers and available model IDs. | useful seed |
| Backend provider keys | Generation/embedding/reranker code still reads keys primarily from environment variables such as `GOOGLE_API_KEY`, `OPENAI_API_KEY`, and `OPENROUTER_API_KEY`. | gap |
| Admin metrics API | `app/api/admin.py` has `/api/admin/realtime-metrics` with live cost/token support, but `/api/admin/metrics` returns static sample data. | gap |
| Langfuse integration | `docs/LANGFUSE_SETUP.md` and `app/lib/langfuse_client.py` show existing Langfuse tracing support via environment variables. | partial |
| Trace coverage | RAG pipeline, chat service, generation, reranking, and evaluators already use `observe`/`record_generation` in several paths. | useful seed |

## Requirements

### R1. Model Selection GUI

- Admin can view supported providers and models.
- Admin can choose active provider/model.
- Active model setting is persisted server-side.
- Chat/RAG generation uses the active provider/model, not only local browser state.
- UI shows validation/apply status.

### R2. API Key GUI Replacement

- Admin can see whether a key is configured without seeing the raw key.
- Admin can replace the key for a supported provider.
- Raw key is never returned by any API response.
- Key is encrypted or delegated to a secret-management boundary before persistence.
- Replacement can be validated with a minimal provider test.
- Runtime behavior is explicit: either hot reload is supported or the UI marks restart required.
- Changes are protected by admin authentication and audited.

### R3. Langfuse Trace Dashboard

- Admin can inspect recent trace summaries for a bounded retention window, initially 7 days.
- Trace rows include time, trace/session identifiers, model, latency, token usage, and cost when available.
- Raw question/answer text is not exposed in OneRAG by default; full trace inspection remains in Langfuse under its own access controls.
- Trace collection is privacy-aware: redaction/retention behavior is documented and enforced.
- Langfuse settings are validated and failure-tolerant.

### R4. 12-Month Usage Analytics

- Admin can see visitor count, chat opens/sessions, question count, answer count, token usage, estimated cost, and average response time.
- 12-month summaries are backed by persisted event/aggregate data, not static samples.
- Visitor count is collected by application analytics events because Langfuse traces alone do not represent non-question page views.
- Analytics data does not store raw secrets or direct personal contact/payment identifiers.

### R5. Verification and QA

- Feature-level implementation decisions must be approved by three independent agents per feature area.
- QA must be reviewed by three independent agents after implementation.
- Any P0/P1 QA finding requires another implementation/review iteration.
- Verification commands must match the touched surface and be recorded here.

## Proposed Architecture

### Backend

- Add an admin settings persistence layer for AI provider/model settings.
- Store provider secrets server-side only, with response masking.
- Add admin endpoints:
  - `GET /api/admin/ai-settings`
  - `PATCH /api/admin/ai-settings`
  - `POST /api/admin/ai-settings/test`
  - `POST /api/admin/ai-settings/apply`
- Add analytics endpoints:
  - `POST /api/analytics/event`
  - `GET /api/admin/analytics/summary`
  - `GET /api/admin/analytics/timeseries`
  - `GET /api/admin/langfuse/traces`
  - `GET /api/admin/langfuse/daily-metrics`
- Replace static `/api/admin/metrics` with real aggregates or route it through the analytics service.

### Frontend

- Extend admin settings with an AI/provider tab:
  - provider select
  - model select
  - masked key status
  - key replacement input
  - test/apply actions
- Add a tracking dashboard:
  - KPI cards for visitors, sessions, questions, tokens, cost, latency
  - daily trend chart/table
  - model usage breakdown
  - recent 7-day trace table
- Emit privacy-scoped analytics events from the chat/embed UI.

### Security and Privacy

- Never persist third-party provider keys in localStorage.
- Never return raw provider keys from backend APIs.
- Mask sensitive data in logs and API responses.
- Rate-limit or at least admin-gate key validation endpoints.
- Record who/when changed active provider/model/key metadata where the auth layer provides identity.
- For trace summaries, document and enforce 7-day default retention plus redaction.

## Consensus Assignments

| Workstream | Agents | Status | Decision |
|---|---:|---|---|
| Model/API key GUI and backend settings | 3 | complete | unanimous reject-as-is; approve only after recursive admin secret redaction, server-side write-only secrets, scoped generation/internal LLM settings, and explicit apply/restart semantics. |
| Langfuse trace and usage analytics dashboard | 3 | complete | unanimous reject-as-is; approve only after raw Langfuse capture is constrained, durable app-owned analytics storage is added, and Langfuse remains a backend-only proxy/cache. |
| Final QA verification | 3 | complete | Initial QA found P0/P1/P2 issues; all blocking items were fixed and re-reviewed with no remaining P0/P1 findings. |

## Implementation Tracker

| Step | Status | Evidence |
|---|---|---|
| Repository snapshot captured | done | `git status --short --branch` on 2026-06-25 showed existing frontend settings/logo changes. |
| Plan document created | done | This document. |
| Model/API key 3-agent audit | done | Three auditors rejected frontend/local-only or broad runtime mutation; all required server-side settings, secret masking, and apply/restart semantics. |
| Langfuse/analytics 3-agent audit | done | Three auditors rejected dashboard-first work; all required raw trace capture mitigation and app-owned durable analytics. |
| Unanimous implementation boundary recorded | done | See Consensus Results below. |
| Backend settings/analytics implementation | done | Added server-side AI settings/key metadata store, recursive admin secret redaction, analytics event store/API, chat analytics events, Langfuse admin proxy endpoints, and raw-capture disabled high-level spans. |
| Frontend settings/dashboard implementation | done | Added AI provider/model/key controls to global settings, anonymous analytics event emission, visitor header propagation, and tracking tab with 12-month analytics/model usage/Langfuse summaries. |
| Documentation updates | done | Updated `docs/LANGFUSE_SETUP.md` and this plan with privacy/verification status. |
| Lead verification commands | done | Backend py_compile, targeted ruff, targeted pytest, full backend unit suite, frontend build warning gate, frontend test warning gate, and frontend lint passed. |
| QA 3-agent review | done | Three QA reviewers covered backend privacy/security, runtime AI setting behavior, and frontend dashboard/UX. |
| Iteration after QA findings | done | Fixed default override before save, invalid model persistence, provider-less LLM default leakage, Langfuse input/output preview exposure, streaming output capture, key-only restart ambiguity, and frontend tracking failure/visitor-count issues. |

## Verification Plan

Minimum expected commands after implementation:

```bash
cd frontend && npm run build:warning-gate
cd frontend && npm run test:warning-gate
ENVIRONMENT=test uv run pytest --tb=short -q --timeout=60 --ignore=tests/integration
```

Narrower targeted commands may be added once the touched files and test locations are known.

## Implementation Results

Backend:

- Added `app/api/admin_ai_settings_store.py` for server-side active provider/model settings and write-only provider key replacement. Raw keys are returned only from store internals to server provider clients; API responses return masked metadata.
- Added `app/api/analytics_event_store.py` and `app/api/analytics.py` for durable, privacy-scoped event capture. Visitor/session ids are hashed server-side, raw questions/answers are not stored, and referrer values are reduced to origin.
- Updated `app/api/admin.py` to recursively mask sensitive config/module responses, expose AI settings endpoints, replace sample metrics with analytics aggregates, and proxy Langfuse status/metrics/traces through admin-authenticated backend endpoints with a 7-day trace retention filter.
- Updated chat/generation paths so same-provider model changes can apply as request model overrides; provider/key changes remain restart-required to rebuild clients.
- Disabled high-level and generation-level Langfuse raw input/output capture in RAG pipeline, streaming chat spans, and generation observations.

Frontend:

- Added `frontend/src/services/analyticsService.ts` and visitor-id propagation through normal chat and SSE calls.
- Added AI provider/model/key controls to `frontend/src/pages/Admin/GlobalSettingsPage.tsx`; the API key draft is kept in memory only and cleared after replacement.
- Added a Tracking tab to `frontend/src/pages/Admin/AdminDashboard.tsx` for visitors/questions/tokens/cost, 12-month trends, model usage, and redacted Langfuse trace summaries including latency.
- Limited visitor page-view analytics to chat surfaces so admin dashboard visits do not inflate customer visitor counts.

Verification completed:

```bash
.venv/bin/python -m py_compile app/api/admin.py app/api/admin_ai_settings_store.py app/api/analytics_event_store.py app/api/analytics.py app/api/routers/chat_router.py app/modules/core/generation/generator.py app/lib/llm_client.py main.py
uv run ruff check app/api/admin.py app/api/admin_ai_settings_store.py app/api/analytics_event_store.py app/api/analytics.py app/api/routers/chat_router.py app/api/services/rag_pipeline.py app/api/services/chat_service.py app/api/routers/chat_router.py app/modules/core/generation/generator.py app/lib/llm_client.py main.py tests/unit/api/test_admin_secret_redaction.py tests/unit/api/test_admin_ai_settings_store.py tests/unit/api/test_analytics_event_store.py
ENVIRONMENT=test uv run pytest --tb=short -q --timeout=60 tests/unit/api/test_admin_secret_redaction.py tests/unit/api/test_admin_ai_settings_store.py tests/unit/api/test_analytics_event_store.py
ENVIRONMENT=test uv run pytest --tb=short -q --timeout=60 --ignore=tests/integration
cd frontend && npm run build:warning-gate
cd frontend && npm run test:warning-gate
cd frontend && npm run lint
```

QA results:

- Backend privacy/security QA: initial P1 issues around Langfuse input/output previews and streaming output capture were fixed; final re-review found no blocking issues.
- Runtime AI settings QA: initial P0/P1 issues around unsaved default override, model validation, and provider-less LLM factory defaults were fixed; final re-review found no blocking issues.
- Frontend/dashboard QA: initial P1/P2 issues around visitor counting, optional tracking failure handling, key draft clearing, and empty states were fixed; final re-review found no remaining issues.

## Consensus Results

### Model/API Key Workstream

Decision: approved only for a scoped secure implementation.

Required boundary:

1. Fix admin config/module secret exposure before exposing key management UI.
2. Add one recursive sanitizer for config-bearing admin responses.
3. Store provider secrets server-side only and return only masked metadata.
4. Scope initial model/key controls to answer generation and internal `/v1` LLM usage; do not include embedding model/key changes because embeddings require reindex/cache blast-radius handling.
5. Expose runtime behavior explicitly as hot-applied or restart-required. For this pass, prefer restart-required unless the touched modules can be proven to refresh safely.
6. Keep provider keys out of `operatorSettings`, `customSettings`, `window.RUNTIME_CONFIG`, exported JSON, URLs, and logs.

### Langfuse/Analytics Workstream

Decision: approved only for a privacy-first analytics implementation.

Required boundary:

1. Stop automatic raw question/answer capture on high-level Langfuse spans before showing traces in an admin UI.
2. Do not build 12-month usage analytics from Langfuse alone.
3. Add an application-owned durable analytics store for visitor/session/question/token/cost events.
4. Keep Langfuse keys server-only; expose only a backend admin proxy/cache with redacted trace summaries.
5. Default trace summary retention to 7 days.
6. Add partial/unavailable states for Langfuse-disabled or analytics-store-disabled deployments.

## Open Decisions

1. Whether encrypted provider keys are stored in the existing application database, a new local encrypted settings file, or an external Secret Manager. Current implementation should support encrypted local storage only when a server-side encryption secret is configured; otherwise it must avoid persisting raw provider keys.
2. Whether model/key changes should hot-reload generation clients or mark the service restart-required. Current implementation should expose restart-required as the conservative baseline.
3. Whether Langfuse trace rows should be fetched live from Langfuse, cached locally with 7-day TTL, or both. Current implementation should use backend-only live fetch with redaction and allow cache addition later.
4. Whether visitor identity uses anonymous localStorage client IDs only, or a hashed request-derived fallback for embedded contexts. Current implementation should accept anonymous client IDs and hash them server-side.
