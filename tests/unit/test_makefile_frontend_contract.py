import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"


def _target_block(target: str) -> str:
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(target)}:[^\n]*\n(?P<body>(?:\t.*\n|#.*\n|\n)*)",
        text,
        flags=re.MULTILINE,
    )
    assert match, f"Makefile target not found: {target}"
    return match.group("body")


def test_frontend_make_targets_use_warning_gate() -> None:
    assert "npm run build:warning-gate" in _target_block("frontend-build")
    assert "npm run test:warning-gate" in _target_block("frontend-test")


def test_frontend_install_uses_lockfile_exact_install() -> None:
    assert "npm ci" in _target_block("frontend-install")


def test_warning_gate_self_test_target_is_available() -> None:
    assert "npm run warning-gate:self-test" in _target_block(
        "frontend-warning-gate-self-test"
    )
