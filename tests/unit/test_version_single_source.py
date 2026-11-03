"""버전 단일 진실원 검증: pyproject.toml, app.__version__, FastAPI 앱, /health 가 같은 값을 내야 한다."""

from __future__ import annotations

import tomllib
from pathlib import Path


def _pyproject_version() -> str:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def test_app_version_matches_pyproject() -> None:
    import app

    assert app.__version__ == _pyproject_version()


def test_health_response_default_version_matches_pyproject() -> None:
    from app.api.health import HealthResponse

    field = HealthResponse.model_fields["version"]
    assert field.default == _pyproject_version()


def test_changelog_latest_release_matches_pyproject() -> None:
    """CHANGELOG의 최신 릴리스 헤더([x.y.z])가 패키지 버전과 같아야 한다(릴리스 시 함께 올릴 것)."""
    import re

    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M)
    assert match is not None, "CHANGELOG에 릴리스 헤더가 없습니다"
    assert match.group(1) == _pyproject_version()
