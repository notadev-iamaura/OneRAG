"""
외부 API 호출 모듈
httpx를 사용한 안전한 HTTP 요청 처리
- 재시도 로직 (exponential backoff)
- 타임아웃 처리
- Circuit Breaker 패턴
- 에러 핸들링
"""

import asyncio
import ipaddress
import time
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from ....lib.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from ....lib.logger import get_logger

# 백오프 전략/지연 계산은 공용 유틸로 일원화 (동작 동일).
# BackoffStrategy는 기존 공개 API 호환성을 위해 이 모듈에서도 그대로 재노출한다.
from ....lib.retry import BackoffStrategy as BackoffStrategy
from ....lib.retry import calculate_backoff_delay as _calculate_backoff_delay_util
from .tool_loader import ToolDefinition

logger = get_logger(__name__)


@dataclass
class APICallResult:
    """API 호출 결과"""

    success: bool
    data: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    status_code: int | None = None
    response_time_ms: float | None = None
    retry_count: int = 0


class ExternalAPICaller:
    """
    외부 API 호출 관리자
    안전한 HTTP 요청 처리 및 에러 핸들링
    """

    def __init__(self):
        """초기화"""
        self.client: httpx.AsyncClient | None = None
        self.circuit_breakers: dict[str, CircuitBreaker] = {}

        logger.info("ExternalAPICaller 초기화")

    async def initialize(self):
        """클라이언트 초기화"""
        if self.client is None:
            # httpx.AsyncClient 생성
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),  # 기본 타임아웃
                follow_redirects=False,
                verify=True,  # SSL 검증
            )
            logger.info("httpx AsyncClient 초기화 완료")

    async def close(self):
        """클라이언트 종료"""
        if self.client:
            await self.client.aclose()
            self.client = None
            logger.info("httpx AsyncClient 종료")

    def get_circuit_breaker(self, tool_name: str, config: dict[str, Any]) -> CircuitBreaker:
        """
        Tool별 Circuit Breaker 조회 또는 생성

        Args:
            tool_name: Tool 이름
            config: Circuit Breaker 설정

        Returns:
            CircuitBreaker 인스턴스
        """
        if tool_name not in self.circuit_breakers:
            # CircuitBreakerConfig 객체 생성 (타입 안전성 보장)
            cb_config = CircuitBreakerConfig(
                failure_threshold=config.get("failure_threshold", 5),
                timeout=config.get("timeout_seconds", 60.0),
                success_threshold=config.get("success_threshold", 2),
            )
            self.circuit_breakers[tool_name] = CircuitBreaker(name=tool_name, config=cb_config)
            logger.debug(f"Circuit Breaker 생성: {tool_name}")

        return self.circuit_breakers[tool_name]

    async def call_api(self, tool_def: ToolDefinition, parameters: dict[str, Any]) -> APICallResult:
        """
        외부 API 호출

        Args:
            tool_def: Tool 정의
            parameters: API 호출 파라미터

        Returns:
            API 호출 결과
        """
        if self.client is None:
            await self.initialize()

        execution = tool_def.execution

        # Circuit Breaker 설정 (활성화 시에만 인스턴스 생성)
        circuit_breaker = None
        if execution.get("circuit_breaker", {}).get("enabled", False):
            circuit_breaker = self.get_circuit_breaker(tool_def.name, execution["circuit_breaker"])

        # 재시도 설정
        retry_config = execution.get("retry", {})
        max_attempts = retry_config.get("max_attempts", 1)

        last_error = None
        retry_count = 0

        for attempt in range(max_attempts):
            try:
                # Circuit Breaker가 활성화된 경우 .call()로 감싸서 자동 상태 관리
                if circuit_breaker:
                    result = await circuit_breaker.call(
                        self._execute_api_call,
                        tool_def,
                        parameters,
                        attempt,
                        fallback=lambda: APICallResult(
                            success=False,
                            error={
                                "code": "CIRCUIT_BREAKER_OPEN",
                                "message": "서비스가 일시적으로 사용 불가능합니다",
                            },
                        ),
                    )
                else:
                    # Circuit Breaker 미사용 시 직접 호출
                    result = await self._execute_api_call(tool_def, parameters, attempt)

                result.retry_count = retry_count
                return cast(APICallResult, result)

            except Exception as e:
                last_error = e
                retry_count += 1

                # 재시도 여부 판단
                if attempt < max_attempts - 1:
                    delay = self._calculate_backoff_delay(attempt, retry_config)
                    logger.warning(
                        f"API 호출 실패, {delay}초 후 재시도 "
                        f"(시도 {attempt + 1}/{max_attempts}): {tool_def.name}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"API 호출 최종 실패 (시도 {max_attempts}회): {tool_def.name}, "
                        f"에러: {str(last_error)}"
                    )

        # 모든 재시도 실패
        return APICallResult(
            success=False,
            error={"code": "API_CALL_FAILED", "message": f"외부 API 호출 실패: {str(last_error)}"},
            retry_count=retry_count,
        )

    def _validate_url_safety(self, url: str) -> tuple[bool, str | None]:
        """
        SSRF 방어를 위한 URL 안전성 검증

        Args:
            url: 검증할 URL

        Returns:
            (검증 성공 여부, 오류 메시지)
        """
        try:
            parsed = urlparse(url)

            # 1. 프로토콜 검증 (http/https만 허용)
            if parsed.scheme not in ("http", "https"):
                return False, f"허용되지 않는 프로토콜: {parsed.scheme}"

            # 2. 호스트 검증
            hostname = parsed.hostname
            if not hostname:
                return False, "유효하지 않은 호스트명"

            # 3. 위험한 호스트 패턴 차단
            blocked_patterns = [
                "localhost",
                "127.0.0.1",
                "169.254.169.254",  # AWS metadata
                "metadata.google.internal",  # GCP metadata
                "0.0.0.0",
                "[::1]",  # IPv6 localhost
                "[::]",
            ]

            hostname_lower = hostname.lower()
            for pattern in blocked_patterns:
                if pattern in hostname_lower:
                    logger.warning(f"SSRF 차단: 위험한 호스트 감지 - {hostname}")
                    return False, f"차단된 호스트: {hostname}"

            # 4. Private IP 대역 검증
            try:
                ip_obj = ipaddress.ip_address(hostname)

                # Private IP 차단 (RFC 1918, Link-local 등)
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                    logger.warning(f"SSRF 차단: Private IP 대역 감지 - {hostname}")
                    return False, f"Private IP 접근 차단: {hostname}"

            except ValueError:
                # 호스트명이 IP가 아닌 경우 (도메인) → 허용
                pass

            return True, None

        except Exception as e:
            logger.error(f"URL 검증 중 오류: {str(e)}")
            return False, f"URL 검증 실패: {str(e)}"

    async def _execute_api_call(
        self, tool_def: ToolDefinition, parameters: dict[str, Any], attempt: int
    ) -> APICallResult:
        """
        실제 API 호출 실행

        Args:
            tool_def: Tool 정의
            parameters: 파라미터
            attempt: 시도 횟수

        Returns:
            API 호출 결과
        """
        execution = tool_def.execution

        # URL 구성
        base_url = execution.get("base_url", "")
        endpoint = execution.get("endpoint", "")
        url = f"{base_url}{endpoint}"

        # CRITICAL: SSRF 방어 - URL 안전성 검증
        is_safe, error_msg = self._validate_url_safety(url)
        if not is_safe:
            logger.error(f"SSRF 차단: {tool_def.name} - {error_msg}")
            return APICallResult(
                success=False,
                error={
                    "code": "SSRF_BLOCKED",
                    "message": f"보안상의 이유로 차단된 URL: {error_msg}",
                },
                response_time_ms=0.0,
            )

        # HTTP 메서드
        method = execution.get("method", "POST").upper()

        # 헤더
        headers = execution.get("headers", {}).copy()

        # 타임아웃
        timeout_ms = execution.get("timeout_ms", 10000)
        timeout = httpx.Timeout(timeout_ms / 1000.0)

        logger.info(
            f"API 호출 시작: {method} {url} " f"(Tool: {tool_def.name}, 시도: {attempt + 1})"
        )

        # Client 초기화 확인
        if not self.client:
            logger.error("httpx AsyncClient가 초기화되지 않음")
            return APICallResult(
                success=False,
                error={"code": "NOT_INITIALIZED", "message": "API Client가 초기화되지 않았습니다"},
            )

        start_time = time.time()

        try:
            # HTTP 요청
            response = await self.client.request(
                method=method, url=url, json=parameters, headers=headers, timeout=timeout
            )

            response_time_ms = (time.time() - start_time) * 1000

            # 응답 처리
            if response.status_code == 200:
                data = response.json()
                logger.info(
                    f"API 호출 성공: {method} {url} " f"(응답 시간: {response_time_ms:.0f}ms)"
                )

                return APICallResult(
                    success=True,
                    data=data,
                    status_code=response.status_code,
                    response_time_ms=response_time_ms,
                )
            else:
                # HTTP 오류 응답
                try:
                    error_data = response.json()
                except Exception:
                    error_data = {"message": response.text}

                logger.error(
                    f"API 호출 실패: {method} {url} " f"(상태 코드: {response.status_code})"
                )

                return APICallResult(
                    success=False,
                    error={
                        "code": f"HTTP_{response.status_code}",
                        "message": error_data.get("message", "Unknown error"),
                    },
                    status_code=response.status_code,
                    response_time_ms=response_time_ms,
                )

        except httpx.TimeoutException:
            response_time_ms = (time.time() - start_time) * 1000
            logger.error(f"API 호출 타임아웃: {method} {url} ({timeout_ms}ms)")

            return APICallResult(
                success=False,
                error={"code": "TIMEOUT", "message": f"API 응답 시간 초과 ({timeout_ms}ms)"},
                response_time_ms=response_time_ms,
            )

        except httpx.HTTPStatusError as e:
            response_time_ms = (time.time() - start_time) * 1000
            logger.error(f"HTTP 상태 오류: {method} {url} - {str(e)}")

            return APICallResult(
                success=False,
                error={"code": "HTTP_STATUS_ERROR", "message": str(e)},
                status_code=e.response.status_code,
                response_time_ms=response_time_ms,
            )

        except httpx.RequestError as e:
            response_time_ms = (time.time() - start_time) * 1000
            logger.error(f"요청 오류: {method} {url} - {str(e)}")

            return APICallResult(
                success=False,
                error={"code": "REQUEST_ERROR", "message": f"요청 실패: {str(e)}"},
                response_time_ms=response_time_ms,
            )

        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            logger.error(f"예상치 못한 오류: {method} {url} - {str(e)}")

            return APICallResult(
                success=False,
                error={"code": "UNKNOWN_ERROR", "message": f"알 수 없는 오류: {str(e)}"},
                response_time_ms=response_time_ms,
            )

    def _calculate_backoff_delay(self, attempt: int, retry_config: dict[str, Any]) -> float:
        """
        재시도 백오프 지연 시간 계산

        공용 유틸 ``app.lib.retry.calculate_backoff_delay``에 위임한다.
        기존 호출부 호환을 위해 메서드 시그니처와 반환값(초)을 그대로 유지한다.

        Args:
            attempt: 시도 횟수 (0부터 시작)
            retry_config: 재시도 설정

        Returns:
            지연 시간 (초)
        """
        return _calculate_backoff_delay_util(attempt, retry_config)


# 싱글톤 인스턴스
_api_caller: ExternalAPICaller | None = None


async def get_api_caller() -> ExternalAPICaller:
    """
    ExternalAPICaller 싱글톤 인스턴스 반환

    Returns:
        ExternalAPICaller 인스턴스
    """
    global _api_caller

    if _api_caller is None:
        _api_caller = ExternalAPICaller()
        await _api_caller.initialize()

    return _api_caller
