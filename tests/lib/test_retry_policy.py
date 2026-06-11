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
async def test_linear_default_increment_equals_initial(
    sleep_recorder: list[float],
) -> None:
    """
    LINEAR increment 미지정: increment_s=None이면 initial_delay_s를 사용해
    ``initial * (attempt + 1)`` 시퀀스와 등가 — initial=2 → 2,4,6 (재시도 대기)
    """
    policy = RetryPolicy(
        retry_exceptions=(_MyError,),
        max_attempts=4,
        strategy=BackoffStrategy.LINEAR,
        initial_delay_s=2.0,
        # increment_s 미지정 (기본 None → initial_delay_s 사용)
        max_delay_s=1000.0,
        jitter_s=0.0,
    )
    with pytest.raises(_MyError):
        await _run_failing(policy, fail_times=99)
    # docstring의 등가성 주장 검증: 2*(0+1), 2*(1+1), 2*(2+1) = 2, 4, 6
    assert sleep_recorder == [2.0, 4.0, 6.0]


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


@pytest.mark.asyncio
async def test_retry_on_result_zero_wait(sleep_recorder: list[float]) -> None:
    """retry_on_result: falsy 결과 재시도는 무대기(0초), 시도 횟수 소진까지 반복"""
    from tenacity import RetryError

    policy = RetryPolicy(
        retry_exceptions=(_MyError,),
        max_attempts=3,
        strategy=BackoffStrategy.EXPONENTIAL,
        initial_delay_s=1.0,
        jitter_s=0.0,
        retry_on_result=lambda result: not result,  # falsy 결과면 재시도
    )
    calls = {"n": 0}

    async def _run() -> None:
        async for attempt in policy.build_async_retrying():
            with attempt:
                calls["n"] += 1
            # tenacity 공식 패턴: with 블록 밖에서 결과를 명시적으로 전달
            if not attempt.retry_state.outcome.failed:  # type: ignore[union-attr]
                attempt.retry_state.set_result(None)  # 항상 falsy

    # 결과 기반 재시도 소진: 예외가 없으므로 RetryError 발생 (reraise=True여도 동일)
    with pytest.raises(RetryError):
        await _run()
    assert calls["n"] == 3  # max_attempts 모두 시도
    # 결과 기반 재시도는 모두 무대기 (백오프는 예외 기반에만 적용)
    assert sleep_recorder == [0.0, 0.0]


@pytest.mark.asyncio
async def test_retry_on_result_exception_still_backs_off(
    sleep_recorder: list[float],
) -> None:
    """retry_on_result 설정 시에도 예외 기반 재시도는 기존 백오프 적용"""
    policy = RetryPolicy(
        retry_exceptions=(_MyError,),
        max_attempts=4,
        strategy=BackoffStrategy.EXPONENTIAL,
        initial_delay_s=1.0,
        max_delay_s=100.0,
        jitter_s=0.0,
        retry_on_result=lambda result: not result,
    )
    calls = {"n": 0}

    async def _run() -> int:
        async for attempt in policy.build_async_retrying():
            with attempt:
                calls["n"] += 1
                if calls["n"] <= 2:
                    raise _MyError()
            if not attempt.retry_state.outcome.failed:  # type: ignore[union-attr]
                attempt.retry_state.set_result({"ok": True})  # truthy → 종료
        return calls["n"]

    total = await _run()
    assert total == 3  # 예외 2번 + 성공 1번
    # 예외 기반 재시도 대기: 지수 백오프 1, 2 (무대기 아님)
    assert sleep_recorder == [1.0, 2.0]


@pytest.mark.asyncio
async def test_wait_override_takes_precedence(sleep_recorder: list[float]) -> None:
    """wait_override: 커스텀 wait 주입 시 정책의 백오프 필드 대신 사용"""
    from tenacity import wait_fixed

    policy = RetryPolicy(
        retry_exceptions=(_MyError,),
        max_attempts=3,
        strategy=BackoffStrategy.EXPONENTIAL,  # 무시되어야 함
        initial_delay_s=99.0,  # 무시되어야 함
        jitter_s=0.0,
        wait_override=wait_fixed(7.0),
    )
    with pytest.raises(_MyError):
        await _run_failing(policy, fail_times=99)
    # 커스텀 wait(고정 7초)가 적용됨 — 지수 백오프(99,198) 아님
    assert sleep_recorder == [7.0, 7.0]
