"""
app.lib.retry.RetryPolicy 헬퍼 단위 테스트

목적:
- tenacity 기반 공용 재시도 헬퍼 ``RetryPolicy``의 동작을 고정합니다.
- 각 백오프 전략(EXPONENTIAL/LINEAR/FIXED)의 대기 시퀀스, jitter 범위,
  최대 시도 횟수, reraise 동작을 단언합니다.
"""

import asyncio
from typing import Any

import pytest

from app.lib.retry import BackoffStrategy, RetryPolicy


class _MyError(Exception):
    """테스트용 재시도 대상 예외"""


@pytest.fixture
def sleep_recorder(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """tenacity 재시도 대기 시간을 기록하는 픽스처 (전역 asyncio.sleep 교체)"""
    waits: list[float] = []

    async def _fake_sleep(seconds: float, *args: Any, **kwargs: Any) -> None:
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    return waits


async def _run_failing(policy: RetryPolicy, fail_times: int) -> int:
    """fail_times번 실패 후 성공하는 시나리오 실행. 총 호출 횟수 반환."""
    calls = {"n": 0}
    async for attempt in policy.build_async_retrying():
        with attempt:
            calls["n"] += 1
            if calls["n"] <= fail_times:
                raise _MyError()
    return calls["n"]


@pytest.mark.asyncio
async def test_exponential_no_jitter(sleep_recorder: list[float]) -> None:
    """EXPONENTIAL: initial=1, max=16 → 1,2,4,8 (재시도 대기)"""
    policy = RetryPolicy(
        retry_exceptions=(_MyError,),
        max_attempts=5,
        strategy=BackoffStrategy.EXPONENTIAL,
        initial_delay_s=1.0,
        max_delay_s=16.0,
        jitter_s=0.0,
    )
    with pytest.raises(_MyError):
        await _run_failing(policy, fail_times=99)
    assert sleep_recorder == [1.0, 2.0, 4.0, 8.0]


@pytest.mark.asyncio
async def test_exponential_with_jitter_range(sleep_recorder: list[float]) -> None:
    """EXPONENTIAL + jitter: 각 대기는 [base, base+jitter) 범위"""
    policy = RetryPolicy(
        retry_exceptions=(_MyError,),
        max_attempts=4,
        strategy=BackoffStrategy.EXPONENTIAL,
        initial_delay_s=1.0,
        max_delay_s=100.0,
        jitter_s=0.5,
    )
    with pytest.raises(_MyError):
        await _run_failing(policy, fail_times=99)
    bases = [1.0, 2.0, 4.0]
    assert len(sleep_recorder) == len(bases)
    for actual, base in zip(sleep_recorder, bases, strict=True):
        assert base <= actual < base + 0.5


@pytest.mark.asyncio
async def test_linear_no_jitter(sleep_recorder: list[float]) -> None:
    """LINEAR: start=2, increment=2 → 2,4 (재시도 대기)"""
    policy = RetryPolicy(
        retry_exceptions=(_MyError,),
        max_attempts=3,
        strategy=BackoffStrategy.LINEAR,
        initial_delay_s=2.0,
        increment_s=2.0,
        max_delay_s=1000.0,
        jitter_s=0.0,
    )
    with pytest.raises(_MyError):
        await _run_failing(policy, fail_times=99)
    assert sleep_recorder == [2.0, 4.0]


@pytest.mark.asyncio
async def test_fixed_no_jitter(sleep_recorder: list[float]) -> None:
    """FIXED: initial=1.0 → 1.0, 1.0 (재시도 대기)"""
    policy = RetryPolicy(
        retry_exceptions=(_MyError,),
        max_attempts=3,
        strategy=BackoffStrategy.FIXED,
        initial_delay_s=1.0,
        jitter_s=0.0,
    )
    with pytest.raises(_MyError):
        await _run_failing(policy, fail_times=99)
    assert sleep_recorder == [1.0, 1.0]


@pytest.mark.asyncio
async def test_recovers_after_failures(sleep_recorder: list[float]) -> None:
    """실패 후 성공: 재시도 대기 후 정상 종료"""
    policy = RetryPolicy(
        retry_exceptions=(_MyError,),
        max_attempts=5,
        strategy=BackoffStrategy.EXPONENTIAL,
        initial_delay_s=1.0,
        max_delay_s=16.0,
        jitter_s=0.0,
    )
    total_calls = await _run_failing(policy, fail_times=2)
    assert total_calls == 3  # 2번 실패 + 1번 성공
    assert sleep_recorder == [1.0, 2.0]


@pytest.mark.asyncio
async def test_non_retry_exception_propagates_immediately(
    sleep_recorder: list[float],
) -> None:
    """재시도 대상이 아닌 예외: 즉시 전파, 대기 없음"""
    policy = RetryPolicy(
        retry_exceptions=(_MyError,),
        max_attempts=5,
        jitter_s=0.0,
    )

    async def _run() -> None:
        async for attempt in policy.build_async_retrying():
            with attempt:
                raise ValueError("not retryable")

    with pytest.raises(ValueError):
        await _run()
    assert sleep_recorder == []


@pytest.mark.asyncio
async def test_reraise_false_wraps_in_retry_error(sleep_recorder: list[float]) -> None:
    """reraise=False: 소진 시 RetryError로 래핑"""
    from tenacity import RetryError

    policy = RetryPolicy(
        retry_exceptions=(_MyError,),
        max_attempts=2,
        strategy=BackoffStrategy.FIXED,
        initial_delay_s=1.0,
        jitter_s=0.0,
        reraise=False,
    )
    with pytest.raises(RetryError):
        await _run_failing(policy, fail_times=99)
