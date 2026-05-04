# OneRAG Consensus Agent Harness

Date: 2026-05-03
Global skill installed: `/Users/youngouksong/.codex/skills/onerag-release-harness`

## Goal

Operate OneRAG maintenance through paired subagents, independent evidence gathering, consensus gates, and explicit verification before merge.

## Harness Rules

1. Every workstream starts with two independent auditors.
2. Implementation starts only after both auditors agree on the issue and fix boundary.
3. Each implementation task has a clearly owned write set.
4. No two workers edit the same files unless a lead serializes the work.
5. Every patch gets two independent reviewers.
6. Merge requires passing gates or a documented lead override.
7. P0 build/test failures cannot be overridden.

## Role Matrix

| Role | Minimum Agents | Main Output | Merge Authority |
|---|---:|---|---|
| Release Auditor | 2 | ranked blockers with file/log evidence | no |
| Implementer | 2 for large/disjoint work, 1 for small lead-owned work after paired audit | patch and changed-file list | no |
| Reviewer | 2 | approve/reject diff with commands | no |
| QA Verifier | 2 | verification transcript and residual risk | no |
| Security Auditor | 2 | auth/dependency/secrets risk decision | veto on security regressions |
| Lead Orchestrator | 1 | resolves disagreements, sequences work, merges | yes |

## Consensus States

- `agreed`: both agents identify same defect and compatible fix.
- `needs-third-pass`: agents disagree on severity, scope, or fix.
- `blocked`: required secret, account, infra, or approval is unavailable.
- `lead-override`: lead proceeds despite disagreement with explicit evidence.

## Workstream Assignment

### Bundle A, Release Boot

Scope:
- `frontend/src/components/icons/BrandLogo.tsx`
- `.gitignore`
- `docker-compose.yml`
- `frontend/Dockerfile`
- `quickstart/*`
- `README.md`, `README_EN.md`, `Makefile`

Agents:
- Release Auditor A/B
- Implementer A: asset/gitignore/build fix
- Implementer B: Docker/quickstart fix
- Reviewer A/B
- QA Verifier A/B

Required gates:
- `npm run build`
- `docker compose config`
- quickstart file existence checks

### Bundle B, CI Trust

Scope:
- `.github/workflows/ci.yml`
- `frontend/package.json`
- `Makefile`
- coverage configuration

Agents:
- Release Auditor A/B
- Implementer A: frontend CI
- Implementer B: backend coverage/test-count gate
- Reviewer A/B
- QA Verifier A/B

Required gates:
- workflow syntax review
- local `npm run build`, `npm run lint`, `npm run test:run`
- backend collect/test command or documented blocker

### Bundle C, Security

Scope:
- `frontend/package*.json`
- dependency automation config
- access control and demo auth docs
- secret handling docs

Agents:
- Security Auditor A/B
- Implementer A: dependency automation/gates
- Implementer B: demo access control cleanup
- Reviewer A/B

Required gates:
- no committed secrets
- no weakened auth defaults
- npm audit result or blocked-network record

### Bundle D, OSS Readiness

Scope:
- `CONTRIBUTING.md`
- `SECURITY.md`
- `CODE_OF_CONDUCT.md`
- `SUPPORT.md`
- `.github/ISSUE_TEMPLATE/*`
- `.github/pull_request_template.md`

Agents:
- Docs Maintainer A/B
- Reviewer A/B

Required gates:
- all linked docs exist
- instructions match repository commands

### Bundle E, Accessibility

Scope:
- chat sidebar
- dialogs/modals
- prompt views
- axe helper/tests

Agents:
- UX Accessibility Auditor A/B
- Implementer A: semantic controls
- Implementer B: tests/warnings
- Reviewer A/B
- QA Verifier A/B

Required gates:
- targeted Vitest passes
- no known Dialog title/description warnings

### Bundle F, RAG Quality

Scope:
- RAG pipeline trace payloads
- RAG Trace panel contract
- RAGAS/eval fixtures
- retrieval/reranker metrics

Agents:
- RAG Architect A/B
- Backend Implementer A/B
- Frontend Implementer A/B only if API contract changes
- Reviewer A/B

Required gates:
- unit tests for trace schema
- sample trace visible in UI
- eval command documented

## Execution Template

Use this prompt shape for each paired audit:

```text
Role: <role> <A/B>. Inspect <branch/path> for <workstream>.
Do not modify files. Produce: evidence, severity, proposed fix boundary,
commands to verify, and any disagreement risk.
```

Use this prompt shape for workers:

```text
Role: Worker <A/B>. You are not alone in the codebase.
Own only <files/modules>. Do not revert others' work.
Implement the agreed fix from <audit summary>. Run relevant checks.
Final answer must list changed files and command results.
```

Use this prompt shape for reviewers:

```text
Role: Reviewer <A/B>. Review the diff for <workstream>.
Prioritize blockers, regressions, missing tests, security risks.
Approve only if evidence supports merge.
```

## Current Bootstrap Decision

The next safe execution should start with Bundle A because two independent auditors agreed that current `main` has release-blocking frontend build and compose failures.
