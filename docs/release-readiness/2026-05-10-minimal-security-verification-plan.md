# Minimal Security And Verification Plan

Date: 2026-05-10

## Goal

Restore the smallest stable operating boundary for OneRAG before broader release work:

- Do not expose backend server API keys to browser runtime config.
- Protect OpenAI-compatible `/v1/*` HTTP routes with the existing API key middleware.
- Protect `/chat-ws` WebSocket connections without sending `FASTAPI_AUTH_KEY` to the browser.
- Make local/CI frontend Node versions consistent.
- Restore `lint-imports` reproducibility without adding new tooling.

## Consensus Evidence

Security Auditor A and the lead agreed on these P0 issues:

- `frontend/generate-config.js` and `frontend/entrypoint.sh` write API key material into `window.RUNTIME_CONFIG`.
- `frontend/src/services/api.ts` reads `VITE_API_KEY` or `window.RUNTIME_CONFIG.API_KEY` and sends it as `X-API-Key`.
- `app/lib/auth.py` protects only `/api/` by default, leaving `/v1/*` outside the global HTTP auth boundary.
- `app/api/routers/websocket_router.py` accepts `/chat-ws` before checking any API key.

Verification Auditor B and the lead agreed on these P1 issues:

- `import-linter` already exists in project dependencies, but the local console script can become stale after a workspace move.
- CI uses Node 20 while `frontend/Dockerfile` uses Node 18 and no checked-in Node version pin exists.

Post-implementation reviewers found one important correction:

- Removing browser API key injection while leaving all `/api/*` behind global `X-API-Key` auth breaks production frontend chat.
- The stable boundary is: `/v1/*` uses server API key auth; browser chat stays server-key-free and rate-limited; `/chat-ws` uses a session-scoped HMAC token issued by `/api/chat/session`.
- A final operability review found that document/admin-style frontend modules call protected APIs. The stable default is to disable those modules unless a deployment explicitly enables and fronts them with an appropriate auth path.

## Fix Boundary

In scope:

- Remove browser runtime API key generation and automatic public `X-API-Key` injection.
- Set `APIKeyAuth` default protected paths to `/v1/` so browser chat is not blocked by a server-only key.
- Keep explicit router-level `X-API-Key` dependencies for admin, upload, documents, ingestion, evaluations, monitoring, and privileged tools.
- Keep document, admin, prompts, and analysis frontend modules disabled by default because they call protected server-key APIs.
- Add WebSocket validation before registering `/chat-ws`, accepting either server-client API key auth or a browser-safe session token.
- Add Node 20 pin files/config.
- Add a Makefile repair target for stale virtualenv console scripts.
- Add targeted tests for `/v1` protection, WebSocket token auth, and public browser chat operability.

Out of scope:

- JWT, OAuth, BFF/proxy server, or new session architecture.
- Full API authorization redesign.
- Dependency upgrades unrelated to Node pinning.
- Docker image optimization.
- Full frontend test performance work.
- Long-lived user identity, JWT, OAuth, or revocation beyond short token expiry.

## Implementation Checklist

- [x] Document plan and consensus.
- [x] Remove frontend runtime API key exposure.
- [x] Protect `/v1/*` in the existing API key middleware.
- [x] Keep browser chat operational without public server API key injection.
- [x] Disable protected management frontend modules by default.
- [x] Protect `/chat-ws` before accepting operational traffic.
- [x] Pin frontend Node to 20.
- [x] Add local `lint-imports` repair path.
- [x] Add targeted regression tests.
- [x] Run narrow verification commands.

## Expected Verification

Primary:

```bash
ENVIRONMENT=test .venv/bin/python -m pytest tests/lib/test_auth_security.py tests/unit/api/routers/test_websocket_router.py --tb=short -q --timeout=60
uv run ruff check .
uv run lint-imports
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH node --version
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm run build:warning-gate
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm run lint
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm run test:warning-gate
```

Fallback if local virtualenv scripts are stale:

```bash
make repair-venv-scripts
uv run lint-imports
```

## Verification Results

Passed:

```bash
ENVIRONMENT=test .venv/bin/python -m pytest tests/lib/test_auth_security.py tests/unit/api/routers/test_websocket_router.py --tb=short -q --timeout=60
uv run ruff check .
make repair-venv-scripts
uv run lint-imports
cd frontend && node --check generate-config.js
cd frontend && node --check check-env.js
cd frontend && sh -n entrypoint.sh
cd frontend && ./node_modules/.bin/tsc --noEmit --pretty false
cd frontend && npm run warning-gate:self-test
git diff --check
```

Node 20 frontend release gates passed:

```bash
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH node --version
# v20.20.2

cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm ci
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm run build:warning-gate
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm run lint
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH ./node_modules/.bin/tsc --noEmit --pretty false
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm run test:warning-gate
# Test Files 52 passed (52)
# Tests 474 passed (474)
```

Observed but not blocking this fix:

- Homebrew installed `node@20` as a keg-only runtime, so shells that do not prepend `/opt/homebrew/opt/node@20/bin` may still resolve the previously installed Node `v24.9.0`.
- `npm ci` reports existing third-party package deprecation notices, but dependency installation and all frontend gates pass under Node `v20.20.2`.
- Document/admin/prompt/analysis UI modules are disabled by default. Enabling them still requires a separate browser-safe auth path, server-side proxy, or private/admin deployment model.

## Production Deployment Verification

Result: release gates are closed for the default production boundary as of 2026-05-10. Remaining risks are environment or scope exceptions, not known build, lint, unit, or production Dockerfile failures.

Backend gates passed:

```bash
env UV_PROJECT_ENVIRONMENT=/private/tmp/onerag-verify-venv uv sync --frozen
/private/tmp/onerag-verify-venv/bin/ruff check app main.py tests
/private/tmp/onerag-verify-venv/bin/mypy . --show-traceback
/private/tmp/onerag-verify-venv/bin/lint-imports --no-cache
ENVIRONMENT=test /private/tmp/onerag-verify-venv/bin/python -m pytest --tb=short -q --timeout=60 --ignore=tests/integration
```

Backend results:

```text
Ruff: all checks passed.
Mypy: success, no issues found in 501 source files.
Import-linter: all 3 contracts kept.
Default non-integration pytest suite: passed with 2 optional spaCy NER skips and 1 known XFAIL.
```

Frontend Node 20 release gates passed:

```bash
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm audit --audit-level=high
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm run lint
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm run build:warning-gate
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm run test:warning-gate
```

Frontend results:

```text
npm audit: found 0 vulnerabilities.
Vitest: Test Files 52 passed (52), Tests 474 passed (474).
Build/lint/warning gates: passed under Node v20.20.2.
```

Docker and compose gates passed:

```bash
docker compose config --quiet
env WEAVIATE_API_KEY=... FASTAPI_AUTH_KEY=... VITE_... docker compose -f docker-compose.prod.yml config --quiet
env BUILDX_GIT_INFO=0 ... docker compose --progress plain -f docker-compose.prod.yml build frontend
env BUILDX_GIT_INFO=0 docker buildx build --check --file Dockerfile .
env BUILDX_GIT_INFO=0 docker buildx build --load --progress=plain --file Dockerfile -t onerag-api-currentpath-verify:latest .
env WEAVIATE_API_KEY=... FASTAPI_AUTH_KEY=... VITE_... BUILDX_GIT_INFO=0 docker compose --progress plain -f docker-compose.prod.yml build api
```

Docker results:

```text
Default and production compose configs are valid.
Production frontend image builds successfully and runs lint plus build warning gate inside Docker.
API Dockerfile check passes with no warnings.
API image builds successfully from the current project path and installs dependencies from uv.lock using uv export --frozen --no-dev.
Production compose API build completes successfully and exports `onerag-api:latest`.
```

## Local Regression Verification

Result on 2026-05-11: local non-production regression gates passed. Initial test attempts exposed macOS CloudDocs file materialization delays, but targeted reruns and final full gates passed after the relevant files were read locally.

Additional backend gates passed:

```bash
/private/tmp/onerag-verify-venv/bin/ruff check app main.py tests
/private/tmp/onerag-verify-venv/bin/mypy . --show-traceback
/private/tmp/onerag-verify-venv/bin/lint-imports --no-cache
ENVIRONMENT=test /private/tmp/onerag-verify-venv/bin/python -m pytest --tb=short -q --timeout=60 --ignore=tests/integration
```

Additional frontend Node 20 gates passed:

```bash
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm ci
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm audit --audit-level=high
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm run lint
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm run build:warning-gate
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH npm run test:warning-gate
cd frontend && PATH=/opt/homebrew/opt/node@20/bin:$PATH ./node_modules/.bin/tsc --noEmit --pretty false
```

Additional Docker/runtime gates passed:

```bash
docker compose config --quiet
docker compose --profile fullstack config --quiet
env WEAVIATE_API_KEY=... FASTAPI_AUTH_KEY=... VITE_... docker compose -f docker-compose.prod.yml config --quiet
env WEAVIATE_API_KEY=... FASTAPI_AUTH_KEY=... VITE_... BUILDX_GIT_INFO=0 docker compose --progress plain -f docker-compose.prod.yml build api
env WEAVIATE_API_KEY=... FASTAPI_AUTH_KEY=... VITE_... BUILDX_GIT_INFO=0 docker compose --progress plain -f docker-compose.prod.yml build frontend
env BUILDX_GIT_INFO=0 docker buildx build --check --file Dockerfile .
docker run --rm --entrypoint python -e ENVIRONMENT=test -e FASTAPI_AUTH_KEY=... -e WEAVIATE_URL=http://localhost:8080 -e WEAVIATE_API_KEY=... onerag-api:latest -c "import main; print('api-runtime-ok')"
docker run --rm --entrypoint sh onerag-frontend:latest -c "test -s /usr/share/nginx/html/index.html && test -x /entrypoint.sh && echo frontend-runtime-ok"
```

Local regression results:

```text
Backend final pytest: passed, with 2 optional spaCy NER skips and 1 known XFAIL.
Frontend Vitest: Test Files 52 passed (52), Tests 474 passed (474).
Frontend audit: found 0 vulnerabilities.
API image runtime smoke: api-runtime-ok.
Frontend image runtime smoke: frontend-runtime-ok.
Git status: completed with `GIT_OPTIONAL_LOCKS=0 git -c core.trustctime=false -c core.checkStat=minimal status --porcelain=v1 --ignore-submodules --no-renames`.
Known enrichment XFAIL: fixed after the full run; `tests/unit/enrichment` now passes without XFAIL.
```

Production hardening fixes completed in this pass:

- Removed browser runtime API key exposure while preserving public browser chat.
- Protected `/v1/*` and WebSocket traffic without exposing `FASTAPI_AUTH_KEY` to frontend code.
- Added a production compose profile with authenticated Weaviate and no host-published database ports.
- Made the batch crawler opt-in through `START_BATCH_CRAWLER=true`.
- Moved local embedding dependencies behind the `local-embedding` extra and made provider-heavy imports lazy.
- Replaced the API Docker install path with a lockfile-bound `uv export --frozen --no-dev` install.
- Constrained backend and frontend Docker contexts with allowlist `.dockerignore` files.
- Removed unstable PWA build output and updated frontend docs to match the actual shipped behavior.
- Moved frontend test/build-only packages to `devDependencies` and resolved high-severity npm audit findings.

## Residual Risk

- Integration and real-provider tests are still outside the default release gate. They require live services or explicit provider credentials.
- The WebSocket token is short-lived and session-bound, but it is still a bearer token in the WebSocket URL. It avoids leaking `FASTAPI_AUTH_KEY`, but it is not a full user identity or revocation system.
- The local Desktop workspace can repeatedly report macOS `dataless` file flags and slow first reads. This caused first-run pytest/import, Docker context, standard `git status`, and `git diff --check` delays, but the functional build/test/runtime gates passed after materialization. Secret env files and local data directories were not read or printed.
- Local frontend `npm run build:warning-gate` can report Vite's `NODE_ENV=production` env-file warning if an uncommitted local frontend env file is present. The production Docker frontend build excludes local env files and completed cleanly.
