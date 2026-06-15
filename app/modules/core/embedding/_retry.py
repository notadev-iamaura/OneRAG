"""
임베딩 API 호출 재시도 유틸리티
========================================
기능: 임베딩 프로바이더(Gemini/OpenAI 등) API의 일시적 오류(429/5xx)에 대해
지수 백오프 + Retry-After 헤더 우선 재시도를 제공한다.

설계 의도:
- 임베더의 ``_batch_embed``/``embed_query``는 동기(sync) 경로이며
  ``asyncio.to_thread``로 실행되므로, 동기 재시도 래퍼(time.sleep 기반)가 필요하다.
- 백오프 지연 계산은 공용 ``app/lib/retry.py``의 ``build_backoff_wait`` /
  ``BackoffStrategy``를 재사용해 프로젝트 전반의 백오프 정책과 일관성을 유지한다
  (새 임시 백오프 구현 금지). 단, Retry-After 헤더 우선·프로바이더 예외→상태코드
  매핑·동기 실행은 공용 비동기 정책으로 표현할 수 없어 이 모듈에서 처리한다.
- 프로바이더 SDK 예외 타입은 try/except import로 옵셔널 매핑한다. 미설치 SDK는
  매핑하지 않으므로 의존성 부담이 없다.

의존성:
- ``app.lib.retry.build_backoff_wait`` / ``BackoffStrategy`` (지수 백오프 base 계산)
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import TypeVar

from ....lib.logger import get_logger
from ....lib.retry import BackoffStrategy, build_backoff_wait

logger = get_logger(__name__)

T = TypeVar("T")

# 재시도 대상 HTTP 상태 코드(레이트리밋 + 일시적 서버 오류)
RETRYABLE_EMBEDDING_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# 환경변수 기반 재시도 설정 키(YAML 키가 아닌 런타임 튜닝 노브)
_ENV_MAX_RETRIES = "ONERAG_EMBEDDING_MAX_RETRIES"
_ENV_RETRY_BASE_SECONDS = "ONERAG_EMBEDDING_RETRY_BASE_SECONDS"
_ENV_RETRY_MAX_SECONDS = "ONERAG_EMBEDDING_RETRY_MAX_SECONDS"

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BASE_SECONDS = 1.0
_DEFAULT_RETRY_MAX_SECONDS = 30.0


class EmbeddingRetryableError(Exception):
    """테스트/내부용 재시도 가능 오류.

    실제 프로바이더 예외 대신 명시적 상태 코드를 담아 재시도 경로를 검증할 때
    사용한다. ``status_code`` 속성으로 상태 코드를 노출한다.
    """

    def __init__(self, status_code: int, message: str | None = None) -> None:
        self.status_code = status_code
        super().__init__(message or f"retryable embedding error: HTTP {status_code}")


def _env_int(name: str, default: int) -> int:
    """환경변수를 정수로 읽되, 미설정/오류 시 기본값을 사용한다."""
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid integer for %s=%r; using %s", name, value, default)
        return default


def _env_float(name: str, default: float) -> float:
    """환경변수를 실수로 읽되, 미설정/오류 시 기본값을 사용한다."""
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("Invalid float for %s=%r; using %s", name, value, default)
        return default


def resolve_retry_settings() -> tuple[int, float, float]:
    """환경변수 기반 재시도 설정(max_retries, base_seconds, max_seconds)을 해석한다."""
    return (
        _env_int(_ENV_MAX_RETRIES, _DEFAULT_MAX_RETRIES),
        _env_float(_ENV_RETRY_BASE_SECONDS, _DEFAULT_RETRY_BASE_SECONDS),
        _env_float(_ENV_RETRY_MAX_SECONDS, _DEFAULT_RETRY_MAX_SECONDS),
    )


class _AttemptState:
    """tenacity wait 객체에 전달할 최소 상태(attempt_number만 사용)."""

    def __init__(self, attempt_number: int) -> None:
        self.attempt_number = attempt_number


def _status_from_exception(exc: BaseException) -> int | None:
    """프로바이더 예외를 재시도용 HTTP 상태 코드로 매핑한다(미매핑 시 None).

    옵셔널 매핑:
    - 내부 EmbeddingRetryableError: status_code 직접 사용
    - google.api_core.exceptions: ResourceExhausted→429, ServiceUnavailable→503,
      그 외 GoogleAPICallError는 .code(HTTP 상태) 사용
    - openai: RateLimitError→429, APIStatusError→.status_code
    - grpc_status_code 속성(8=RESOURCE_EXHAUSTED, 14=UNAVAILABLE) 폴백 매핑
    """
    # 1) 내부 명시적 재시도 예외
    if isinstance(exc, EmbeddingRetryableError):
        return exc.status_code

    # 2) Google API Core 예외 (google-generativeai 경유 간접 설치)
    try:
        from google.api_core import exceptions as gexc  # type: ignore[import-not-found]

        if isinstance(exc, gexc.ResourceExhausted):
            return 429
        if isinstance(exc, gexc.ServiceUnavailable):
            return 503
        if isinstance(exc, gexc.GoogleAPICallError):
            code = getattr(exc, "code", None)
            if isinstance(code, int):
                return code
    except ImportError:
        pass

    # 3) OpenAI SDK 예외
    try:
        import openai  # type: ignore[import-not-found]

        if isinstance(exc, openai.RateLimitError):
            return 429
        if isinstance(exc, openai.APIStatusError):
            status = getattr(exc, "status_code", None)
            if isinstance(status, int):
                return status
    except ImportError:
        pass

    # 4) gRPC 상태 코드 폴백(SDK 미설치 환경 또는 흉내 예외 대응)
    grpc_status = getattr(exc, "grpc_status_code", None)
    if isinstance(grpc_status, int):
        if grpc_status == 8:  # RESOURCE_EXHAUSTED
            return 429
        if grpc_status == 14:  # UNAVAILABLE
            return 503

    # 5) 일반 status_code 속성 폴백
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    return None


def _retry_after_seconds(exc: BaseException) -> str | None:
    """예외에서 Retry-After 헤더 값을 추출한다(없으면 None).

    httpx/requests 스타일 ``response.headers`` 및 OpenAI ``exc.response.headers``를
    모두 지원한다.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get("Retry-After") or headers.get("retry-after")
    except AttributeError:
        return None
    return str(value) if value is not None else None


