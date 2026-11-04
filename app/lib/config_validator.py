"""
환경 변수 및 설정 검증 유틸리티

타입 안전성과 검증을 제공하는 환경 변수 로더 및 설정 검증기입니다.

구현일: 2026-01-08
보안: SEC-002 대응
업데이트: 2026-01-08 - Pydantic 기반 설정 검증 강화
"""
import os
from typing import Any, Literal, TypeVar, cast
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError, field_validator

from .logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class ConfigValidationError(ValueError):
    """환경 변수 검증 실패 에러"""
    pass


# ========================================
# 값 강제 변환(coerce) 헬퍼 — 관대(lenient) 모드
# ========================================
# 설정 딕셔너리/환경변수에서 읽은 임의 값을 숫자로 바꾸되, 비어있거나 잘못된 값은
# 경고 후 기본값으로 대체하고 범위를 벗어나면 clamp한다(예외를 던지지 않음).
# 여러 모듈에 산재하던 ``_env_int`` / ``_env_float`` / ``_coerce_*`` 재구현을 대체한다.


def coerce_int(
    value: Any,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    label: str = "value",
) -> int:
    """
    값을 int로 변환하되 범위를 clamp하고, 비어있거나 잘못된 값이면 기본값을 사용한다.

    Args:
        value: 변환할 값 (None/빈 문자열은 미설정으로 간주)
        default: 미설정/변환 실패 시 기본값
        minimum: 하한 (지정 시 이보다 작은 값은 하한으로 clamp)
        maximum: 상한 (지정 시 이보다 큰 값은 상한으로 clamp)
        label: 경고 로그에 표시할 값 이름 (환경 변수명 등)

    Returns:
        변환·clamp된 정수값

    Examples:
        >>> coerce_int("10", 5)
        10
        >>> coerce_int("abc", 5)
        5
        >>> coerce_int(0, 5, minimum=1)
        1
    """
    if value is None or value == "":
        result = default
    else:
        try:
            result = int(value)
        except (TypeError, ValueError):
            logger.warning(
                f"'{label}'의 값 {value!r}은(는) 정수가 아닙니다. 기본값 {default}을(를) 사용합니다."
            )
            result = default
    return _clamp(result, minimum, maximum)


def coerce_float(
    value: Any,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    label: str = "value",
) -> float:
    """
    값을 float로 변환하되 범위를 clamp하고, 비어있거나 잘못된 값이면 기본값을 사용한다.

    Args:
        value: 변환할 값 (None/빈 문자열은 미설정으로 간주)
        default: 미설정/변환 실패 시 기본값
        minimum: 하한 (지정 시 이보다 작은 값은 하한으로 clamp)
        maximum: 상한 (지정 시 이보다 큰 값은 상한으로 clamp)
        label: 경고 로그에 표시할 값 이름 (환경 변수명 등)

    Returns:
        변환·clamp된 실수값

    Examples:
        >>> coerce_float("1.5", 1.0)
        1.5
        >>> coerce_float("abc", 1.0)
        1.0
        >>> coerce_float("9", 1.0, maximum=2.0)
        2.0
    """
    if value is None or value == "":
        result = default
    else:
        try:
            result = float(value)
        except (TypeError, ValueError):
            logger.warning(
                f"'{label}'의 값 {value!r}은(는) 실수가 아닙니다. 기본값 {default}을(를) 사용합니다."
            )
            result = default
    return _clamp(result, minimum, maximum)


_Number = TypeVar("_Number", int, float)


def _clamp(value: _Number, minimum: _Number | None, maximum: _Number | None) -> _Number:
    """값을 [minimum, maximum] 범위로 제한한다(None인 경계는 무시)."""
    if minimum is not None and value < minimum:
        return minimum
    if maximum is not None and value > maximum:
        return maximum
    return value


