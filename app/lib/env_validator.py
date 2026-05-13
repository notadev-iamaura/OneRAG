"""
환경 변수 검증 유틸리티
Tool Use 및 기타 필수 환경 변수 검증
"""

import os
from dataclasses import dataclass
from typing import Any

from .logger import get_logger

logger = get_logger(__name__)


@dataclass
class EnvValidationResult:
    """환경 변수 검증 결과"""

    is_valid: bool
    missing_vars: list[str]
    warnings: list[str]


class EnvValidator:
    """
    환경 변수 검증기
    Tool Use 및 기타 필수 환경 변수를 검증
    """

    # Tool Use 관련 환경 변수 (선택사항)
    TOOL_USE_ENV_VARS = {
        "USER_API_BASE_URL": {
            "required": False,
            "description": "유저 계정 조회 API Base URL",
            "example": "https://your-user-api-domain.com",
        },
        "USER_API_TOKEN": {
            "required": False,
            "description": "유저 계정 조회 API 인증 토큰",
            "example": "your_bearer_token_here",
        },
    }

    # 필수 환경 변수 (기존 시스템)
    # Phase 1 MVP: 선택사항으로 변경 (graceful degradation 지원)
    REQUIRED_ENV_VARS = {
        "GOOGLE_API_KEY": {
            "required": False,  # Phase 1: 선택사항 (향후 필수로 변경)
            "description": "Google Gemini API Key",
            "example": "AIza...",
        },
        "MONGODB_URI": {
            "required": False,  # Phase 1: 선택사항 (향후 필수로 변경)
            "description": "MongoDB Atlas 연결 URI (세션 + Vector Search)",
            "example": "mongodb+srv://user:password@cluster.mongodb.net/database",
        },
    }

    # 선택적 환경 변수
    OPTIONAL_ENV_VARS: dict[str, dict[str, Any]] = {}

    PROVIDER_ENV_REQUIREMENTS: dict[str, dict[str, tuple[str, ...]]] = {
        "embeddings": {
            "google": ("GOOGLE_API_KEY",),
            "openai": ("OPENAI_API_KEY",),
            "openrouter": ("OPENROUTER_API_KEY",),
            "local": (),
        },
        "generation": {
            "google": ("GOOGLE_API_KEY",),
            "openrouter": ("OPENROUTER_API_KEY",),
            "ollama": (),
        },
        "llm": {
            "google": ("GOOGLE_API_KEY",),
            "openai": ("OPENAI_API_KEY",),
            "anthropic": ("ANTHROPIC_API_KEY",),
            "openrouter": ("OPENROUTER_API_KEY",),
            "ollama": (),
        },
    }

    @classmethod
    def validate_tool_use_env(cls) -> EnvValidationResult:
        """
        Tool Use 관련 환경 변수 검증

        Returns:
            EnvValidationResult: 검증 결과
        """
        missing_vars = []
        warnings = []

        for var_name, var_config in cls.TOOL_USE_ENV_VARS.items():
            value = os.getenv(var_name)

            if not value:
                if var_config.get("required"):
                    missing_vars.append(var_name)
                    logger.error(f"필수 환경 변수 누락: {var_name} - {var_config['description']}")
                else:
                    warning_msg = (
                        f"선택적 환경 변수 미설정: {var_name} - "
                        f"{var_config['description']} (Tool 사용 불가)"
                    )
                    warnings.append(warning_msg)
                    logger.warning(warning_msg)
            else:
                logger.debug(f"환경 변수 확인: {var_name} = {cls._mask_value(value)}")

        is_valid = len(missing_vars) == 0

        if is_valid and not warnings:
            logger.info("✅ Tool Use 환경 변수 검증 완료")
        elif is_valid and warnings:
            logger.info(f"⚠️  Tool Use 환경 변수 검증 완료 (경고 {len(warnings)}개)")
        else:
            logger.error(f"❌ Tool Use 환경 변수 검증 실패 (누락 {len(missing_vars)}개)")

        return EnvValidationResult(is_valid=is_valid, missing_vars=missing_vars, warnings=warnings)

    @classmethod
    def validate_required_env(cls) -> EnvValidationResult:
        """
        필수 환경 변수 검증

        Returns:
            EnvValidationResult: 검증 결과
        """
        import os

        required_vars = cls.REQUIRED_ENV_VARS
        missing_vars = []
        warnings: list[str] = []

        for var_name, var_config in required_vars.items():
            value = os.getenv(var_name)

            if not value:
                if var_config.get("required"):
                    missing_vars.append(var_name)
                    logger.error(f"필수 환경 변수 누락: {var_name} - {var_config['description']}")
            else:
                logger.debug(f"환경 변수 확인: {var_name} = {cls._mask_value(value)}")

        is_valid = len(missing_vars) == 0

        if is_valid:
            logger.info("✅ 필수 환경 변수 검증 완료")
        else:
            logger.error(f"❌ 필수 환경 변수 검증 실패 (누락 {len(missing_vars)}개)")

        return EnvValidationResult(is_valid=is_valid, missing_vars=missing_vars, warnings=warnings)

    @classmethod
    def validate_all(cls, strict: bool = False) -> EnvValidationResult:
        """
        모든 환경 변수 검증

        Args:
            strict: True이면 Tool Use 환경변수도 필수로 검증

        Returns:
            EnvValidationResult: 통합 검증 결과
        """
        required_result = cls.validate_required_env()
        tool_use_result = cls.validate_tool_use_env()

        all_missing = required_result.missing_vars + (
            tool_use_result.missing_vars if strict else []
        )
        all_warnings = required_result.warnings + tool_use_result.warnings

        is_valid = len(all_missing) == 0

        return EnvValidationResult(
            is_valid=is_valid, missing_vars=all_missing, warnings=all_warnings
        )

    @classmethod
    def validate_provider_env(
        cls, config: dict[str, Any], strict: bool = False
    ) -> EnvValidationResult:
        """
        선택된 runtime provider와 필요한 환경 변수가 일치하는지 검증합니다.

        strict=False에서는 개발/테스트 quickstart를 막지 않도록 경고만 반환합니다.
        provider 이름 자체가 지원 목록 밖이면 strict 여부와 무관하게 실패합니다.
        """
        missing_vars: list[str] = []
        warnings: list[str] = []

        selected_providers = {
            "embeddings": config.get("embeddings", {}).get("provider", "openrouter"),
            "generation": config.get("generation", {}).get("default_provider", "google"),
            "llm": config.get("llm", {}).get("default_provider", "openrouter"),
        }

        for section, provider in selected_providers.items():
            provider_name = str(provider).strip().lower()
            requirements = cls.PROVIDER_ENV_REQUIREMENTS.get(section, {})

            if provider_name not in requirements:
                missing_vars.append(f"{section}.{provider_name}")
                continue

            for env_var in requirements[provider_name]:
                provider_config = config.get(section, {}).get(provider_name, {})
                configured_value = (
                    provider_config.get("api_key") if isinstance(provider_config, dict) else None
                )
                if configured_value or os.getenv(env_var):
                    continue

                message = (
                    f"{section} provider '{provider_name}' requires {env_var}. "
                    f"Set {env_var} or choose a provider that does not require that key."
                )
                if strict:
                    missing_vars.append(env_var)
                else:
                    warnings.append(message)

        unique_missing = list(dict.fromkeys(missing_vars))
        unique_warnings = list(dict.fromkeys(warnings))

        return EnvValidationResult(
            is_valid=len(unique_missing) == 0,
            missing_vars=unique_missing,
            warnings=unique_warnings,
        )

    @classmethod
    def get_missing_env_help(cls, missing_vars: list[str]) -> str:
        """
        누락된 환경 변수에 대한 도움말 생성

        Args:
            missing_vars: 누락된 환경 변수 리스트

        Returns:
            str: 도움말 메시지
        """
        if not missing_vars:
            return ""

        help_messages = ["\n⚠️  누락된 환경 변수를 설정해주세요:\n"]

        all_vars = {**cls.REQUIRED_ENV_VARS, **cls.OPTIONAL_ENV_VARS, **cls.TOOL_USE_ENV_VARS}

        for var_name in missing_vars:
            var_config = all_vars.get(var_name, {})
            description = var_config.get("description", "설명 없음")
            example = var_config.get("example", "")

            help_messages.append(f"  • {var_name}")
            help_messages.append(f"    설명: {description}")
            if example:
                help_messages.append(f"    예시: {example}")
            help_messages.append("")

        help_messages.append("📝 .env 파일에 위 환경 변수를 설정한 후 재시작하세요.\n")

        return "\n".join(help_messages)

    @staticmethod
    def _mask_value(value: str, visible_chars: int = 4) -> str:
        """
        환경 변수 값 마스킹 (로깅용)

        Args:
            value: 원본 값
            visible_chars: 표시할 문자 수

        Returns:
            str: 마스킹된 값
        """
        if len(value) <= visible_chars:
            return "***"
        return value[:visible_chars] + "***"


def validate_tool_use_env() -> EnvValidationResult:
    """
    Tool Use 환경 변수 검증 (편의 함수)

    Returns:
        EnvValidationResult: 검증 결과
    """
    return EnvValidator.validate_tool_use_env()


def validate_required_env() -> EnvValidationResult:
    """
    필수 환경 변수 검증 (편의 함수)

    Returns:
        EnvValidationResult: 검증 결과
    """
    return EnvValidator.validate_required_env()


def validate_all_env(strict: bool = False) -> EnvValidationResult:
    """
    모든 환경 변수 검증 (편의 함수)

    Args:
        strict: True이면 Tool Use 환경변수도 필수로 검증

    Returns:
        EnvValidationResult: 통합 검증 결과
    """
    return EnvValidator.validate_all(strict=strict)


def validate_provider_env(config: dict[str, Any], strict: bool = False) -> EnvValidationResult:
    """
    선택된 provider와 환경 변수 조합 검증 (편의 함수)

    Args:
        config: 로드된 애플리케이션 설정
        strict: True이면 누락된 provider 환경 변수를 실패로 처리

    Returns:
        EnvValidationResult: 검증 결과
    """
    return EnvValidator.validate_provider_env(config=config, strict=strict)
