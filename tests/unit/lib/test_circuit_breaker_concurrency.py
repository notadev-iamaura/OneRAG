"""
CircuitBreaker 동시성 결함 테스트 (Phase 2.7)

목적:
    (1) OPEN 상태에서 느린 fallback이 lock을 잡아 breaker 전체를 직렬화하던 결함,
    (2) HALF_OPEN 시험 요청 게이트 부재(동시 요청 전부 통과),
    (3) half_open_timeout 미사용,
    (4) HALF_OPEN 회계 결함 3종을 회귀 방지한다:
        (4a) stale trial(이전 사이클의 시험 요청)이 새 사이클의 카운터를 오염시켜
             threshold 초과 동시 진입 + 조기 CLOSED를 유발
        (4b) finally의 슬롯 해제가 lock acquire를 await하는 동안 취소되면
             감소가 건너뛰어져 시험 슬롯이 영구 누수
        (4c) HALF_OPEN 사이클 재진입 시 consecutive_successes 미리셋으로
             이전 사이클의 성공이 합산되어 조기 CLOSED
    (5) CLOSED 시기에 시작된 장기 호출(stale)의 늦은 결과가 HALF_OPEN 사이클을
        오염시키는 결함:
        (5a) stale 성공이 consecutive_successes에 합산되어 실제 probe 1건만으로
             조기 CLOSED → 미복구 백엔드로 트래픽 전면 재개
        (5b) stale 실패가 HALF_OPEN → OPEN 복귀를 유발해 정상 probe를 무효화
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


# ========================================
# HALF_OPEN 회계 결함 3종 (Phase 2.7 후속)
# ========================================


def _accounting_config() -> CircuitBreakerConfig:
    """회계 결함 테스트용 공통 설정 (실패 1회 → OPEN, 성공 2회 → CLOSED)."""
    return CircuitBreakerConfig(
        failure_threshold=1,
        success_threshold=2,
        timeout=60.0,
        half_open_timeout=100.0,
        enable_error_rate_check=False,
    )


async def _fail() -> None:
    raise RuntimeError("boom")


async def _force_open(cb: CircuitBreaker) -> None:
    """CLOSED → OPEN 전환 (failure_threshold=1 전제)."""
    with pytest.raises(RuntimeError):
        await cb.call(_fail)
    assert cb.state == CircuitState.OPEN


def _allow_half_open_reset(cb: CircuitBreaker) -> None:
    """sleep 없이 OPEN → HALF_OPEN 전환 조건(timeout 경과)을 시뮬레이션한다."""
    cb.stats.state_change_time = time.time() - cb.config.timeout - 1.0


@pytest.mark.asyncio
async def test_stale_trial_does_not_pollute_new_half_open_cycle() -> None:
    """(4a) 이전 사이클의 stale trial이 새 사이클의 슬롯/연속 성공을 오염시키면 안 된다."""
    cb = CircuitBreaker("t", _accounting_config())
    await _force_open(cb)

    # --- 사이클 A 진입: 느린 시험 요청 T1 시작 ---
    _allow_half_open_reset(cb)
    t1_started = asyncio.Event()
    t1_gate = asyncio.Event()

    async def slow_trial_a() -> str:
        t1_started.set()
        await t1_gate.wait()
        return "A-ok"

    t1 = asyncio.create_task(cb.call(slow_trial_a))
    await t1_started.wait()
    assert cb.state == CircuitState.HALF_OPEN
    assert cb._half_open_in_flight == 1

    # 사이클 A에서 다른 시험 요청 실패 → OPEN 복귀 (T1은 아직 실행 중 = stale)
    with pytest.raises(RuntimeError):
        await cb.call(_fail)
    assert cb.state == CircuitState.OPEN

    # --- 사이클 B 진입: 시험 요청 b1, b2가 한도(2)까지 진입 ---
    _allow_half_open_reset(cb)
    b1_started, b1_gate = asyncio.Event(), asyncio.Event()
    b2_started, b2_gate = asyncio.Event(), asyncio.Event()

    async def slow_trial_b(started: asyncio.Event, gate: asyncio.Event) -> str:
        started.set()
        await gate.wait()
        return "B-ok"

    b1 = asyncio.create_task(cb.call(slow_trial_b, b1_started, b1_gate))
    await b1_started.wait()
    b2 = asyncio.create_task(cb.call(slow_trial_b, b2_started, b2_gate))
    await b2_started.wait()
    assert cb.state == CircuitState.HALF_OPEN
    assert cb._half_open_in_flight == 2

    # --- stale T1 완료: 새 사이클 카운터/연속 성공에 영향이 없어야 한다 ---
    t1_gate.set()
    assert await t1 == "A-ok"
    assert cb._half_open_in_flight == 2, "stale trial이 새 사이클 슬롯을 잘못 해제함"
    assert cb.stats.consecutive_successes == 0, "stale 성공이 연속 성공에 합산됨"
    assert cb.state == CircuitState.HALF_OPEN

    # 한도(2)가 유지되므로 추가 시험 요청은 fast-fail해야 한다 (초과 진입 금지)
    called: list[int] = []

    async def fn() -> str:
        called.append(1)
        return "x"

    result = await cb.call(fn, fallback=lambda: "fb")
    assert result == "fb", "stale 감소로 한도가 풀려 초과 진입 발생"
    assert called == []

    # 사이클 B의 '실제' 성공 1회만으로는 CLOSED 전환 금지 (threshold=2)
    b1_gate.set()
    assert await b1 == "B-ok"
    assert cb.state == CircuitState.HALF_OPEN, "stale 성공 합산으로 조기 CLOSED"
    assert cb.stats.consecutive_successes == 1

    # 두 번째 실제 성공으로 정상 CLOSED
    b2_gate.set()
    assert await b2 == "B-ok"
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_cancelled_trial_releases_slot_even_while_lock_held() -> None:
    """(4b) 다른 코루틴이 lock을 점유한 채 trial이 취소돼도 슬롯은 해제되어야 한다.

    슬롯 해제가 lock acquire를 await하면 그 대기 중 CancelledError가 전달될 때
    감소가 건너뛰어져 누수된다. 해제는 동기(awaits 없는) 연산이어야 한다.
    """
    cb = CircuitBreaker("t", _accounting_config())
    await _force_open(cb)
    _allow_half_open_reset(cb)

    started = asyncio.Event()
    gate = asyncio.Event()

    async def slow_trial() -> str:
        started.set()
        await gate.wait()
        return "ok"

    t1 = asyncio.create_task(cb.call(slow_trial))
    await started.wait()
    assert cb.state == CircuitState.HALF_OPEN
    assert cb._half_open_in_flight == 1

    # 외부 코루틴이 breaker lock 점유 (다른 call이 lock 구간에 있는 상황 모사)
    await cb._lock.acquire()
    try:
        # 취소 1회: func(gate.wait) 안에서 CancelledError 전달
        t1.cancel()
        # 이벤트 루프 양보 — 수정 전 구현이라면 t1이 finally의 lock acquire에서 대기
        for _ in range(5):
            await asyncio.sleep(0)
        # 취소 2회: (수정 전) finally의 lock acquire 대기 중 전달 → 감소 건너뜀
        #          (수정 후) t1은 이미 완료라 no-op
        t1.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
    finally:
        cb._lock.release()

    with pytest.raises(asyncio.CancelledError):
        await t1
    assert cb._half_open_in_flight == 0, "취소된 trial의 시험 슬롯이 누수됨"


# ========================================
# CLOSED 시기 시작 호출의 stale 결과가 HALF_OPEN 사이클 오염 (결함 5)
# ========================================


@pytest.mark.asyncio
async def test_stale_closed_origin_success_does_not_pollute_half_open() -> None:
    """(5a) CLOSED 시기에 시작된 호출의 늦은 성공이 HALF_OPEN 회계를 오염시키면 안 된다.

    시나리오: CLOSED에서 느린 호출 S 시작 → 장애로 OPEN → HALF_OPEN 전환(세대 +1)
    → 그 사이 S가 성공 완료. S의 성공이 consecutive_successes에 합산되면
    실제 probe 1건 + 과거 성공 1건으로 threshold(2)를 채워 조기 CLOSED 된다.
    """
    cb = CircuitBreaker("t", _accounting_config())

    # --- CLOSED 상태에서 느린 성공 호출 S 시작 (asyncio.Event로 결정적 제어) ---
    s_started, s_gate = asyncio.Event(), asyncio.Event()

    async def slow_closed_call() -> str:
        s_started.set()
        await s_gate.wait()
        return "S-ok"

    s = asyncio.create_task(cb.call(slow_closed_call))
    await s_started.wait()
    assert cb.state == CircuitState.CLOSED

    # --- S 실행 중 장애 발생 → OPEN (failure_threshold=1) ---
    with pytest.raises(RuntimeError):
        await cb.call(_fail)
    assert cb.state == CircuitState.OPEN

    # --- OPEN → HALF_OPEN 전환: 느린 probe P1 진입 (세대 +1) ---
    _allow_half_open_reset(cb)
    p1_started, p1_gate = asyncio.Event(), asyncio.Event()

    async def slow_probe() -> str:
        p1_started.set()
        await p1_gate.wait()
        return "P-ok"

    p1 = asyncio.create_task(cb.call(slow_probe))
    await p1_started.wait()
    assert cb.state == CircuitState.HALF_OPEN

    # --- stale S 완료: 새 사이클의 연속 성공에 합산되면 안 된다 ---
    s_gate.set()
    assert await s == "S-ok"
    assert cb.stats.consecutive_successes == 0, "CLOSED 시기 stale 성공이 연속 성공에 합산됨"
    assert cb.state == CircuitState.HALF_OPEN

    # --- 실제 probe 1건 성공만으로는 CLOSED 금지 (threshold=2) ---
    p1_gate.set()
    assert await p1 == "P-ok"
    assert cb.state == CircuitState.HALF_OPEN, "stale 성공 합산으로 조기 CLOSED"
    assert cb.stats.consecutive_successes == 1

    # --- 두 번째 실제 probe 성공으로만 정상 CLOSED ---
    assert await cb.call(_ok) == "ok"
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_stale_closed_origin_failure_does_not_reopen_half_open() -> None:
    """(5b) CLOSED 시기에 시작된 호출의 늦은 실패가 HALF_OPEN → OPEN을 유발하면 안 된다.

    대칭 시나리오: CLOSED에서 시작된 느린 실패 호출이 HALF_OPEN 전환 후 완료되면,
    현재 사이클의 probe와 무관한 과거 실패가 복구 시도를 무효화(OPEN 복귀)한다.
    """
    cb = CircuitBreaker("t", _accounting_config())

    # --- CLOSED 상태에서 느린 실패 호출 F 시작 ---
    f_started, f_gate = asyncio.Event(), asyncio.Event()

    async def slow_failing_call() -> None:
        f_started.set()
        await f_gate.wait()
        raise RuntimeError("late-fail")

    f = asyncio.create_task(cb.call(slow_failing_call))
    await f_started.wait()

    # --- F 실행 중 장애 발생 → OPEN ---
    with pytest.raises(RuntimeError):
        await cb.call(_fail)
    assert cb.state == CircuitState.OPEN

    # --- OPEN → HALF_OPEN 전환: 느린 probe P1 진입 (세대 +1) ---
    _allow_half_open_reset(cb)
    p1_started, p1_gate = asyncio.Event(), asyncio.Event()

    async def slow_probe() -> str:
        p1_started.set()
        await p1_gate.wait()
        return "P-ok"

    p1 = asyncio.create_task(cb.call(slow_probe))
    await p1_started.wait()
    assert cb.state == CircuitState.HALF_OPEN

    # --- stale F 실패 완료: HALF_OPEN → OPEN 복귀를 유발하면 안 된다 ---
    f_gate.set()
    with pytest.raises(RuntimeError):
        await f
    assert cb.state == CircuitState.HALF_OPEN, "stale 실패가 HALF_OPEN → OPEN 유발"

    # --- 실제 probe 2건 성공으로 정상 CLOSED ---
    p1_gate.set()
    assert await p1 == "P-ok"
    assert cb.state == CircuitState.HALF_OPEN
    assert await cb.call(_ok) == "ok"
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_half_open_reentry_resets_consecutive_successes() -> None:
    """(4c) HALF_OPEN 사이클 재진입 시 이전 사이클의 연속 성공이 리셋되어야 한다.

    half_open_timeout 경과로 OPEN 복귀할 때는 실패가 기록되지 않으므로
    consecutive_successes가 잔존한다 — 재진입 시 리셋하지 않으면 새 사이클에서
    성공 1회만으로 조기 CLOSED 된다.
    """
    cb = CircuitBreaker("t", _accounting_config())
    await _force_open(cb)

    # 사이클 1 진입: 성공 1회 (threshold=2 미달 → HALF_OPEN 유지)
    _allow_half_open_reset(cb)
    assert await cb.call(_ok) == "ok"
    assert cb.state == CircuitState.HALF_OPEN
    assert cb.stats.consecutive_successes == 1

    # half_open_timeout 초과 → 다음 호출에서 OPEN 복귀 (실패 기록 없는 전환)
    cb.stats.state_change_time = time.time() - cb.config.half_open_timeout - 1.0
    result = await cb.call(_ok, fallback=lambda: "fb")
    assert result == "fb"
    assert cb.state == CircuitState.OPEN

    # 사이클 2 재진입: 첫 성공만으로 CLOSED 되면 안 된다 (연속 성공 리셋 검증)
    _allow_half_open_reset(cb)
    assert await cb.call(_ok) == "ok"
    assert cb.stats.consecutive_successes == 1
    assert cb.state == CircuitState.HALF_OPEN, "사이클 재진입 시 연속 성공 미리셋 (조기 CLOSED)"

    # 두 번째 성공으로 정상 CLOSED
    assert await cb.call(_ok) == "ok"
    assert cb.state == CircuitState.CLOSED