def get_env_int(
    key: str,
    default: int | None = None,
    min_value: int | None = None,
    max_value: int | None = None,
    *,
    strict: bool = True,
) -> int:
    """
    정수형 환경 변수 로드 및 검증

    Args:
        key: 환경 변수명
        default: 기본값 (None이면 필수)
        min_value: 최소값
        max_value: 최대값
        strict: True(기본)면 정수가 아니거나 범위를 벗어날 때 예외를 던진다.
            False면 관대 모드: 비어있거나 잘못된 값은 경고 후 기본값을 사용하고,
            범위를 벗어난 값은 min/max로 clamp한다 (``coerce_int`` 위임).

    Returns:
        검증된 정수값

    Raises:
        ConfigValidationError: 검증 실패 시 (strict=True), 또는 기본값 없이 미설정 시

    Examples:
        >>> get_env_int("PORT", default=8000)
        8000
        >>> get_env_int("TIMEOUT", min_value=1, max_value=3600)
        30
        >>> get_env_int("RETRIES", default=3, min_value=0, strict=False)
        3
    """
    raw_value = os.getenv(key)

    if raw_value is None or (not strict and raw_value == ""):
        if default is not None:
            return default
        raise ConfigValidationError(
            f"환경 변수 '{key}'가 설정되지 않았습니다. "
            "필수 환경 변수입니다."
        )

    if not strict:
        if default is None:
            raise ConfigValidationError(
                f"환경 변수 '{key}'의 관대 모드(strict=False)에는 기본값이 필요합니다."
            )
        return coerce_int(raw_value, default, minimum=min_value, maximum=max_value, label=key)

    try:
        value = int(raw_value)
    except ValueError:
        raise ConfigValidationError(
            f"환경 변수 '{key}'의 값 '{raw_value}'은(는) 정수가 아닙니다."
        )

    if min_value is not None and value < min_value:
        raise ConfigValidationError(
            f"환경 변수 '{key}'의 값 {value}은(는) 최소값 {min_value}보다 작습니다."
        )

    if max_value is not None and value > max_value:
        raise ConfigValidationError(
            f"환경 변수 '{key}'의 값 {value}은(는) 최대값 {max_value}보다 큽니다."
        )

    return value


def get_env_float(
    key: str,
    default: float | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    *,
    strict: bool = True,
) -> float:
    """
    실수형 환경 변수 로드 및 검증

    Args:
        key: 환경 변수명
        default: 기본값 (None이면 필수)
        min_value: 최소값
        max_value: 최대값
        strict: True(기본)면 실수가 아니거나 범위를 벗어날 때 예외를 던진다.
            False면 관대 모드: 비어있거나 잘못된 값은 경고 후 기본값을 사용하고,
            범위를 벗어난 값은 min/max로 clamp한다 (``coerce_float`` 위임).

    Returns:
        검증된 실수값

    Raises:
        ConfigValidationError: 검증 실패 시 (strict=True), 또는 기본값 없이 미설정 시

    Examples:
        >>> get_env_float("RETRY_BASE_SECONDS", default=1.0)
        1.0
        >>> get_env_float("THRESHOLD", default=0.5, min_value=0.0, max_value=1.0, strict=False)
        0.5
    """
    raw_value = os.getenv(key)

    if raw_value is None or (not strict and raw_value == ""):
        if default is not None:
            return default
        raise ConfigValidationError(
            f"환경 변수 '{key}'가 설정되지 않았습니다. "
            "필수 환경 변수입니다."
        )

    if not strict:
        if default is None:
            raise ConfigValidationError(
                f"환경 변수 '{key}'의 관대 모드(strict=False)에는 기본값이 필요합니다."
            )
        return coerce_float(raw_value, default, minimum=min_value, maximum=max_value, label=key)

    try:
        value = float(raw_value)
    except ValueError:
        raise ConfigValidationError(
            f"환경 변수 '{key}'의 값 '{raw_value}'은(는) 실수가 아닙니다."
        )

    if min_value is not None and value < min_value:
        raise ConfigValidationError(
            f"환경 변수 '{key}'의 값 {value}은(는) 최소값 {min_value}보다 작습니다."
        )

    if max_value is not None and value > max_value:
        raise ConfigValidationError(
            f"환경 변수 '{key}'의 값 {value}은(는) 최대값 {max_value}보다 큽니다."
        )

    return value


