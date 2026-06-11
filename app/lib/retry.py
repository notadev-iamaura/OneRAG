"""
재시도 백오프 공용 유틸리티
========================================
기능: 지수/선형/고정 백오프 지연 시간 계산을 공용 함수로 제공

여러 모듈에 산재하던 백오프 지연 계산 로직을 한 곳으로 모은 모듈입니다.
가장 일반화된 형태인 ``ExternalAPICaller._calculate_backoff_delay``의 동작을
그대로 옮겨, 전략(strategy)과 지연 한계(cap)를 파라미터로 받습니다.

동작 보존 주의:
- 입력 단위는 밀리초(ms)이며 반환 단위는 초(s)입니다.
- ``max_delay_ms``로 최대 지연 시간을 제한합니다(상한이 없으면 충분히 큰 값 전달).
- 부동소수점 결과가 기존 호출부와 정확히 일치하도록 연산 순서를 유지합니다.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    retry_if_result,
    stop_after_attempt,
    stop_never,
    wait_exponential_jitter,
    wait_fixed,
    wait_incrementing,
    wait_random,
)
from tenacity.retry import retry_base
from tenacity.stop import stop_base
from tenacity.wait import wait_base

# 재시도 폭주(thundering herd) 완화용 공용 jitter 기본값
# base 지연에 [0, DEFAULT_BACKOFF_JITTER_S) 범위의 무작위 지연을 더합니다.
# 여러 모듈(sitemap, notion_client, llm_enricher, session_manager)에 각자
# 정의되어 있던 0.5초 상수를 이 한 곳으로 통일합니다.
DEFAULT_BACKOFF_JITTER_S: float = 0.5


class BackoffStrategy(Enum):
    """재시도 백오프 전략"""

    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    FIXED = "fixed"


def calculate_backoff_delay(attempt: int, retry_config: dict[str, Any]) -> float:
    """
    재시도 백오프 지연 시간 계산

    ``retry_config`` 딕셔너리에서 전략과 지연 파라미터를 읽어 지연 시간을 계산합니다.
    기존 ``ExternalAPICaller._calculate_backoff_delay``와 동일한 동작을 보장합니다.

    Args:
        attempt: 시도 횟수 (0부터 시작)
        retry_config: 재시도 설정. 다음 키를 사용합니다.
            - ``backoff_strategy``: "exponential" | "linear" | "fixed" (기본 "exponential")
            - ``initial_delay_ms``: 초기 지연(밀리초, 기본 1000)
            - ``max_delay_ms``: 최대 지연(밀리초, 기본 5000)

    Returns:
        지연 시간 (초)
    """
    strategy_str = retry_config.get("backoff_strategy", "exponential")
    strategy = BackoffStrategy(strategy_str)

    initial_delay_ms = retry_config.get("initial_delay_ms", 1000)
    max_delay_ms = retry_config.get("max_delay_ms", 5000)

    if strategy == BackoffStrategy.EXPONENTIAL:
        # 지수 백오프: delay = initial * (2 ^ attempt)
        delay_ms = initial_delay_ms * (2**attempt)
    elif strategy == BackoffStrategy.LINEAR:
        # 선형 백오프: delay = initial * (attempt + 1)
        delay_ms = initial_delay_ms * (attempt + 1)
    else:  # FIXED
        # 고정 백오프
        delay_ms = initial_delay_ms

    # 최대 지연 시간 제한
    delay_ms = min(delay_ms, max_delay_ms)

    return cast(float, delay_ms / 1000.0)  # 밀리초 → 초


# =============================================================================
# tenacity 기반 공용 재시도 헬퍼 (jitter 표준화)
# =============================================================================
#
# 설계 의도:
# - 각 모듈이 산재하던 ``for attempt in range(...) + asyncio.sleep(backoff)`` 패턴을
#   선언적 정책(RetryPolicy)으로 표현하도록 표준화합니다.
# - tenacity의 ``wait_exponential_jitter`` / ``wait_incrementing`` / ``wait_fixed``로
#   jitter(무작위 지연 분산)를 추가해 "thundering herd"(동시 재시도 폭주)를 완화합니다.
#
# 동작 보존 주의 (tenacity 매핑):
# - tenacity의 ``attempt_number``는 **1부터** 시작합니다(기존 코드의 ``attempt``는 0부터).
# - ``wait_exponential_jitter(initial=i, max=m, jitter=j)``의 base 지연은
#   ``i * 2^(attempt_number - 1)`` 이며 그 위에 ``[0, j)`` 무작위 값을 더합니다.
#   따라서 기존 ``i * 2^attempt`` (attempt 0부터) 시퀀스와 base가 정확히 일치합니다.
#   단, base가 ``max``에 도달하면 jitter는 적용되지 않습니다(정확히 ``max``).
# - ``wait_incrementing(start=s, increment=inc)``는 ``s + inc * (attempt_number - 1)``로
#   선형 시퀀스를 만듭니다. increment 미지정(None) 시 initial과 동일하게 적용되어
#   기존 ``base * (attempt + 1)`` 시퀀스와 정확히 등가입니다.


def build_backoff_wait(
    strategy: "BackoffStrategy",
    *,
    initial_delay_s: float = 1.0,
    increment_s: float | None = None,
    max_delay_s: float = 60.0,
    jitter_s: float = 0.0,
) -> wait_base:
    """
    전략에 맞는 tenacity wait 객체 생성 (공용 빌더)

    ``RetryPolicy``의 wait 구성 구현체입니다. 예외 타입별 분기 등 정책 필드로
    표현할 수 없는 커스텀 wait를 직접 합성해야 하는 호출처(예: notion_client)도
    이 빌더로 개별 wait를 만들어 EXPONENTIAL/FIXED 분기 재구현을 피할 수 있습니다.

    Args:
        strategy: 백오프 전략 (EXPONENTIAL | LINEAR | FIXED).
        initial_delay_s: 초기 지연(초).
        increment_s: LINEAR 전략의 시도당 증가 폭(초).
            ``None``이면 ``initial_delay_s``를 사용해 ``initial * (attempt + 1)``
            선형 시퀀스와 등가가 됩니다.
        max_delay_s: 지연 상한(초). 상한이 없으면 ``float("inf")``를 전달합니다.
        jitter_s: 무작위 지연 범위(초). ``[0, jitter_s)`` 값을 base에 더합니다.

    Returns:
        구성된 tenacity wait 객체
    """
    if strategy == BackoffStrategy.EXPONENTIAL:
        # base = initial * 2^(attempt_number - 1), 상한 max_delay_s, jitter 추가
        return wait_exponential_jitter(
            initial=initial_delay_s,
            max=max_delay_s,
            jitter=jitter_s,
        )
    if strategy == BackoffStrategy.LINEAR:
        # increment 미지정 시 initial과 동일 — initial * (attempt + 1) 시퀀스 재현
        increment = initial_delay_s if increment_s is None else increment_s
        # jitter는 별도 합성(wait_incrementing 자체에는 jitter 옵션이 없음)
        base = wait_incrementing(
            start=initial_delay_s,
            increment=increment,
            max=max_delay_s,
        )
        if jitter_s > 0.0:
            return base + wait_random(0, jitter_s)
        return base
    # FIXED
    base_fixed: wait_base = wait_fixed(initial_delay_s)
    if jitter_s > 0.0:
        return base_fixed + wait_random(0, jitter_s)
    return base_fixed


class _WaitZeroOnResultRetry(wait_base):
    """
    결과(result) 기반 재시도는 무대기(0초), 예외 기반 재시도는 내부 wait에 위임

    ``RetryPolicy.retry_on_result`` 설정 시 자동으로 적용됩니다.
    "호출 자체는 성공했지만 결과가 불충분(예: 빈 LLM 응답, 파싱 실패)"한 경우는
    외부 서비스 장애가 아니므로 백오프 없이 즉시 재시도합니다
    (기존 llm_enricher의 falsy result ``continue`` 동작 보존).
    """

    def __init__(self, inner: wait_base) -> None:
        # 예외 기반 재시도에 적용할 내부 wait 전략
        self._inner = inner

    def __call__(self, retry_state: RetryCallState) -> float:
        # outcome.failed == True(예외 발생)면 내부 백오프, 아니면(결과 기반) 무대기
        if retry_state.outcome is not None and retry_state.outcome.failed:
            # tenacity wait_base.__call__의 타입 정보가 Any로 추론되어 명시 캐스팅
            return cast(float, self._inner(retry_state))
        return 0.0


@dataclass(frozen=True)
class RetryPolicy:
    """
    선언적 재시도 정책

    각 모듈이 "최대 횟수, 초기/최대 지연, 재시도 대상 예외, 백오프 전략"을
    선언적으로 표현하도록 하는 정책 객체입니다. ``build_async_retrying()``으로
    tenacity의 ``AsyncRetrying`` 인스턴스를 생성합니다.

    Attributes:
        max_attempts: 최대 시도 횟수. ``None``이면 무한 재시도(``stop_never``).
        strategy: 백오프 전략 (EXPONENTIAL | LINEAR | FIXED).
        initial_delay_s: 초기 지연 시간(초).
            - EXPONENTIAL: 첫 재시도 base 지연 (이후 ``initial * 2^n``).
            - LINEAR: 첫 재시도 지연 (이후 선형 증가).
            - FIXED: 고정 지연 시간.
        increment_s: LINEAR 전략에서 시도마다 증가하는 지연 폭(초).
            ``None``(기본)이면 ``initial_delay_s``를 사용해
            ``initial * (attempt + 1)`` 선형 시퀀스와 등가가 됩니다.
        max_delay_s: 지연 상한(초). EXPONENTIAL에서 base가 이 값에 도달하면 고정됩니다.
            상한이 필요 없으면 ``float("inf")``를 전달합니다.
        jitter_s: 추가할 무작위 지연 범위(초). ``[0, jitter_s)`` 값을 base에 더합니다.
            ``0.0``이면 jitter 없음(기존 동작과 정확히 동일).
        retry_exceptions: 재시도 대상 예외 타입 튜플.
        reraise: 최종 실패 시 마지막 예외를 그대로 raise할지 여부.
            ``True``면 tenacity의 ``RetryError`` 래핑 없이 원본 예외를 전파합니다.
            단, 결과 기반 재시도 소진은 예외가 없으므로 ``RetryError``가 발생합니다.
        retry_on_result: 결과 기반 재시도 조건 함수.
            설정 시 반환 결과가 이 함수에서 ``True``로 평가되면 재시도합니다.
            결과 기반 재시도는 **무대기(0초)** 즉시 재시도이며, 백오프는
            예외 기반 재시도에만 적용됩니다. 사용 시 tenacity 공식 패턴에 따라
            ``with attempt`` 블록 밖에서 ``attempt.retry_state.set_result(...)``로
            결과를 전달해야 합니다.
        wait_override: 커스텀 wait 전략 직접 주입(예외 타입별 분기 등 정책 필드로
            표현할 수 없는 wait용). 설정 시 strategy/initial_delay_s/increment_s/
            max_delay_s/jitter_s 필드는 무시됩니다. 내부 wait 구성에는
            ``build_backoff_wait()``를 활용해 중복 구현을 피하십시오.
    """

    retry_exceptions: tuple[type[BaseException], ...]
    max_attempts: int | None = 3
    strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    initial_delay_s: float = 1.0
    # LINEAR 증가 폭. None이면 initial_delay_s 사용 → initial*(attempt+1) 등가
    increment_s: float | None = None
    max_delay_s: float = 60.0
    jitter_s: float = 0.0
    reraise: bool = True
    # before_sleep 콜백(로깅 등). tenacity가 재시도 직전 호출합니다.
    before_sleep: Any = field(default=None)
    # 결과 기반 재시도 조건 (무대기 즉시 재시도). 예: 빈 LLM 응답 재시도
    retry_on_result: Callable[[Any], bool] | None = None
    # 커스텀 wait 직접 주입 (예외 타입별 분기 등). 설정 시 백오프 필드 무시
    wait_override: wait_base | None = None

    def _build_wait(self) -> wait_base:
        """전략에 맞는 tenacity wait 객체 생성 (커스텀 주입 시 그대로 사용)"""
        if self.wait_override is not None:
            return self.wait_override
        return build_backoff_wait(
            self.strategy,
            initial_delay_s=self.initial_delay_s,
            increment_s=self.increment_s,
            max_delay_s=self.max_delay_s,
            jitter_s=self.jitter_s,
        )

    def _build_stop(self) -> stop_base:
        """최대 시도 횟수에 맞는 tenacity stop 객체 생성"""
        if self.max_attempts is None:
            return stop_never
        return stop_after_attempt(self.max_attempts)

    def build_async_retrying(self) -> AsyncRetrying:
        """
        정책으로부터 tenacity ``AsyncRetrying`` 인스턴스 생성

        사용 예시::

            policy = RetryPolicy(
                retry_exceptions=(httpx.TimeoutException,),
                max_attempts=5,
                initial_delay_s=1.0,
                max_delay_s=16.0,
                jitter_s=0.5,
            )
            async for attempt in policy.build_async_retrying():
                with attempt:
                    return await do_request()

        Returns:
            구성된 ``AsyncRetrying`` 인스턴스
        """
        retry_condition: retry_base = retry_if_exception_type(self.retry_exceptions)
        wait: wait_base = self._build_wait()
        if self.retry_on_result is not None:
            # 결과 기반 재시도 합성: 조건 만족 결과(무대기) 또는 대상 예외(백오프)
            retry_condition = retry_if_result(self.retry_on_result) | retry_condition
            # 결과 기반 재시도에는 백오프를 적용하지 않음 (즉시 재시도)
            wait = _WaitZeroOnResultRetry(wait)

        kwargs: dict[str, Any] = {
            "stop": self._build_stop(),
            "wait": wait,
            "retry": retry_condition,
            "reraise": self.reraise,
        }
        if self.before_sleep is not None:
            kwargs["before_sleep"] = self.before_sleep
        return AsyncRetrying(**kwargs)
