"""
환경 변수 검증 유틸리티(EnvValidator) 단위 테스트

대상 모듈: app/lib/env_validator.py
테스트 범위: EnvValidationResult, _mask_value, validate_tool_use_env,
            validate_required_env, validate_all, get_missing_env_help, 편의 함수
"""

import pytest

from app.lib.env_validator import (
    EnvValidationResult,
    EnvValidator,
    validate_all_env,
    validate_provider_env,
    validate_required_env,
    validate_tool_use_env,
)

# ---------------------------------------------------------------------------
# EnvValidationResult 데이터클래스 (2개)
# ---------------------------------------------------------------------------


class TestEnvValidationResult:
    """EnvValidationResult 데이터클래스 생성 테스트"""

    def test_valid_result_creation(self) -> None:
        """유효한 결과 생성: is_valid=True, 빈 missing_vars, 빈 warnings"""
        result = EnvValidationResult(is_valid=True, missing_vars=[], warnings=[])

        assert result.is_valid is True
        assert result.missing_vars == []
        assert result.warnings == []

    def test_invalid_result_creation(self) -> None:
        """유효하지 않은 결과 생성: is_valid=False, missing_vars와 warnings 포함"""
        result = EnvValidationResult(
            is_valid=False,
            missing_vars=["VAR_A", "VAR_B"],
            warnings=["경고 메시지"],
        )

        assert result.is_valid is False
        assert result.missing_vars == ["VAR_A", "VAR_B"]
        assert len(result.warnings) == 1


# ---------------------------------------------------------------------------
# _mask_value 정적 메서드 (3개)
# ---------------------------------------------------------------------------


class TestMaskValue:
    """_mask_value 마스킹 로직 테스트"""

    def test_long_value_masks_after_visible_chars(self) -> None:
        """긴 값(>4자)은 앞 4자만 노출하고 나머지를 '***'로 마스킹"""
        result = EnvValidator._mask_value("ABCDEFGH")

        assert result == "ABCD***"

    def test_short_value_returns_all_masked(self) -> None:
        """짧은 값(<=4자)은 전체를 '***'로 마스킹"""
        assert EnvValidator._mask_value("AB") == "***"
        assert EnvValidator._mask_value("ABCD") == "***"

    def test_custom_visible_chars(self) -> None:
        """visible_chars 커스텀 설정 시 해당 자릿수만큼 노출"""
        result = EnvValidator._mask_value("ABCDEFGH", visible_chars=2)

        assert result == "AB***"


# ---------------------------------------------------------------------------
# validate_tool_use_env (2개)
# ---------------------------------------------------------------------------


class TestValidateToolUseEnv:
    """Tool Use 환경변수 검증 테스트"""

    def test_all_vars_missing_returns_valid_with_warnings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """모든 Tool Use 변수 누락 시 valid=True(선택사항), warnings 존재"""
        # 환경변수 제거
        monkeypatch.delenv("USER_API_BASE_URL", raising=False)
        monkeypatch.delenv("USER_API_TOKEN", raising=False)

        result = EnvValidator.validate_tool_use_env()

        assert result.is_valid is True
        assert result.missing_vars == []
        assert len(result.warnings) == 2
        # 경고 메시지에 변수명이 포함되는지 확인
        warning_text = " ".join(result.warnings)
        assert "USER_API_BASE_URL" in warning_text
        assert "USER_API_TOKEN" in warning_text

    def test_all_vars_set_returns_valid_no_warnings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """모든 Tool Use 변수 설정 시 valid=True, warnings 없음"""
        monkeypatch.setenv("USER_API_BASE_URL", "https://example.com")
        monkeypatch.setenv("USER_API_TOKEN", "test_token_value")

        result = EnvValidator.validate_tool_use_env()

        assert result.is_valid is True
        assert result.missing_vars == []
        assert result.warnings == []


# ---------------------------------------------------------------------------
# validate_required_env (2개)
# ---------------------------------------------------------------------------


class TestValidateRequiredEnv:
    """필수 환경변수 검증 테스트"""

    def test_all_vars_missing_returns_valid_phase1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """모든 필수 변수 누락 시에도 valid=True (Phase 1 MVP: required=False)"""
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("MONGODB_URI", raising=False)

        result = EnvValidator.validate_required_env()

        assert result.is_valid is True
        assert result.missing_vars == []

    def test_all_vars_set_returns_valid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """모든 필수 변수 설정 시 valid=True"""
        monkeypatch.setenv("GOOGLE_API_KEY", "AIza_test_key_12345")
        monkeypatch.setenv("MONGODB_URI", "mongodb+srv://user:pass@cluster.net/db")

        result = EnvValidator.validate_required_env()

        assert result.is_valid is True
        assert result.missing_vars == []


# ---------------------------------------------------------------------------
# validate_all (1개)
# ---------------------------------------------------------------------------


class TestValidateAll:
    """통합 환경변수 검증 테스트"""

    def test_non_strict_mode_returns_valid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """non-strict 모드: 모든 변수 누락이어도 valid=True (Phase 1 MVP)"""
        # 모든 환경변수 제거
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("MONGODB_URI", raising=False)
        monkeypatch.delenv("USER_API_BASE_URL", raising=False)
        monkeypatch.delenv("USER_API_TOKEN", raising=False)

        result = EnvValidator.validate_all(strict=False)

        assert result.is_valid is True
        assert result.missing_vars == []
        # Tool Use 경고는 포함
        assert len(result.warnings) == 2


