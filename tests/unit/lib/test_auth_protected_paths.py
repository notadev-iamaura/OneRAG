"""
보호 경로 설정 가능성 테스트 (Phase 4.6)

목적:
    OpenAI 호환 API(/v1)의 인증 여부를 배포마다 설정할 수 있도록
    protected_paths가 환경변수 FASTAPI_PROTECTED_PATHS로 오버라이드되는지 검증한다.
"""

from __future__ import annotations

import pytest

from app.lib.auth import APIKeyAuth


def test_protected_paths_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """환경변수가 없으면 기본 보호 경로는 /v1/이어야 한다."""
    monkeypatch.delenv("FASTAPI_PROTECTED_PATHS", raising=False)
    auth = APIKeyAuth()
    assert auth.protected_paths == ["/v1/"]


def test_protected_paths_empty_disables_v1_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FASTAPI_PROTECTED_PATHS=''이면 /v1 무인증(보호 경로 없음)이어야 한다."""
    monkeypatch.setenv("FASTAPI_PROTECTED_PATHS", "")
    auth = APIKeyAuth()
    assert auth.protected_paths == []


def test_protected_paths_custom_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """콤마 구분 환경변수로 여러 보호 경로를 지정할 수 있어야 한다."""
    monkeypatch.setenv("FASTAPI_PROTECTED_PATHS", "/v1/, /api/admin")
    auth = APIKeyAuth()
    assert auth.protected_paths == ["/v1/", "/api/admin"]


def test_explicit_arg_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """명시적 인자는 환경변수보다 우선해야 한다."""
    monkeypatch.setenv("FASTAPI_PROTECTED_PATHS", "/v1/")
    auth = APIKeyAuth(protected_paths=["/custom"])
    assert auth.protected_paths == ["/custom"]
