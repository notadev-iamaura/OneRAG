# OneRAG Ralph Loop Execution Plan

Date: 2026-05-05
Target branch: `main`
Harness: `onerag-release-harness`
Loop controller: `goals/continuation.md`

## Goal

Run OneRAG release-readiness work as a Ralph loop: set a concrete objective,
implement the smallest high-impact slice, verify it, decide whether the goal is
complete, and continue until either the goal is complete or the token/time budget
is exhausted.

## Priority Order

1. CI Trust: add frontend build/lint/test coverage to GitHub Actions and make
   backend coverage artifacts real.
2. Security Hygiene: add dependency monitoring and document audit triage rules
   before turning strict audit gates into merge blockers.
3. OSS Governance: add or tighten `CONTRIBUTING`, `SECURITY`, support, and issue
   and PR templates.
4. UX Accessibility: add focused accessibility tests for chat controls, dialogs,
   keyboard navigation, and visible labels.
5. Packaging: verify wheel contents include runtime config and non-Python assets
   needed outside editable installs.
6. Docs Drift: automate checks for renamed brand strings, version claims, and
   stale test-count claims.
7. Docker and Quickstart Smoke: add repeatable quickstart and compose smoke gates
   that do not require private secrets.
8. RAG Quality Evaluation: add seed fixtures and repeatable retrieval/answer
   quality metrics before tuning retrieval defaults.
9. Observability Contracts: verify realtime metrics, tracing payloads, and cost
   tracking through contract tests.
10. Advanced RAG Roadmap: stage agentic, multimodal, connector, and reranker
    improvements only after release gates are reliable.

## Execution Bundles

- Sequential foundation: CI Trust -> Security Hygiene -> OSS Governance.
- Parallel-ready validation: UX Accessibility, Docs Drift, and Packaging can run
  in separate branches because their write sets are mostly disjoint.
- Quality expansion: RAG Quality Evaluation and Observability Contracts should
  be paired because evaluation evidence needs trace and metric contracts.
- Final smoke: Docker and Quickstart Smoke should run after CI and packaging
  changes stabilize.

## Consensus Harness

For large bundles, use paired roles before implementation and before merge:

- Release Auditor A/B: confirm defect evidence and fix scope.
- Implementer A/B: work only on disjoint file sets or branches.
- Reviewer A/B: inspect diffs and verification output.
- Security Auditor A/B: review dependencies, auth, secrets, and PII impact.
- Docs Maintainer A/B: validate public instructions and examples.
- QA Verifier A/B: run the smallest sufficient command matrix.

If external subagent capacity is unavailable, the lead may continue only with a
recorded override and deterministic gates that cover the affected surface.

## Current Loop

- Loop ID: `2026-05-05-ci-trust`
- Bundle: CI Trust
- Objective: make CI cover the frontend release surface and make backend coverage
  upload meaningful instead of optional and empty.
- Planned changes:
  - Update `.github/workflows/ci.yml` branding and validation comments.
  - Add a frontend job running `npm ci`, `npm run build`, `npm run lint`, and
    `npm run test:run` from `frontend/`.
  - Change the backend test job to generate `htmlcov/` and `coverage.xml` before
    uploading coverage artifacts.
- Verification gates:
  - Workflow YAML parses.
  - Frontend build, lint, and Vitest suite pass locally.
  - Backend coverage command is syntactically valid and uses existing
    `pytest-cov` dependency.
  - Release-readiness docs link check passes when docs are changed.

## Loop Status Template

Use `goals/continuation.md` after each turn and carry forward `remaining` and
`next_loop` into the next response.

## Loop 1 Result

