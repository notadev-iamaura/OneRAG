# Frontend Warning Gate Goal

## Goal

Prevent OneRAG frontend quality regressions by making targeted React, Radix Dialog,
and Tailwind warning classes fail local CI-equivalent commands and GitHub Actions.

## Why This Exists

The previous loop removed known React `act(...)`, Radix Dialog accessibility, and
Tailwind ambiguous utility warnings. Passing tests alone is not enough: those
warnings can return in a future PR while `vitest` or `vite build` still exits
successfully.

## Done Criteria

This goal is complete only when all of the following are true:

1. A warning-gate wrapper streams command output and fails on the targeted
   warning classes.
2. `frontend/package.json` exposes warning-gated build and test commands.
3. GitHub Actions uses the warning-gated frontend build and test commands.
4. Any currently exposed targeted warnings are fixed rather than allowlisted.
5. Local verification passes:
   - `npm run warning-gate:self-test`
   - `npm run build:warning-gate`
   - `npm run lint`
   - `npm run test:warning-gate`
6. The PR passes all GitHub checks and is merged.
7. The post-merge `main` CI run completes successfully.

## Harness Loop

1. Audit A/B independently confirm the defect and minimal fix shape.
2. Lead implements only the agreed warning-gate surface.
3. Reviewer/QA gates validate positive and negative warning detection.
4. Merge is allowed only when no P0 gate fails.
5. Stop when `main` has a successful CI run for the merge commit.

## Targeted Warning Classes

- React `act(...)` boundary warnings
- React invalid DOM nesting warnings
- Radix Dialog missing `DialogTitle`
- Radix Dialog missing `DialogDescription` / undefined `aria-describedby`
- Tailwind ambiguous utility warnings
