#!/usr/bin/env python3
"""Small guardrail hook for high-risk OneRAG shell commands."""

import json
import re
import sys
from typing import Any

DANGEROUS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"(^|[\s;&|])git\s+reset\s+--hard(\s|$)"),
        "`git reset --hard` discards user work. Ask the user for explicit approval and explain the affected files.",
    ),
    (
        re.compile(r"(^|[\s;&|])git\s+checkout\s+--\s+"),
        "`git checkout --` can discard user work. Use a targeted patch or ask the user first.",
    ),
    (
        re.compile(r"(^|[\s;&|])git\s+clean\s+-[^\s;&|]*[df][^\s;&|]*(\s|$)"),
        "`git clean` can delete untracked user files. Ask the user before running it.",
    ),
    (
        re.compile(r"(^|[\s;&|])rm\s+-[^\s;&|]*r[^\s;&|]*f[^\s;&|]*\s+/(?:\s|$)"),
        "`rm -rf /`-style commands are blocked by the harness.",
    ),
    (
        re.compile(r"(^|[\s;&|])sudo\s+rm\s+"),
        "`sudo rm` is too destructive for an unattended harness step.",
    ),
    (
        re.compile(r"(^|[\s;&|])chmod\s+-R\s+777(\s|$)"),
        "`chmod -R 777` weakens filesystem permissions broadly.",
    ),
    (
        re.compile(r"(^|[\s;&|])(mkfs|diskutil\s+erase|dd\s+if=.*\s+of=/dev/)"),
        "Disk formatting or raw device writes are outside the engineering harness.",
    ),
]

SECRET_READ_PATTERN = re.compile(
    r"(^|[\s;&|])(cat|less|more|head|tail|sed|awk)\b.*"
    r"(^|[\s\"'])\.env(\s|$|[\s\"'])|"
    r"(^|[\s;&|])(cat|less|more|head|tail|sed|awk)\b.*"
    r"\.env\.(?!example\b|quickstart\b)[A-Za-z0-9_.-]+",
    re.DOTALL,
)


def _read_payload() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _command_text(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""

    command = tool_input.get("command") or tool_input.get("cmd")
    if isinstance(command, str):
        return command
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    return ""


def _deny_pre_tool(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def _deny_permission(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {
                        "behavior": "deny",
                        "message": reason,
                    },
                }
            }
        )
    )


def _block_reason(command: str) -> str | None:
    for pattern, reason in DANGEROUS_PATTERNS:
        if pattern.search(command):
            return reason
    if SECRET_READ_PATTERN.search(command):
        return "Reading local secret env files is blocked. Use `.env.example` or documented sample env files instead."
    return None


def main() -> int:
    payload = _read_payload()
    command = _command_text(payload)
    reason = _block_reason(command)
    if reason is None:
        return 0

    event_name = payload.get("hook_event_name")
    if event_name == "PermissionRequest":
        _deny_permission(reason)
    else:
        _deny_pre_tool(reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
