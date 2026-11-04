# Security Policy

OneRAG is an open-source RAG system that may process private documents, prompts,
chat messages, and operational metadata. Please report security issues
privately and avoid publishing proof-of-concept exploits until a fix is
available.

## Supported Versions

Security fixes are prioritized for:

- The `main` branch.
- The latest tagged release, when releases are available.

Older branches are handled on a best-effort basis unless a maintainer explicitly
marks them as supported.

## Reporting a Vulnerability

Use GitHub's private vulnerability reporting or Security Advisory flow for this
repository. If private reporting is unavailable, open a minimal public issue
that says a security report is available, but do not include secrets,
credentials, exploit steps, private data, or payloads in the public issue.

Please include:

- Affected version, commit SHA, or deployment mode.
- Impacted component, such as API auth, PII handling, file ingestion, retrieval,
  frontend, CI, Docker, or dependency supply chain.
- Reproduction steps that use dummy data only.
- Expected impact and any known mitigations.

## Response Targets

- Critical: acknowledge within 2 business days and prioritize an emergency fix.
- High: acknowledge within 3 business days and target the next patch window.
- Medium/Low: triage within 5 business days and schedule with normal
  maintenance work.

## Security Boundaries

OneRAG should not require production secrets for local tests, CI validation, or
quickstart demos. Demo access codes, example API keys, and sample data must not
be treated as production credentials. Any change that weakens authentication,
PII masking, file validation, dependency pinning, or CI verification needs an
explicit security note in the pull request.

## Deployment Hardening Checklist

- Set `FASTAPI_AUTH_KEY` to a random value of at least 32 characters
  (`openssl rand -hex 32`). Without a key, the admin, upload and `/v1` APIs
  reject every request; placeholder or short keys refuse to start in production.
- Set `ENVIRONMENT=production` in the deployment environment. The default
  `docker-compose.yml` now reads this from `.env` instead of forcing
  `development`.
- Put the API behind a reverse proxy and set `TRUSTED_PROXY_IPS` to that
  proxy's address range. Forwarded-IP headers are only trusted from those
  addresses, so rate limits cannot be bypassed by spoofing `X-Forwarded-For`.
- Never inject the admin key into the frontend container. The frontend ignores
  `ADMIN_API_KEY`; operators enter the key in the settings page and it stays in
  their browser's localStorage.
- Keep `SQL_SEARCH_ENABLED=false` unless the database role used for SQL search
  is read-only and limited to the intended schema.
- Run `make audit` (pip-audit) before a release and keep the baseline table in
  `docs/security/dependency-triage.md` shrinking.
