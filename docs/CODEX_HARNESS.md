# Codex Engineering Harness

Last updated: 2026-05-13

이 문서는 OneRAG에서 Codex를 하네스 기반으로 쓰기 위한 전역/프로젝트 설정과 운영 방법을 정리한다.

## Research Basis

설정은 OpenAI Codex 공식 문서의 현재 구조를 기준으로 만들었다.

- `AGENTS.md`: 전역 `~/.codex/AGENTS.md`와 프로젝트 `AGENTS.md`가 함께 로드되며, 더 가까운 디렉터리의 지침이 나중에 병합된다.
- `config.toml`: 개인 기본값은 `~/.codex/config.toml`, 프로젝트 오버라이드는 `<repo>/.codex/config.toml`에 둔다.
- `rules/`: 전역 또는 프로젝트 레이어의 `rules/*.rules`로 샌드박스 밖 실행 정책을 관리한다.
- `hooks/`: `SessionStart`, `PreToolUse`, `PermissionRequest` 같은 생명주기 훅으로 컨텍스트 주입과 위험 명령 차단을 할 수 있다.
- `subagents`: 명시적으로 요청한 경우에만 병렬 subagent를 사용하고, 복잡한 점검은 독립 감사/리뷰로 나눌 수 있다.

참고:

- [AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md)
- [Config basics](https://developers.openai.com/codex/config-basic)
- [Rules](https://developers.openai.com/codex/rules)
- [Hooks](https://developers.openai.com/codex/hooks)
- [Subagents](https://developers.openai.com/codex/subagents)
- [Best practices](https://developers.openai.com/codex/learn/best-practices)

## Installed Layers

전역 레이어:

- `~/.codex/AGENTS.md`: 모든 레포에서 공유되는 엔지니어링 하네스 원칙
- `~/.codex/config.toml`: 기본 승인/샌드박스/문서 탐색/훅 설정
- `~/.codex/hooks/harness_session.py`: 세션 시작 시 하네스 컨텍스트를 짧게 주입
- `~/.codex/hooks/harness_guard.py`: 위험한 shell 명령과 로컬 secret env 파일 읽기 차단
- `~/.codex/rules/harness.rules`: remote publish, dependency install, Docker, destructive command 계열은 승인 흐름으로 보냄

프로젝트 레이어:

- `AGENTS.md`: OneRAG 전용 작업 규칙과 검증 매트릭스
- `.codex/config.toml`: OneRAG 프로젝트의 reasoning, approval, hook 설정
- `.codex/hooks/onerag_harness_session.py`: OneRAG 하네스 컨텍스트 주입
- `.codex/hooks/onerag_harness_guard.py`: OneRAG 위험 명령 차단
- `.codex/rules/onerag-harness.rules`: OneRAG 원격/의존성/Docker 작업 승인 정책

## When To Use The Harness

다음 작업은 하네스를 켠 것으로 간주한다.

- release-readiness, CI, build/test failure, Docker, quickstart
- auth, secret, dependency, PII, security triage
- public docs, OSS governance, README/quickstart drift
- frontend accessibility, warning-gated build/test
- RAG quality, eval, tracing, retrieval/reranker contract
- packaging, deploy, publish, PR 준비

작은 단일 파일 수정은 전체 paired-agent 운영까지 필요하지 않다. 대신 같은 게이트를 로컬로 축약한다: 증거 확인, 수정 범위 고정, 최소 검증, 잔여 리스크 기록.

## Operating Flow

1. Snapshot: `git status --short`로 기존 변경을 확인한다.
2. Evidence: 같은 문제를 두 번 독립적으로 확인한다. subagent가 명시 요청되지 않았으면 lead가 로컬에서 두 관점으로 확인한다.
3. Scope: 만질 파일과 검증 명령을 먼저 정한다.
4. Edit: `apply_patch`를 사용하고 unrelated refactor를 피한다.
5. Verify: 변경 표면에 맞는 최소 명령을 실행한다.
6. Review: diff를 버그, 회귀, 보안, 테스트 누락 중심으로 검토한다.
7. Report: 실행한 명령, 실패/스킵 사유, 잔여 리스크를 남긴다.

## Verification Matrix

Backend:

```bash
ENVIRONMENT=test uv run pytest --tb=short -q --timeout=60 --ignore=tests/integration
uv run ruff check .
uv run mypy .
uv run lint-imports
```

Frontend:

```bash
cd frontend && npm run build:warning-gate
cd frontend && npm run lint
cd frontend && npm run test:warning-gate
```

Docker/quickstart:

```bash
make test-operational-smoke
docker compose config --quiet
docker compose --profile fullstack build frontend
```

Docs:

```bash
rg "referenced-command-or-file" docs README.md README_EN.md
```

## Subagent Prompt Templates

Subagents는 사용자가 명시적으로 요청한 경우에만 사용한다.

Audit:

```text
Role: <role> <A/B>. Inspect <branch/path> for <workstream>.
Do not modify files. Produce: evidence, severity, proposed fix boundary,
commands to verify, and disagreement risk.
```

Worker:

```text
Role: Worker <A/B>. You are not alone in the codebase.
Own only <files/modules>. Do not revert others' work.
Implement the agreed fix from <audit summary>. Run relevant checks.
Final answer must list changed files and command results.
```

Review:

```text
Role: Reviewer <A/B>. Review the diff for <workstream>.
Prioritize blockers, regressions, missing tests, security risks.
Approve only if evidence supports merge.
```

## Gitignore Policy

`.codex/config.toml`, `.codex/hooks/*.py`, `.codex/rules/*.rules`, `AGENTS.md`, and this document are intended to be committed. Local Codex runtime state, logs, temporary files, and machine-local overrides are ignored.

Use `AGENTS.override.md` or `.codex/*.local.*` for local-only overrides. Do not commit secrets, transcripts, shell snapshots, or generated Codex logs.

## Maintenance

- 전역 정책을 바꿀 때는 `~/.codex/AGENTS.md`와 `~/.codex/rules/harness.rules`를 먼저 수정한다.
- OneRAG 전용 정책은 `AGENTS.md`와 `.codex/` 아래에서 수정한다.
- 훅이 너무 강하게 막으면 `.codex/hooks/onerag_harness_guard.py`에서 패턴을 좁힌다.
- Codex를 재시작해야 새 전역/프로젝트 config, rules, hooks가 안정적으로 반영된다.