def get_env_bool(
    key: str,
    default: bool = False,
) -> bool:
    """
    불리언 환경 변수 로드

    True 값: "true", "True", "1", "yes", "YES"
    False 값: "false", "False", "0", "no", "NO", ""

    Args:
        key: 환경 변수명
        default: 기본값

    Returns:
        불리언 값

    Examples:
        >>> get_env_bool("DEBUG", default=False)
        False
    """
    raw_value = os.getenv(key)

    if raw_value is None or raw_value == "":
        return default

    true_values = {"true", "1", "yes"}
    false_values = {"false", "0", "no", ""}

    normalized = raw_value.lower()

    if normalized in true_values:
        return True
    elif normalized in false_values:
        return False
    else:
        logger.warning(
            f"환경 변수 '{key}'의 값 '{raw_value}'은(는) 불리언이 아닙니다. "
            f"기본값 {default}을(를) 사용합니다."
        )
        return default


def get_env_url(
    key: str,
    default: str | None = None,
    require_https: bool = False,
) -> str:
    """
    URL 환경 변수 로드 및 검증

    Args:
        key: 환경 변수명
        default: 기본값
        require_https: HTTPS 필수 여부

    Returns:
        검증된 URL

    Raises:
        ConfigValidationError: URL 형식이 잘못된 경우

    Examples:
        >>> get_env_url("API_URL", require_https=True)
        'https://api.example.com'
    """
    raw_value = os.getenv(key)

    if raw_value is None:
        if default is not None:
            raw_value = default
        else:
            raise ConfigValidationError(
                f"환경 변수 '{key}'가 설정되지 않았습니다."
            )

    try:
        parsed = urlparse(raw_value)
    except Exception as e:
        raise ConfigValidationError(
            f"환경 변수 '{key}'의 값 '{raw_value}'은(는) 유효한 URL이 아닙니다: {e}"
        )

    if not parsed.scheme:
        raise ConfigValidationError(
            f"환경 변수 '{key}'의 URL '{raw_value}'에 스킴(http/https)이 없습니다."
        )

    if require_https and parsed.scheme != "https":
        raise ConfigValidationError(
            f"환경 변수 '{key}'의 URL은 HTTPS여야 합니다. (현재: {parsed.scheme})"
        )

    return raw_value


# ========================================
# Pydantic 기반 설정 검증 모델
# ========================================


class EnvironmentConfig(BaseModel):
    """환경 설정 검증 모델"""

    environment: Literal["development", "test", "production"] = Field(
        ...,
        description="실행 환경",
    )
    debug: bool = Field(
        default=False,
        description="디버그 모드 활성화 여부",
    )

    @field_validator("debug")
    @classmethod
    def validate_debug_in_production(cls, v: bool, info: Any) -> bool:
        """프로덕션 환경에서 디버그 모드 비활성화 검증"""
        environment = info.data.get("environment")
        if environment == "production" and v is True:
            raise ValueError("프로덕션 환경에서는 debug=True를 사용할 수 없습니다.")
        return v


class ServerConfig(BaseModel):
    """서버 설정 검증 모델"""

    host: str = Field(
        default="0.0.0.0",
        description="서버 호스트",
    )
    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="서버 포트",
    )
    workers: int = Field(
        default=1,
        ge=1,
        le=16,
        description="워커 수",
    )
    reload: bool = Field(
        default=False,
        description="자동 리로드 활성화 여부",
    )

    @field_validator("reload")
    @classmethod
    def validate_reload_in_production(cls, v: bool, info: Any) -> bool:
        """프로덕션 환경에서 리로드 비활성화 검증"""
        # 환경 정보는 info.context를 통해 전달받아야 함
        return v


