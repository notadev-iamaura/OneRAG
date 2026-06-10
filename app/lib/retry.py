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

from enum import Enum
from typing import Any, cast


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
