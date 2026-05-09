# OneRAG Codex Instructions

## Repository Profile

OneRAG is a FastAPI + React/Vite RAG system with modular retrieval, privacy, evaluation, and frontend chat surfaces. Treat release, CI, security, docs, and RAG-quality work as harnessed work: inspect first, keep scope tight, and verify with the smallest command set that proves the change.

## Working Agreements

- Start code-changing tasks with `git status --short` and preserve any user changes already present.
- Prefer `rg` and `rg --files` for repo search.
- Keep edits close to the relevant module. Avoid opportunistic refactors and metadata churn.
- Use `apply_patch` for hand edits.
- Do not read or print local secret files such as `.env`, `.env.local`, or production env files. Use `.env.example` and documented sample files instead.
- Ask before adding or upgrading production dependencies, enabling broad network access, changing auth defaults, or deleting user data.

## OneRAG Harness

Use the OneRAG release harness for release-readiness, CI, frontend/backend verification, security, OSS maintenance, accessibility, RAG quality, tracing, or packaging tasks.

- If the user explicitly asks for subagents or paired agents, run independent paired audits before implementation and paired reviews after implementation.
- If subagents are not explicitly requested, do the same gates locally: make two independent evidence passes, record the chosen fix boundary, then edit.
- Implementation starts only after the defect, scope, and verification path are clear.
- For parallel worker work, keep write ownership disjoint and tell workers they are not alone in the codebase.
- P0 build/test/security failures block merge unless the user explicitly redirects.

## Verification Matrix

Choose the smallest sufficient verification set:

- Backend unit work: `ENVIRONMENT=test uv run pytest --tb=short -q --timeout=60 --ignore=tests/integration`
- Backend quality: `uv run ruff check .`, `uv run mypy .`, `uv run lint-imports`
- Frontend build: `cd frontend && npm run build:warning-gate`
- Frontend lint/test: `cd frontend && npm run lint`, `cd frontend && npm run test:warning-gate`
- Frontend accessibility/UI: targeted Vitest or Playwright checks plus a browser smoke when visual behavior changes
- Docker/quickstart: `docker compose config` and the narrow compose/build command tied to the touched files
- Docs: check linked files and command names against the repo

Record skipped checks and blockers explicitly in the final response.

## Project References

- Harness usage: `docs/CODEX_HARNESS.md`
- Existing consensus design: `docs/release-readiness/2026-05-03-consensus-agent-harness.md`
- Frontend warning gate: `goals/frontend-warning-gate.md`
- Local frontend quality gate: `goals/local-frontend-quality-gate.md`
