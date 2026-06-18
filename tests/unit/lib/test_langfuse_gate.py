"""Langfuse import-시점 활성/비활성 게이트 회귀 테스트.

배경(2026-06-18 데이터 플로우 검증에서 발견):
    기존 게이트는 `os.getenv("LANGFUSE_ENABLED") == "False"`(정확 문자열)만 비활성
    처리해, 사용자가 자연스럽게 쓰는 소문자 `false`/`0`/`off` 등은 비활성되지 않고
    실제 SDK가 로드되는 footgun이 있었다(끄려 했는데 키가 있으면 trace 전송).
    `_langfuse_disabled_by_env`는 false 계열을 대소문자/형식 무관하게 인식한다.

이 게이트는 활성 트레이싱(@observe/langfuse_context 전역 SDK)의 권위 있는
on/off 스위치이므로 회귀를 테스트로 고정한다.
"""

from __future__ import annotations

import pytest

from app.lib.langfuse_client import _langfuse_disabled_by_env


class TestLangfuseEnvGate:
    def test_environment_test_always_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
        assert _langfuse_disabled_by_env() is True

    @pytest.mark.parametrize("val", ["false", "False", "FALSE", "0", "no", "off", " false "])
    def test_false_forms_disable_regardless_of_case(
        self, monkeypatch: pytest.MonkeyPatch, val: str
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("LANGFUSE_ENABLED", val)
        assert _langfuse_disabled_by_env() is True, f"{val!r}는 비활성이어야 함(footgun 방지)"

    @pytest.mark.parametrize("val", ["true", "True", "1", "yes", "on"])
    def test_truthy_forms_keep_enabled(
        self, monkeypatch: pytest.MonkeyPatch, val: str
    ) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("LANGFUSE_ENABLED", val)
        assert _langfuse_disabled_by_env() is False

    def test_unset_enables_outside_test(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 미설정 시 기존 동작 보존: 비-test 환경에서는 SDK 로드(키 없으면 SDK가 inert).
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
        assert _langfuse_disabled_by_env() is False

    def test_test_env_overrides_truthy_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 테스트 격리 우선: ENVIRONMENT=test면 LANGFUSE_ENABLED=true여도 비활성.
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("LANGFUSE_ENABLED", "true")
        assert _langfuse_disabled_by_env() is True
