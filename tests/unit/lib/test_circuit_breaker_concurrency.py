"""
CircuitBreaker 동시성 결함 테스트 (Phase 2.7)

목적:
    (1) OPEN 상태에서 느린 fallback이 lock을 잡아 breaker 전체를 직렬화하던 결함,
    (2) HALF_OPEN 시험 요청 게이트 부재(동시 요청 전부 통과),
    (3) half_open_timeout 미사용을 회귀 방지한다.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.lib.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)


async def _ok() -> str:
    return "ok"


@pytest.mark.asyncio
async def test_open_fallback_not_serialized_by_lock() -> None:
    """OPEN 상태의 느린 fallback이 다른 호출을 lock으로 막지 않아야 한다."""
    cb = CircuitBreaker("t", CircuitBreakerConfig(timeout=100.0))
    cb.state = CircuitState.OPEN
    cb.stats.state_change_time = time.time()  # reset 불가 → 계속 OPEN

    slow_started = asyncio.Event()

    async def slow_fallback() -> str:
        slow_started.set()
        await asyncio.sleep(0.3)
        return "slow"

    # 첫 호출: 느린 fallback 실행 (lock을 잡으면 안 됨)
    task1 = asyncio.create_task(cb.call(_ok, fallback=slow_fallback))
    await slow_started.wait()

    # 두 번째 호출: 첫 fallback이 도는 중에도 빠르게 완료돼야 함
    async def quick_fallback() -> str:
        return "quick"

    result2 = await asyncio.wait_for(
        cb.call(_ok, fallback=quick_fallback), timeout=0.1
    )
    assert result2 == "quick", "느린 fallback의 lock에 막힘 (직렬화)"
    await task1


@pytest.mark.asyncio
async def test_half_open_gate_limits_concurrent_trials() -> None:
    """HALF_OPEN에서 success_threshold를 초과하는 시험 요청은 fast-fail해야 한다."""
    cb = CircuitBreaker(
        "t", CircuitBreakerConfig(success_threshold=1, half_open_timeout=100.0)
    )
    cb.state = CircuitState.HALF_OPEN
    cb.stats.state_change_time = time.time()
    cb._half_open_in_flight = 1  # 이미 한도 도달

    called = []

    async def fn() -> str:
        called.append(1)
        return "real"

    result = await cb.call(fn, fallback=lambda: "fb")
    assert result == "fb", "시험 요청 한도 초과인데 통과함"
    assert called == [], "한도 초과 요청이 백엔드를 호출함"


@pytest.mark.asyncio
async def test_half_open_timeout_reverts_to_open() -> None:
    """HALF_OPEN이 half_open_timeout을 넘기면 OPEN으로 복귀해야 한다."""
    cb = CircuitBreaker(
        "t", CircuitBreakerConfig(timeout=100.0, half_open_timeout=0.01)
    )
    cb.state = CircuitState.HALF_OPEN
    cb.stats.state_change_time = time.time() - 1.0  # 1초 경과 > 0.01

    called = []

    async def fn() -> str:
        called.append(1)
        return "real"

    result = await cb.call(fn, fallback=lambda: "fb")
    assert cb.state == CircuitState.OPEN, "Half-Open 타임아웃 후 OPEN 복귀 안 함"
    assert result == "fb"
    assert called == [], "타임아웃 복귀 후에도 백엔드를 호출함"
