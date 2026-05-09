#!/usr/bin/env python3
"""Load concise OneRAG harness context at Codex session start."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _read_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _find_repo_root(cwd: Path) -> Path:
    for path in (cwd, *cwd.parents):
        if (path / ".git").exists() or (path / "pyproject.toml").exists():
            return path
    return cwd


def main() -> int:
    payload = _read_payload()
    cwd = Path(payload.get("cwd") or ".").resolve()
    repo_root = _find_repo_root(cwd)
    harness_doc = repo_root / "docs" / "CODEX_HARNESS.md"

    context = [
        "OneRAG harness context is active.",
        "Before edits, inspect `git status --short` and preserve user changes.",
        "For release, CI, security, docs, accessibility, RAG quality, or packaging work, use the OneRAG consensus gates before implementation.",
        "Prefer the narrowest verification command that proves the touched surface.",
    ]
    if harness_doc.exists():
        context.append("Harness usage is documented at `docs/CODEX_HARNESS.md`.")

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "\n".join(context),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
