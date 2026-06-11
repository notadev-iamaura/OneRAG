"""
Metrics Collection System
비용 추적 + 성능 메트릭 통합 시스템
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Any

from .logger import get_logger

logger = get_logger(__name__)


# ========================================
# 비용 추적
# ========================================


@dataclass
class CostTracker:
    """LLM API 비용 추적기"""

    # 제공자별 비용 (USD / 1M tokens)
    COST_PER_MILLION_TOKENS = {
        "google": {
            "input": 0.125,  # Gemini 2.0 Flash input
            "output": 0.5,  # Gemini 2.0 Flash output
        },
        "openai": {
            "input": 2.5,  # GPT-4o input
            "output": 10.0,  # GPT-4o output
        },
        "anthropic": {
            "input": 3.0,  # Claude 3.5 Sonnet input
            "output": 15.0,  # Claude 3.5 Sonnet output
        },
    }

    # 누적 토큰 사용량
    total_tokens: dict[str, int] = field(
        default_factory=lambda: {"google": 0, "openai": 0, "anthropic": 0}
    )

    # 누적 비용 (USD)
    total_cost: dict[str, float] = field(
        default_factory=lambda: {"google": 0.0, "openai": 0.0, "anthropic": 0.0}
    )

    # 요청 수
    request_count: dict[str, int] = field(
        default_factory=lambda: {"google": 0, "openai": 0, "anthropic": 0}
    )

    # 시작 시간
    start_time: datetime = field(default_factory=datetime.now)

    # Thread-safe
    _lock: Lock = field(default_factory=Lock)

    def track_usage(self, provider: str, tokens_used: int, is_input: bool = False) -> None:
        """
        토큰 사용량 기록

        Args:
            provider: LLM 제공자 (google, openai, anthropic)
            tokens_used: 사용된 토큰 수
            is_input: True면 input 토큰, False면 output 토큰
        """
        with self._lock:
            if provider not in self.total_tokens:
                logger.warning(f"알 수 없는 제공자: {provider}")
                return

            # 토큰 누적
            self.total_tokens[provider] += tokens_used
            self.request_count[provider] += 1

            # 비용 계산
            token_type = "input" if is_input else "output"
            cost_per_million = self.COST_PER_MILLION_TOKENS[provider][token_type]
            cost = (tokens_used / 1_000_000) * cost_per_million

            self.total_cost[provider] += cost

            logger.debug(
                f"💰 비용 추적: {provider} {token_type} " f"{tokens_used} tokens = ${cost:.4f}"
            )

    def get_summary(self) -> dict[str, Any]:
        """비용 요약 정보 반환"""
        with self._lock:
            total_tokens_all = sum(self.total_tokens.values())
            total_cost_all = sum(self.total_cost.values())
            total_requests_all = sum(self.request_count.values())

            elapsed_hours = (datetime.now() - self.start_time).total_seconds() / 3600

            return {
                "total_cost_usd": round(total_cost_all, 4),
                "total_tokens": total_tokens_all,
                "total_requests": total_requests_all,
                "elapsed_hours": round(elapsed_hours, 2),
                "cost_per_hour": (
                    round(total_cost_all / elapsed_hours, 4) if elapsed_hours > 0 else 0
                ),
                "by_provider": {
                    provider: {
                        "tokens": self.total_tokens[provider],
                        "cost_usd": round(self.total_cost[provider], 4),
                        "requests": self.request_count[provider],
                    }
                    for provider in ["google", "openai", "anthropic"]
                },
                "start_time": self.start_time.isoformat(),
            }

    def reset(self) -> None:
        """통계 리셋"""
        with self._lock:
            self.total_tokens = dict.fromkeys(self.total_tokens, 0)
            self.total_cost = dict.fromkeys(self.total_cost, 0.0)
            self.request_count = dict.fromkeys(self.request_count, 0)
            self.start_time = datetime.now()
            logger.info("🔄 비용 추적 통계 리셋")


# ========================================
# 성능 메트릭
# ========================================


@dataclass
class PerformanceMetrics:
    """성능 메트릭 수집"""

    # 함수별 메트릭 (최근 100건 윈도우 — 지연시간 통계 전용)
    function_metrics: dict[str, list[float]] = field(default_factory=dict)

    # 에러 카운트 (무한 누적)
    error_counts: dict[str, int] = field(default_factory=dict)

    # 함수별 누적 호출 카운터 (윈도우와 별개로 무한 누적 —
    # error_rate 분모로 사용. 윈도우 count를 분모로 쓰면
    # 누적 에러 ÷ 최근 100건이 되어 100%를 초과하는 왜곡이 발생한다)
    call_counts: dict[str, int] = field(default_factory=dict)

    # Thread-safe
    _lock: Lock = field(default_factory=Lock)

    def record_latency(self, function_name: str, latency_ms: float) -> None:
        """
        응답 시간 기록

        Args:
            function_name: 함수 이름
            latency_ms: 응답 시간 (밀리초)
        """
        with self._lock:
            if function_name not in self.function_metrics:
                self.function_metrics[function_name] = []

            self.function_metrics[function_name].append(latency_ms)

            # 누적 호출 수는 윈도우와 별개로 무한 누적
            self.call_counts[function_name] = self.call_counts.get(function_name, 0) + 1

            # 최근 100개만 유지
            if len(self.function_metrics[function_name]) > 100:
                self.function_metrics[function_name].pop(0)

    def record_error(self, function_name: str) -> None:
        """에러 기록"""
        with self._lock:
            if function_name not in self.error_counts:
                self.error_counts[function_name] = 0

            self.error_counts[function_name] += 1

    def _get_stats_unlocked(self, function_name: str) -> dict[str, Any]:
        """
        함수별 통계 계산 (락 미획득 내부 헬퍼)

        호출자가 self._lock을 이미 보유한 상태에서 호출해야 한다.
        get_all_stats()가 락을 잡은 채 get_stats()를 재호출하면
        비재진입 Lock의 중복 획득으로 자기 데드락이 발생하므로,
        락 없는 계산 로직을 이 헬퍼로 분리한다.
        """
        latencies = self.function_metrics.get(function_name, [])

        if not latencies:
            # 에러만 기록된 함수도 누적값은 정확히 반환한다
            return {
                "function": function_name,
                "count": 0,
                "total_calls": self.call_counts.get(function_name, 0),
                "avg_latency_ms": 0,
                "min_latency_ms": 0,
                "max_latency_ms": 0,
                "p95_latency_ms": 0,
                "errors": self.error_counts.get(function_name, 0),
            }

        sorted_latencies = sorted(latencies)
        count = len(latencies)
        p95_index = int(count * 0.95)

        return {
            "function": function_name,
            # count = 최근 윈도우 크기(≤100, 지연시간 통계의 표본 수 — 호환성 유지)
            "count": count,
            # total_calls = 누적 성공 호출 수 (error_rate 분모용)
            "total_calls": self.call_counts.get(function_name, 0),
            "avg_latency_ms": round(sum(latencies) / count, 2),
            "min_latency_ms": round(min(latencies), 2),
            "max_latency_ms": round(max(latencies), 2),
            "p95_latency_ms": round(sorted_latencies[p95_index], 2) if p95_index < count else 0,
            "errors": self.error_counts.get(function_name, 0),
        }

    def get_stats(self, function_name: str) -> dict[str, Any]:
        """함수별 통계 반환"""
        with self._lock:
            return self._get_stats_unlocked(function_name)

    def get_all_stats(self) -> dict[str, Any]:
        """
        모든 함수 통계 반환

        락을 한 번만 획득하고 락 없는 헬퍼를 반복 호출한다
        (get_stats 재호출 시 비재진입 Lock 중복 획득 데드락 방지).
        에러만 기록된 함수(function_metrics에 키 없음)도 누락 없이 포함한다.
        """
        with self._lock:
            all_functions = self.function_metrics.keys() | self.error_counts.keys()
            return {fn: self._get_stats_unlocked(fn) for fn in all_functions}

    def reset(self) -> None:
        """통계 리셋"""
        with self._lock:
            self.function_metrics.clear()
            self.error_counts.clear()
            self.call_counts.clear()
            logger.info("🔄 성능 메트릭 통계 리셋")


# ========================================
# 전역 인스턴스
# ========================================

_global_performance_metrics: PerformanceMetrics | None = None


def _get_performance_metrics() -> PerformanceMetrics:
    """
    전역 성능 메트릭 가져오기 (내부용)

    이 함수는 모듈 내부에서만 사용됩니다.
    외부에서는 DI Container의 AppContainer.performance_metrics를 사용하세요.

    Returns:
        PerformanceMetrics: 전역 성능 메트릭 인스턴스
    """
    global _global_performance_metrics
    if _global_performance_metrics is None:
        _global_performance_metrics = PerformanceMetrics()
        logger.info("✅ 전역 성능 메트릭 초기화")
    return _global_performance_metrics


# ========================================
# 헬퍼 함수
# ========================================


def track_function_performance(function_name: str) -> Any:
    """함수 성능 측정 데코레이터"""

    def decorator(func: Any) -> Any:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.time()
            metrics = _get_performance_metrics()

            try:
                result = await func(*args, **kwargs)
                latency_ms = (time.time() - start_time) * 1000
                metrics.record_latency(function_name, latency_ms)
                return result
            except Exception:
                metrics.record_error(function_name)
                raise

        return wrapper

    return decorator


# ========================================
# 호환성 Export
# ========================================

# rag_pipeline.py 호환성을 위한 전역 metrics 객체
metrics = _get_performance_metrics()
