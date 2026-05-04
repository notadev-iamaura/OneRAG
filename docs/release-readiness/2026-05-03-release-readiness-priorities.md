# OneRAG Release Readiness Priorities

Date: 2026-05-03
Baseline: `origin/main` after PR #2, #3, #4 merges (`ad08f19`)

## Evidence Used

- `npm ci` succeeded in a clean temp clone.
- `npm run build` failed because `./icons/BrandLogo` is imported but not present in tracked source.
- `docker-compose.yml` references `frontend/Dockerfile.local`, but only `frontend/Dockerfile` is tracked.
- `.github/workflows/ci.yml` runs Python checks only.
- Two independent auditor subagents agreed on the main release blockers.
- Official Codex docs show subagents, skills, GitHub Action workflows, guardrails, and evals as first-class surfaces for this kind of workflow.

## Top 10 Priorities

| Rank | Work | Effect | Difficulty | Why Now | Dependencies | Parallel Group |
|---:|---|---:|---:|---|---|---|
| 1 | Restore frontend production build by tracking/fixing `BrandLogo` imports and ignored icon assets | 5 | 1 | `npm run build` currently fails on `PageHeader.tsx`/`Sidebar.tsx` imports | None | A |
| 2 | Fix Docker fullstack compose frontend build path | 5 | 1 | `docker-compose.yml` points to missing `frontend/Dockerfile.local` | None | A |
| 3 | Restore quickstart `.env` template and command consistency | 5 | 1 | README/Makefile reference `quickstart/.env.quickstart`, but auditors found it missing in tracked repo | None | A |
| 4 | Add frontend CI gate: `npm ci`, `npm run build`, `npm run lint`, `npm run test:run` | 5 | 2 | Frontend failures reached `main` because CI does not cover frontend | 1 | B |
| 5 | Make backend coverage artifact real and verify claimed test counts | 4 | 2 | CI uploads `htmlcov/` without generating coverage; README claims need automation | None | B |
| 6 | Add dependency/security gate and automation | 4 | 2 | `npm ci` reported vulnerabilities; no audit/Dependabot/Renovate gate exists | 4 preferred | C |
| 7 | Add accessibility regression checks and fix known semantic issues | 4 | 2 | Auditor saw Dialog title/description and invalid HTML warnings; sidebar has clickable non-buttons | 4 preferred | E |
| 8 | Add open-source governance files and templates | 3 | 1 | `CONTRIBUTING`, `SECURITY`, `CODE_OF_CONDUCT`, `SUPPORT`, issue/PR templates are absent | None | D |
| 9 | Fix packaging/runtime data inclusion | 4 | 2 | `pyproject.toml` package data likely omits YAML/JSON/easy-start/quickstart assets | 3 preferred | G |
| 10 | Repair docs drift: brand, version, setup, missing docs links | 3 | 2 | Docs mention older names, versions, and missing files | 3, 5 preferred | H |

## Parallelization Plan

Wave 1, release boot:
- Group A1: BrandLogo/build blocker.
- Group A2: Docker compose path.
- Group A3: quickstart env template.
- These can run in parallel because write sets are mostly disjoint.

Wave 2, trust gates:
- Group B1: frontend CI.
- Group B2: backend coverage/test-count verification.
- Group C1: dependency/security gate design.
- B1 depends on BrandLogo being fixed if the branch must pass immediately.

Wave 3, quality surface:
- Group E1: accessibility warnings and tests.
- Group D1: open-source governance files.
- Group G1: package data and Docker image improvements.

Wave 4, product depth:
- Group H1: docs drift cleanup.
- Group F1: RAG trace backend payloads and RAGAS/eval fixtures.

## Sequential Gates

1. Fix P0 release boot tasks.
2. Run frontend build/lint/test locally.
3. Add CI gates.
4. Confirm CI passes on PR.
5. Add governance/security/docs after build gates are green.
6. Move to RAG quality and deeper observability after release trust is restored.

## Recommended First PRs

1. `fix/release-boot-assets-compose-quickstart`
2. `ci/frontend-and-coverage-gates`
3. `security/dependency-and-demo-access-hardening`
4. `docs/oss-governance-and-drift`
5. `ux/accessibility-regression-suite`
