# Contributing to OneRAG

Thanks for helping improve OneRAG. This project aims to stay easy to run,
modular, secure, and verifiable for real RAG deployments.

## Before You Start

1. Search existing issues and pull requests to avoid duplicate work.
2. Open an issue first for large behavior changes, new providers, new vector
   stores, security-sensitive changes, or public API changes.
3. Keep pull requests scoped to one clear problem.
4. Do not include real secrets, private documents, customer data, or production
   logs in issues, tests, commits, screenshots, or fixtures.

## Local Setup

```bash
uv sync
cd frontend && npm ci
```

For backend-only work, `uv sync` is enough. For frontend work, run commands from
the `frontend/` directory unless a script says otherwise.

## Quality Gates

Run the smallest sufficient set for the files you touched:

```bash
make lint
make type-check
make lint-imports
ENVIRONMENT=test uv run pytest --tb=short -q --timeout=60 --ignore=tests/integration
```

```bash
cd frontend
npm run warning-gate:self-test
npm run build:warning-gate
npm run lint
npm run test:warning-gate
```

Docker, quickstart, and integration changes should also include the relevant
compose or smoke-test evidence in the pull request.

## Architecture Expectations

- Use the existing dependency-injection providers and factories.
- Keep LLM calls behind the configured LLM factory.
- Register vector database changes through the vector store and retriever
  factories.
- Use structured `ErrorCode` based errors for new backend error paths.
- Add observability fields through the existing metrics models when adding new
  runtime metrics.
- Do not add `TODO` or `FIXME` comments. Resolve the issue or open a tracked
  follow-up.

## Pull Request Checklist

Before opening a PR:

- Rebase or branch from the latest `main`.
- Include a concise summary of user-visible behavior.
- List commands run and their results.
- Call out skipped checks and why they were skipped.
- Include screenshots or API examples for user-facing UI/API changes.
- Note security, privacy, migration, or compatibility impact when relevant.

Maintainers may ask for smaller PRs when a change mixes unrelated behavior,
refactors, and documentation.
