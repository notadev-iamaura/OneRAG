# OneRAG Ralph Loop Continuation Prompt

Use this prompt at the end of every autonomous OneRAG release-readiness turn.
Its job is to decide whether the current goal is complete, whether another loop
should run, or whether the work must stop because a budget or blocker was hit.

## Active Goal

- Goal ID: `onerag-release-readiness`
- Objective: make OneRAG release-ready as an open-source RAG project by removing
  verified P0/P1 blockers, strengthening CI and verification, and recording
  evidence for every merge decision.
- Current loop: set by the lead before work starts.
- Token budget: stop when the configured turn budget is exhausted, even if the
  objective is not complete.
- Evidence budget: every loop must leave commands, results, changed files, and
  residual risks in the turn summary or a release-readiness document.

## Done Criteria

Mark the goal `complete` only when all conditions below are true:

1. No known P0 release blockers remain.
2. No known P1 issue lacks either a fix, a tracked follow-up, or an explicit
   risk acceptance.
3. The relevant build, lint, test, docs, Docker, or security gates for the
   changed surface have passed.
4. The local working tree used for implementation is clean after commit.
5. The PR or merge state is recorded with branch, commit SHA, and verification.

## Loop Decision

At the end of each turn, answer these questions in order:

1. What was the active loop objective?
2. What changed, and which files were touched?
3. Which verification gates passed, failed, or were skipped?
4. Are any P0 or P1 blockers still open?
5. Is the remaining work inside the current token/time budget?
6. Should the next loop continue, pause, or escalate?

## Required Output Shape

```yaml
status: continue | complete | blocked | budget_exhausted
confidence: low | medium | high
completed:
  - item
remaining:
  - item
verification:
  passed:
    - command or gate
  failed:
    - command or gate
  skipped:
    - command or gate with reason
next_loop:
  objective: short description
  bundle: release boot | ci trust | security | oss readiness | ux accessibility | rag quality | packaging | docs drift
stop_reason: null or concise reason
```

## Operating Constraints

- Start implementation from a clean snapshot of the target branch.
- Preserve unrelated user changes in the shared workspace.
- Do not merge if a P0 verification gate fails.
- Prefer small, mergeable PRs over broad mixed changes.
- If paired subagents are unavailable, the lead may proceed only after recording
  the missing review capacity and compensating with deterministic local gates.
- If the loop stops before completion, the next response must start from the
  `remaining` and `next_loop` fields rather than restarting discovery.