```yaml
status: continue
confidence: high
completed:
  - Added `goals/continuation.md` as the Ralph loop continuation prompt.
  - Added this execution plan with priority order, bundle sequencing, consensus
    harness roles, and current-loop gates.
  - Updated `.github/workflows/ci.yml` so backend tests generate real coverage
    artifacts and frontend build/lint/test are first-class CI gates.
remaining:
  - Security Hygiene is the next highest priority bundle.
  - UX Accessibility should follow because the frontend suite passes but emits
    existing Dialog/accessibility and React `act(...)` warnings.
verification:
  passed:
    - `ruby -e "require 'yaml'; YAML.load_file('.github/workflows/ci.yml')"`
    - `bash /Users/youngouksong/.codex/skills/onerag-release-harness/scripts/check_docs_links.sh`
    - `npm ci`
    - `npm run build`
    - `npm run lint`
    - `npm run test:run` (52 files, 473 tests)
    - `ENVIRONMENT=test uv run pytest --cov=app --cov-report=html --cov-report=xml --tb=short -q --timeout=60 --ignore=tests/integration tests/lib/test_environment.py` (9 tests)
    - `git diff --check`
  failed:
    - `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` failed because local Python lacks PyYAML; Ruby/Psych was used for YAML parsing instead.
  skipped:
    - Full backend suite was not run in this loop; a focused coverage smoke was
      used to validate the changed CI command shape and artifact generation.
next_loop:
  objective: add security/dependency governance without introducing a known-red CI gate
  bundle: security
stop_reason: null
```

## Loop 3 Result

```yaml
status: continue
confidence: high
completed:
  - Added `CONTRIBUTING.md` with setup, quality gates, architecture rules, and
    PR expectations.
  - Added `CODE_OF_CONDUCT.md` and `SUPPORT.md` for community norms and support
    routing.
  - Added GitHub bug report, feature request, issue config, and pull request
    templates.
  - Linked open-source governance docs from `docs/README.md`.
remaining:
  - UX Accessibility is the next highest priority bundle because passing
    frontend tests still emit accessibility and React state-update warnings.
  - Packaging and docs drift remain parallel-ready follow-ups.
verification:
  passed:
    - `ruby -e "require 'yaml'; Dir['.github/ISSUE_TEMPLATE/*.yml', '.github/dependabot.yml', '.github/workflows/*.yml'].each { |f| YAML.load_file(f) }"`
    - `bash /Users/youngouksong/.codex/skills/onerag-release-harness/scripts/check_docs_links.sh`
    - `git diff --check`
  failed: []
  skipped:
    - Runtime build/test matrix was not rerun locally because this loop changed
      governance documents and GitHub templates only; PR CI remains required.
next_loop:
  objective: convert observed frontend accessibility warnings into focused tests and fixes
  bundle: ux accessibility
stop_reason: null
```

## Loop 2 Result

```yaml
status: continue
confidence: high
completed:
  - Added `.github/dependabot.yml` for `uv`, `npm`, `github-actions`, and
    `pre-commit` weekly dependency update coverage.
  - Added `SECURITY.md` with supported versions, private vulnerability reporting
    guidance, response targets, and security boundaries.
  - Added `docs/security/dependency-triage.md` to define update priority,
    verification, and risk-acceptance rules.
  - Linked security documentation from `docs/README.md`.
remaining:
  - OSS Governance is the next highest priority bundle because issue/PR
    templates and contribution policy are still missing.
  - Security scanning is now governed, but strict audit gates should wait until
    the vulnerability baseline is documented.
verification:
  passed:
    - Official GitHub docs confirm Dependabot supports `uv`, `npm`,
      `github-actions`, and `pre-commit` ecosystems.
    - `ruby -e "require 'yaml'; YAML.load_file('.github/dependabot.yml'); YAML.load_file('.github/workflows/ci.yml')"`
    - `bash /Users/youngouksong/.codex/skills/onerag-release-harness/scripts/check_docs_links.sh`
    - `git diff --check`
  failed: []
  skipped:
    - Strict dependency audit gate was intentionally not added in this loop to
      avoid introducing a known-red CI gate before baseline triage.
next_loop:
  objective: add open-source contribution and issue/PR governance templates
  bundle: oss readiness
stop_reason: null
```