def _retry_delay(
    attempt: int,
    retry_after: str | None,
    base_seconds: float,
    max_seconds: float,
) -> float:
    """재시도 지연 시간(초)을 계산한다.

    - Retry-After 헤더가 있으면 그 값을 우선 사용하고 max_seconds로 clamp한다.
    - 없으면 공용 ``build_backoff_wait``(EXPONENTIAL)로 base*2^(attempt-1) 지연을
      계산하고 max_seconds로 clamp한다(공용 백오프 정책 재사용).

    Args:
        attempt: 1부터 시작하는 시도 횟수.
        retry_after: Retry-After 헤더 값(초 단위 문자열) 또는 None.
        base_seconds: 지수 백오프 초기 지연(초).
        max_seconds: 지연 상한(초).
    """
    if retry_after:
        try:
            return min(float(retry_after), max_seconds)
        except ValueError:
            pass
    # 공용 백오프 빌더 재사용: wait_exponential_jitter(jitter=0)는
    # base * 2^(attempt_number - 1)을 max로 clamp한 값을 반환한다.
    wait = build_backoff_wait(
        BackoffStrategy.EXPONENTIAL,
        initial_delay_s=base_seconds,
        max_delay_s=max_seconds,
        jitter_s=0.0,
    )
    return float(wait(_AttemptState(attempt)))  # type: ignore[arg-type]


def retry_embed(
    call: Callable[[], T],
    *,
    max_retries: int,
    base_seconds: float,
    max_seconds: float,
) -> T:
    """동기 임베딩 호출에 재시도(지수 백오프 + Retry-After)를 적용한다.

    재시도 가능 상태(429/5xx)이고 시도가 남아 있으면 지연 후 재시도하고,
    비재시도 예외이거나 재시도 소진 시 마지막 예외를 그대로 전파한다
    (오류를 zero-vector 등으로 숨기지 않음 — CLAUDE.md 원칙 준수).

    Args:
        call: 인자 없는 임베딩 호출 콜러블.
        max_retries: 최초 호출 외 추가 재시도 횟수(총 시도 = max_retries + 1).
        base_seconds: 지수 백오프 초기 지연(초).
        max_seconds: 지연 상한(초).

    Returns:
        ``call()``의 반환값.

    Raises:
        Exception: 비재시도 예외 또는 재시도 소진 시 마지막 예외.
    """
    attempt = 0
    while True:
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - 상태코드로 재시도 여부 판단
            status = _status_from_exception(exc)
            retryable = status in RETRYABLE_EMBEDDING_STATUS_CODES
            if not retryable or attempt >= max_retries:
                # 비재시도이거나 소진 → 그대로 전파(오류 은닉 금지)
                raise
            attempt += 1
            delay = _retry_delay(
                attempt,
                _retry_after_seconds(exc),
                base_seconds,
                max_seconds,
            )
            logger.warning(
                "Embedding API retryable error (HTTP %s); retrying in %.1fs (%s/%s)",
                status,
                delay,
                attempt,
                max_retries,
            )
            time.sleep(delay)
