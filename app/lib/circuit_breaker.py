"""
Circuit Breaker Pattern Implementation
외부 서비스 장애 시 빠른 실패 및 자동 복구 지원
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import TYPE_CHECKING, Any

from .logger import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    pass


class CircuitState(Enum):
    """Circuit Breaker 상태"""

    CLOSED = "closed"  # 정상 동작
    OPEN = "open"  # 차단 (빠른 실패)
    HALF_OPEN = "half_open"  # 시험 동작 (복구 시도)


@dataclass
class CircuitBreakerConfig:
    """Circuit Breaker 설정"""

    failure_threshold: int = 5  # 연속 실패 임계값
    success_threshold: int = 2  # Half-Open → Closed 전환 성공 횟수
    timeout: float = 60.0  # Open → Half-Open 대기 시간 (초)
    half_open_timeout: float = 30.0  # Half-Open 상태 최대 시간

    # 에러율 기반 차단
    enable_error_rate_check: bool = True
    error_rate_threshold: float = 0.5  # 에러율 임계값 (50%)
    error_rate_window: int = 10  # 최근 N개 요청 기준
    minimum_error_rate_requests: int = 0  # 에러율 판단 전 필요한 최소 표본 수

    def __post_init__(self) -> None:
        # 0 이하면 윈도우 크기를 최소 표본으로 사용 — 소표본(첫 실패 1건)으로
        # 에러율 100% 판정되어 즉시 Open 되는 오작동을 방지한다
        if self.minimum_error_rate_requests <= 0:
            self.minimum_error_rate_requests = self.error_rate_window


@dataclass
class CircuitBreakerStats:
    """Circuit Breaker 통계"""

    total_requests: int = 0
    total_failures: int = 0
    total_successes: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None
    state_change_time: float = field(default_factory=time.time)

    # 최근 요청 결과 (에러율 계산용)
    recent_results: list = field(default_factory=list)  # True=성공, False=실패

    def record_success(self) -> None:
        """성공 기록"""
        self.total_requests += 1
        self.total_successes += 1
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_success_time = time.time()

        # 최근 결과에 추가
        self.recent_results.append(True)
        if len(self.recent_results) > 20:
            self.recent_results.pop(0)

    def record_failure(self) -> None:
        """실패 기록"""
        self.total_requests += 1
        self.total_failures += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_failure_time = time.time()

        # 최근 결과에 추가
        self.recent_results.append(False)
        if len(self.recent_results) > 20:
            self.recent_results.pop(0)

    def get_error_rate(self, window: int = 10) -> float:
        """최근 N개 요청의 에러율 계산"""
        if not self.recent_results:
            return 0.0

        recent = self.recent_results[-window:]
        if not recent:
            return 0.0

        failures = sum(1 for r in recent if not r)
        return failures / len(recent)


class CircuitBreaker:
    """Circuit Breaker 구현체"""

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None):
        """
        Args:
            name: Circuit Breaker 식별자
            config: 설정 (None이면 기본값 사용)
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()
        # HALF_OPEN 상태에서 동시에 진행 중인 시험 요청 수
        # (success_threshold 개수만 허용해 복구 안 된 백엔드로의 쇄도를 막는다)
        self._half_open_in_flight = 0
        # HALF_OPEN 세대 토큰: OPEN → HALF_OPEN 전환마다 +1.
        # 모든 호출이 진입 시점의 세대를 캡처하고 완료 시점의 세대와 비교해
        # stale 여부를 식별한다. 이전 사이클의 시험 요청(stale trial)뿐 아니라
        # CLOSED 시기에 시작된 장기 호출의 늦은 결과도 새 HALF_OPEN 사이클의
        # 슬롯 카운터/연속 성공·실패/상태 전환을 오염시키지 못하게 막는다.
        self._half_open_generation: int = 0

    async def call(
        self,
        func: Callable[..., Any],
        *args: Any,
        fallback: Callable[..., Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Circuit Breaker를 통한 함수 호출

        Args:
            func: 실행할 함수 (sync 또는 async)
            fallback: 실패 시 대체 함수
            *args, **kwargs: func에 전달할 인자

        Returns:
            func의 반환값

        Raises:
            CircuitBreakerOpenError: Circuit이 Open 상태
            Exception: func 실행 중 발생한 에러
        """
        # lock 안에서는 상태 전이와 진입 결정만 빠르게 수행한다.
        # 느린 작업(func/fallback 실행)은 lock을 잡은 채 돌리지 않는다 —
        # 그래야 OPEN 상태의 느린 fallback이 breaker 전체를 직렬화하지 않는다.
        fast_fail = False
        half_open_trial = False

        async with self._lock:
            # HALF_OPEN이 half_open_timeout을 넘기면 복구 실패로 보고 OPEN 복귀
            if self.state == CircuitState.HALF_OPEN:
                elapsed = time.time() - self.stats.state_change_time
                if elapsed >= self.config.half_open_timeout:
                    logger.warning(f"⚠️  [{self.name}] Half-Open 타임아웃 → Open 복귀")
                    self.state = CircuitState.OPEN
                    self.stats.state_change_time = time.time()

            # OPEN 상태: timeout 경과 시 HALF_OPEN 전환, 아니면 빠른 실패
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    logger.info(f"🔄 [{self.name}] Half-Open 전환 시도")
                    self.state = CircuitState.HALF_OPEN
                    self.stats.state_change_time = time.time()
                    self._half_open_in_flight = 0
                    # 새 시험 사이클 시작: 세대를 올려 이전 사이클의 stale trial이
                    # 이번 사이클의 회계(슬롯/성공 카운트)에 개입하지 못하게 한다
                    self._half_open_generation += 1
                    # 이전 사이클의 성공 기록이 이번 사이클의 CLOSED 전환 판단에
                    # 합산되지 않도록 연속 성공 카운터를 리셋한다
                    # (half_open_timeout 경유 OPEN 복귀는 실패를 기록하지 않아
                    #  consecutive_successes가 잔존할 수 있다)
                    self.stats.consecutive_successes = 0
                else:
                    fast_fail = True

            # HALF_OPEN 상태: 시험 요청을 success_threshold 개수로 제한한다.
            # (게이트가 없으면 동시 요청이 전부 통과해 복구 안 된 백엔드로 쇄도)
            if not fast_fail and self.state == CircuitState.HALF_OPEN:
                if self._half_open_in_flight >= self.config.success_threshold:
                    fast_fail = True
                else:
                    self._half_open_in_flight += 1
                    half_open_trial = True

            # 모든 호출이 진입 시점의 세대를 캡처한다 (위의 상태 전이 반영 후).
            # - trial: 완료 시 세대가 다르면 이전 HALF_OPEN 사이클의 stale trial
            # - 일반 호출(CLOSED 시기 시작 등): 실행 중 OPEN → HALF_OPEN 전환이
            #   일어나면 세대가 달라지므로, 늦게 도착한 결과가 새 사이클의
            #   연속 성공/실패 회계와 상태 전환을 오염시키지 못하게 식별한다
            call_generation = self._half_open_generation

        # --- 여기부터는 lock 밖 (느린 작업) ---
        if fast_fail:
            logger.warning(f"🚫 [{self.name}] Circuit Open, 빠른 실패")
            if fallback:
                return await self._execute_fallback(fallback, *args, **kwargs)
            raise CircuitBreakerOpenError(f"Circuit {self.name} is OPEN")

        # 함수 실행
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = await asyncio.to_thread(func, *args, **kwargs)

            await self._on_success(
                half_open_trial=half_open_trial, call_generation=call_generation
            )
            return result

        except Exception as e:
            logger.error(f"❌ [{self.name}] 실행 실패: {e}")
            await self._on_failure(
                half_open_trial=half_open_trial, call_generation=call_generation
            )

            if fallback:
                return await self._execute_fallback(fallback, *args, **kwargs)
            raise
        finally:
            # 시험 요청 카운터 해제 (HALF_OPEN 게이트가 다음 요청을 받을 수 있도록).
            #
            # lock 없이 '동기'로 수행하는 근거: asyncio는 단일 스레드 이벤트 루프에서
            # 동작하고 아래 블록에는 await가 없어 다른 코루틴이 끼어들 수 없으므로
            # 정수 비교/증감은 원자적이다. 이전 구현처럼 lock acquire를 await하면
            # 그 대기 중 CancelledError가 전달될 때 감소가 건너뛰어져 시험 슬롯이
            # 영구 누수된다 (취소 슬롯 누수 방지).
            #
            # 세대가 일치할 때만 감소: stale trial(이전 HALF_OPEN 사이클)이 새 사이클
            # 카운터를 잘못 감소시키면 threshold 초과 동시 진입이 발생한다.
            if half_open_trial and call_generation == self._half_open_generation:
                self._half_open_in_flight = max(0, self._half_open_in_flight - 1)

    async def _execute_fallback(
        self, fallback: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        """Fallback 함수 실행"""
        try:
            if asyncio.iscoroutinefunction(fallback):
                return await fallback(*args, **kwargs)
            else:
                return await asyncio.to_thread(fallback, *args, **kwargs)
        except Exception as e:
            logger.error(f"❌ [{self.name}] Fallback 실패: {e}")
            raise

    async def _on_success(
        self, *, half_open_trial: bool = False, call_generation: int = 0
    ) -> None:
        """성공 처리

        Args:
            half_open_trial: HALF_OPEN 시험 요청 여부
            call_generation: 호출이 진입한 시점의 HALF_OPEN 세대 (stale 판별용)
        """
        async with self._lock:
            # stale 호출(진입 세대 ≠ 현재 세대)의 성공은 HALF_OPEN 사이클의
            # 통계/상태 전환에 반영하지 않는다 — 두 경우 모두 차단한다:
            # 1) stale trial: 이전 HALF_OPEN 사이클의 시험 요청이 늦게 완료
            # 2) CLOSED 등에서 시작된 장기 호출: 장애 → OPEN → HALF_OPEN 전환 후
            #    완료된 과거 성공이 consecutive_successes에 합산되면 실제 probe
            #    1건만으로 threshold를 채워 미복구 백엔드로 조기 CLOSED 된다
            if call_generation != self._half_open_generation and (
                half_open_trial or self.state == CircuitState.HALF_OPEN
            ):
                logger.debug(
                    f"🕰️  [{self.name}] stale 호출 성공 무시 "
                    f"(세대 {call_generation} != 현재 {self._half_open_generation}, "
                    f"trial={half_open_trial})"
                )
                return

            self.stats.record_success()

            if self.state == CircuitState.HALF_OPEN:
                # Half-Open → Closed 전환 확인
                if self.stats.consecutive_successes >= self.config.success_threshold:
                    logger.info(
                        f"✅ [{self.name}] Half-Open → Closed "
                        f"(연속 성공: {self.stats.consecutive_successes})"
                    )
                    self.state = CircuitState.CLOSED
                    self.stats.state_change_time = time.time()

    async def _on_failure(
        self, *, half_open_trial: bool = False, call_generation: int = 0
    ) -> None:
        """실패 처리

        Args:
            half_open_trial: HALF_OPEN 시험 요청 여부
            call_generation: 호출이 진입한 시점의 HALF_OPEN 세대 (stale 판별용)
        """
        async with self._lock:
            # stale 호출의 실패도 성공과 대칭으로 현재 사이클의 통계/상태 전환에
            # 반영하지 않는다 — 이전 사이클의 늦은 실패(stale trial)나 CLOSED
            # 시기에 시작된 호출의 늦은 실패가 현재 probe와 무관하게
            # HALF_OPEN → OPEN 복귀를 유발하는 것을 방지한다.
            if call_generation != self._half_open_generation and (
                half_open_trial or self.state == CircuitState.HALF_OPEN
            ):
                logger.debug(
                    f"🕰️  [{self.name}] stale 호출 실패 무시 "
                    f"(세대 {call_generation} != 현재 {self._half_open_generation}, "
                    f"trial={half_open_trial})"
                )
                return

            self.stats.record_failure()

            # Half-Open 상태에서 실패 시 즉시 Open
            if self.state == CircuitState.HALF_OPEN:
                logger.warning(f"⚠️  [{self.name}] Half-Open → Open (복구 실패)")
                self.state = CircuitState.OPEN
                self.stats.state_change_time = time.time()
                return

            # Closed 상태에서 Open 전환 확인
            if self.state == CircuitState.CLOSED:
                should_open = False

                # 연속 실패 임계값 확인
                if self.stats.consecutive_failures >= self.config.failure_threshold:
                    logger.warning(
                        f"⚠️  [{self.name}] 연속 실패 임계값 초과: "
                        f"{self.stats.consecutive_failures}/{self.config.failure_threshold}"
                    )
                    should_open = True

                # 에러율 임계값 확인 (최소 표본 수 충족 시에만 판정)
                if self.config.enable_error_rate_check:
                    sample_size = len(self.stats.recent_results[-self.config.error_rate_window :])
                    if sample_size >= self.config.minimum_error_rate_requests:
                        error_rate = self.stats.get_error_rate(self.config.error_rate_window)
                        if error_rate >= self.config.error_rate_threshold:
                            logger.warning(
                                f"⚠️  [{self.name}] 에러율 임계값 초과: "
                                f"{error_rate:.1%} >= {self.config.error_rate_threshold:.1%}"
                            )
                            should_open = True

                if should_open:
                    logger.error(f"🔴 [{self.name}] Closed → Open")
                    self.state = CircuitState.OPEN
                    self.stats.state_change_time = time.time()

    def _should_attempt_reset(self) -> bool:
        """Open → Half-Open 전환 시점 확인"""
        if self.state != CircuitState.OPEN:
            return False

        elapsed = time.time() - self.stats.state_change_time
        return elapsed >= self.config.timeout

    def get_state(self) -> dict[str, Any]:
        """현재 상태 반환"""
        return {
            "name": self.name,
            "state": self.state.value,
            "total_requests": self.stats.total_requests,
            "total_failures": self.stats.total_failures,
            "total_successes": self.stats.total_successes,
            "consecutive_failures": self.stats.consecutive_failures,
            "consecutive_successes": self.stats.consecutive_successes,
            "error_rate": self.stats.get_error_rate(self.config.error_rate_window),
            "success_rate": (
                self.stats.total_successes / self.stats.total_requests
                if self.stats.total_requests > 0
                else 0.0
            ),
            "last_failure_time": self.stats.last_failure_time,
            "last_success_time": self.stats.last_success_time,
        }

    async def reset(self) -> None:
        """Circuit Breaker 리셋 (수동 복구)"""
        async with self._lock:
            logger.info(f"🔄 [{self.name}] 수동 리셋")
            self.state = CircuitState.CLOSED
            self.stats = CircuitBreakerStats()


class CircuitBreakerOpenError(Exception):
    """Circuit이 Open 상태일 때 발생하는 에러"""

    pass


# ========================================
# Decorator
# ========================================


def circuit_breaker(
    name: str,
    config: CircuitBreakerConfig | None = None,
    fallback: Callable[..., Any] | None = None,
) -> Callable[..., Any]:
    """
    Circuit Breaker 데코레이터

    Example:
        @circuit_breaker(name="gemini_api", fallback=lambda: "fallback response")
        async def call_gemini(prompt: str):
            return await gemini.generate(prompt)
    """
    breaker = CircuitBreaker(name, config)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await breaker.call(func, *args, fallback=fallback, **kwargs)

        # Circuit Breaker 인스턴스를 함수에 첨부
        wrapper.circuit_breaker = breaker  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ========================================
# Circuit Breaker Factory
# ========================================


class CircuitBreakerFactory:
    """
    Circuit Breaker Factory

    DI Container를 통해 주입되는 Circuit Breaker 팩토리.
    전역 레지스트리를 대체하여 테스트 용이성과 의존성 관리를 개선합니다.

    Config 기반으로 Circuit Breaker 활성화/비활성화 제어.
    비활성화 시 NoopCircuitBreaker를 반환하여 코드 수정 없이 동작 변경.
    """

    def __init__(self, config: dict | None = None):
        """
        Args:
            config: Circuit Breaker 설정 딕셔너리
        """
        self.config = config or {}
        self._breakers: dict[str, CircuitBreaker] = {}

        # ✨ 신규: 전역 활성화 여부 (Config 기반)
        # circuit_breaker.enabled 키로 제어 (기본값: True)
        circuit_breaker_config = self.config.get("circuit_breaker", {})
        self.enabled = circuit_breaker_config.get("enabled", True)

        if not self.enabled:
            logger.info("🔓 Circuit Breaker 전역 비활성화 (Noop 모드)")
        else:
            logger.info("🔒 Circuit Breaker 전역 활성화")

    def get(
        self, name: str, custom_config: CircuitBreakerConfig | None = None
    ) -> CircuitBreaker | NoopCircuitBreaker:
        """
        Circuit Breaker 인스턴스 가져오기 (싱글톤)

        Config에서 enabled=false인 경우 NoopCircuitBreaker 반환.

        Args:
            name: Circuit Breaker 식별자
            custom_config: 커스텀 설정 (None이면 기본 설정 사용)

        Returns:
            CircuitBreaker 또는 NoopCircuitBreaker

        Example:
            factory = CircuitBreakerFactory(config)
            cb = factory.get('document_retrieval')
            result = await cb.call(fetch_documents)
        """
        # Circuit Breaker 비활성화 시 Noop 반환
        if not self.enabled:
            return NoopCircuitBreaker(name)

        # 기존 로직 (Circuit Breaker 활성화)
        if name not in self._breakers:
            # 설정 우선순위: custom_config > factory config > default
            cb_config: CircuitBreakerConfig | None
            if custom_config is None and self.config:
                cb_config = self._create_config_from_dict(name)
            else:
                cb_config = custom_config

            self._breakers[name] = CircuitBreaker(name, cb_config)

        return self._breakers[name]

    def _create_config_from_dict(self, name: str) -> CircuitBreakerConfig:
        """딕셔너리 설정을 CircuitBreakerConfig로 변환"""
        cb_settings = self.config.get("circuit_breaker", {}).get(name, {})

        return CircuitBreakerConfig(
            failure_threshold=cb_settings.get("failure_threshold", 5),
            success_threshold=cb_settings.get("success_threshold", 2),
            timeout=cb_settings.get("timeout", 60.0),
            half_open_timeout=cb_settings.get("half_open_timeout", 30.0),
            enable_error_rate_check=cb_settings.get("enable_error_rate_check", True),
            error_rate_threshold=cb_settings.get("error_rate_threshold", 0.5),
            error_rate_window=cb_settings.get("error_rate_window", 10),
            minimum_error_rate_requests=cb_settings.get("minimum_error_rate_requests", 0),
        )

    def get_all_states(self) -> dict[str, dict[str, Any]]:
        """모든 Circuit Breaker 상태 반환"""
        return {name: breaker.get_state() for name, breaker in self._breakers.items()}

    async def reset_all(self) -> None:
        """모든 Circuit Breaker 리셋"""
        for breaker in self._breakers.values():
            await breaker.reset()


# ========================================
# NoopCircuitBreaker (MVP용)
# ========================================


class NoopCircuitBreaker:
    """
    Circuit Breaker 비활성화 시 사용하는 Noop(No Operation) 구현

    Circuit Breaker 로직 없이 직접 함수를 호출합니다.
    Fallback 처리는 유지되어 안전성을 보장합니다.

    사용 시나리오:
    - 1단계 MVP: 단일 LLM 프로바이더 환경
    - 개발/테스트 환경: Circuit Breaker 없이 빠른 피드백
    """

    def __init__(self, name: str):
        """
        Args:
            name: Circuit Breaker 식별자 (로깅용)
        """
        self.name = name
        logger.debug(f"🔓 NoopCircuitBreaker 생성: {name} (Circuit Breaker 비활성화)")

    async def call(
        self,
        func: Callable[..., Any],
        *args: Any,
        fallback: Callable[..., Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Circuit Breaker 없이 직접 함수 호출

        Args:
            func: 실행할 함수
            fallback: 실패 시 대체 함수
            *args, **kwargs: func에 전달할 인자

        Returns:
            func의 반환값 (또는 fallback 반환값)
        """
        try:
            # 함수 직접 호출 (Circuit Breaker 로직 없음)
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return await asyncio.to_thread(func, *args, **kwargs)

        except Exception as e:
            logger.error(f"❌ [{self.name}] 실행 실패: {e}")

            # Fallback 처리 (있으면 실행)
            if fallback:
                try:
                    if asyncio.iscoroutinefunction(fallback):
                        return await fallback(*args, **kwargs)
                    else:
                        return await asyncio.to_thread(fallback, *args, **kwargs)
                except Exception as fallback_error:
                    logger.error(f"❌ [{self.name}] Fallback 실패: {fallback_error}")
                    raise

            # Fallback 없으면 원본 예외 전파
            raise

    def get_state(self) -> dict[str, Any]:
        """
        Noop 상태 반환 (호환성을 위한 더미 구현)

        Returns:
            상태 딕셔너리 (모두 0 또는 "noop")
        """
        return {
            "name": self.name,
            "state": "noop",
            "total_requests": 0,
            "total_failures": 0,
            "total_successes": 0,
            "consecutive_failures": 0,
            "consecutive_successes": 0,
            "error_rate": 0.0,
            "success_rate": 1.0,  # 항상 성공으로 간주
            "last_failure_time": None,
            "last_success_time": None,
        }

    async def reset(self) -> None:
        """리셋 (Noop이므로 아무것도 안 함)"""
        logger.debug(f"🔓 NoopCircuitBreaker 리셋: {self.name} (실제 동작 없음)")