# ---------------------------------------------------------------------------
# validate_provider_env (4개)
# ---------------------------------------------------------------------------


def _provider_config(
    embeddings_provider: str = "openrouter",
    generation_provider: str = "google",
    llm_provider: str = "openrouter",
) -> dict:
    return {
        "embeddings": {
            "provider": embeddings_provider,
            "openrouter": {"api_key": ""},
            "google": {"api_key": ""},
            "openai": {"api_key": ""},
            "local": {},
        },
        "generation": {
            "default_provider": generation_provider,
            "google": {"api_key": ""},
            "openrouter": {"api_key": ""},
            "ollama": {},
        },
        "llm": {
            "default_provider": llm_provider,
            "google": {"api_key": ""},
            "openai": {"api_key": ""},
            "anthropic": {"api_key": ""},
            "openrouter": {"api_key": ""},
            "ollama": {},
        },
    }


class TestValidateProviderEnv:
    """선택 provider와 환경 변수 조합 검증 테스트"""

    def test_strict_mode_requires_selected_provider_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key in ["GOOGLE_API_KEY", "OPENROUTER_API_KEY"]:
            monkeypatch.delenv(key, raising=False)

        result = EnvValidator.validate_provider_env(_provider_config(), strict=True)

        assert result.is_valid is False
        assert set(result.missing_vars) == {"GOOGLE_API_KEY", "OPENROUTER_API_KEY"}

    def test_non_strict_mode_warns_for_missing_selected_provider_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key in ["GOOGLE_API_KEY", "OPENROUTER_API_KEY"]:
            monkeypatch.delenv(key, raising=False)

        result = EnvValidator.validate_provider_env(_provider_config(), strict=False)

        assert result.is_valid is True
        assert result.missing_vars == []
        assert len(result.warnings) == 3

    def test_local_and_ollama_providers_need_no_cloud_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key in ["GOOGLE_API_KEY", "OPENROUTER_API_KEY"]:
            monkeypatch.delenv(key, raising=False)

        result = validate_provider_env(
            _provider_config(
                embeddings_provider="local",
                generation_provider="ollama",
                llm_provider="ollama",
            ),
            strict=True,
        )

        assert result.is_valid is True
        assert result.missing_vars == []

    def test_unknown_provider_fails_even_when_non_strict(self) -> None:
        result = EnvValidator.validate_provider_env(
            _provider_config(generation_provider="unknown"),
            strict=False,
        )

        assert result.is_valid is False
        assert result.missing_vars == ["generation.unknown"]

    def test_generation_openai_is_rejected_because_runtime_does_not_support_it(self) -> None:
        result = EnvValidator.validate_provider_env(
            _provider_config(generation_provider="openai"),
            strict=False,
        )

        assert result.is_valid is False
        assert result.missing_vars == ["generation.openai"]


# ---------------------------------------------------------------------------
# get_missing_env_help (2개)
# ---------------------------------------------------------------------------


class TestGetMissingEnvHelp:
    """누락된 환경변수 도움말 생성 테스트"""

    def test_empty_list_returns_empty_string(self) -> None:
        """빈 리스트 입력 시 빈 문자열 반환"""
        result = EnvValidator.get_missing_env_help([])

        assert result == ""

    def test_known_var_includes_description_and_example(self) -> None:
        """알려진 변수명 전달 시 설명과 예시가 포함된 도움말 반환"""
        result = EnvValidator.get_missing_env_help(["GOOGLE_API_KEY"])

        assert "GOOGLE_API_KEY" in result
        assert "Google Gemini API Key" in result
        assert "AIza..." in result
        assert "⚠️" in result
        assert ".env" in result

    def test_unknown_var_shows_default_description(self) -> None:
        """알 수 없는 변수명은 '설명 없음'으로 표시"""
        result = EnvValidator.get_missing_env_help(["UNKNOWN_VAR"])

        assert "UNKNOWN_VAR" in result
        assert "설명 없음" in result


# ---------------------------------------------------------------------------
# 편의 함수 (3개)
# ---------------------------------------------------------------------------


class TestConvenienceFunctions:
    """모듈 레벨 편의 함수가 올바른 타입을 반환하는지 검증"""

    def test_validate_tool_use_env_returns_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """validate_tool_use_env() 편의 함수가 EnvValidationResult를 반환"""
        monkeypatch.delenv("USER_API_BASE_URL", raising=False)
        monkeypatch.delenv("USER_API_TOKEN", raising=False)

        result = validate_tool_use_env()

        assert isinstance(result, EnvValidationResult)
        assert result.is_valid is True

    def test_validate_required_env_returns_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """validate_required_env() 편의 함수가 EnvValidationResult를 반환"""
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("MONGODB_URI", raising=False)

        result = validate_required_env()

        assert isinstance(result, EnvValidationResult)
        assert result.is_valid is True

    def test_validate_all_env_returns_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """validate_all_env() 편의 함수가 EnvValidationResult를 반환"""
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("MONGODB_URI", raising=False)
        monkeypatch.delenv("USER_API_BASE_URL", raising=False)
        monkeypatch.delenv("USER_API_TOKEN", raising=False)

        result = validate_all_env(strict=False)

        assert isinstance(result, EnvValidationResult)
        assert result.is_valid is True
