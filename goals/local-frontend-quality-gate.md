# Local Frontend Quality Gate Goal

## Goal

Make the repository's first-class local frontend commands match the GitHub
Actions frontend warning gate so contributors cannot accidentally bypass the
same React, Radix Dialog, React DOM nesting, and Tailwind warning checks that CI
enforces.

## Done Criteria

This goal is complete only when:

1. `make frontend-build` routes through `npm run build:warning-gate`.
2. `make frontend-test` routes through `npm run test:warning-gate`.
3. `make frontend-warning-gate-self-test` is available.
4. Frontend install uses `npm ci` for lockfile-exact dependency setup.
5. Contributor/security/frontend docs recommend the warning-gated commands.
6. A Makefile contract test prevents these local targets from drifting again.
7. Local verification passes.
8. The PR passes GitHub Actions, is merged, and post-merge `main` CI succeeds.

## Committee Decision

Three independent auditors identified the same drift: CI uses warning-gated
frontend build/test commands, while `Makefile` and contributor docs still
pointed contributors at the ungated commands. The easy-start Makefile issue was
recorded as a separate follow-up because it did not have paired consensus in
this loop.