class LLMProviderSettings(BaseModel):
    """LLM 제공자별 설정 검증 모델"""

    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="LLM 온도 파라미터",
    )
    max_tokens: int = Field(
        default=2048,
        ge=1,
        le=128000,
        description="최대 토큰 수",
    )
    timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="타임아웃 (초)",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="최대 재시도 횟수",
    )


class CacheConfig(BaseModel):
    """캐시 설정 검증 모델"""

    enabled: bool = Field(
        default=True,
        description="캐시 활성화 여부",
    )
    ttl: int = Field(
        default=3600,
        ge=0,
        description="캐시 TTL (초)",
    )


class CircuitBreakerConfig(BaseModel):
    """Circuit Breaker 설정 검증 모델"""

    enabled: bool = Field(
        default=False,
        description="Circuit Breaker 활성화 여부",
    )
    failure_threshold: int = Field(
        default=5,
        ge=1,
        description="실패 임계값",
    )
    recovery_timeout: int = Field(
        default=60,
        ge=1,
        description="복구 타임아웃 (초)",
    )
    half_open_requests: int = Field(
        default=3,
        ge=1,
        description="Half-Open 상태에서 허용할 요청 수",
    )


def validate_config_section(
    section_name: str,
    config_data: dict[str, Any],
    model: type[BaseModel],
    strict: bool = False,
) -> dict[str, Any] | None:
    """
    설정 섹션 검증

    Args:
        section_name: 섹션 이름 (로깅용)
        config_data: 검증할 설정 데이터
        model: Pydantic 모델 클래스
        strict: 엄격 모드 (검증 실패 시 예외 발생)

    Returns:
        검증된 설정 딕셔너리 또는 None (검증 실패 시)

    Raises:
        ConfigValidationError: strict=True일 때 검증 실패 시

    Examples:
        >>> validate_config_section("cache", {"enabled": True, "ttl": 3600}, CacheConfig)
        {'enabled': True, 'ttl': 3600}
    """
    try:
        validated = model.model_validate(config_data)
        logger.debug(f"✅ {section_name} 설정 검증 성공")
        return cast(dict[str, Any], validated.model_dump())
    except ValidationError as e:
        error_msg = f"❌ {section_name} 설정 검증 실패:\n{e}"
        logger.error(error_msg)

        if strict:
            raise ConfigValidationError(error_msg) from e

        logger.warning(f"⚠️ {section_name} 설정 검증 실패했지만 계속 진행합니다.")
        return None


def validate_full_config(
    config: dict[str, Any],
    strict: bool = False,
) -> dict[str, Any]:
    """
    전체 설정 검증

    Args:
        config: 검증할 전체 설정
        strict: 엄격 모드 (검증 실패 시 예외 발생)

    Returns:
        검증된 설정 딕셔너리

    Raises:
        ConfigValidationError: strict=True일 때 검증 실패 시

    Examples:
        >>> validate_full_config(config_dict, strict=True)
        {...}
    """
    validation_results: dict[str, Any] = {}
    failed_sections: list[str] = []

    # 각 섹션별 검증
    validators: dict[str, type[BaseModel]] = {
        "app": EnvironmentConfig,
        "server": ServerConfig,
        "cache": CacheConfig,
        "circuit_breaker": CircuitBreakerConfig,
    }

    for section, model in validators.items():
        if section in config:
            result = validate_config_section(
                section,
                config[section],
                model,
                strict=strict,
            )
            if result is not None:
                validation_results[section] = result
            else:
                failed_sections.append(section)

    if failed_sections and strict:
        raise ConfigValidationError(
            f"다음 설정 섹션 검증 실패: {', '.join(failed_sections)}"
        )

    # 검증되지 않은 섹션은 원본 유지
    for key, value in config.items():
        if key not in validation_results:
            validation_results[key] = value

    logger.info(f"✅ 설정 검증 완료 (검증된 섹션: {len(validation_results)}개)")

    return validation_results
