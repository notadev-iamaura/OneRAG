"""
DemoSessionManager._cleanup_loop 백오프 특성 테스트 (characterization test)

목적:
- 백그라운드 정리 루프의 **현재 동작을 고정**합니다.
- 이 모듈은 "무한 주기 작업 + 실패 시 백오프"로, tenacity의 재시도 모델
  (실패 시 재시도, 성공 시 종료)과 근본적으로 다릅니다. 따라서 tenacity로
  이관하지 않고 **실패 백오프에 jitter만 추가**합니다.
- 본 테스트는 jitter 추가 전후로 다음이 보존됨을 단언합니다.

동작 보존 기준:
- 정상 주기: ``sleep(cleanup_interval)`` 후 ``cleanup_expired()`` 호출.
- 성공 시: consecutive_failures 리셋(다음 실패 백오프가 다시 작아짐).
- 실패 시: ``min(cleanup_interval * 2^consecutive_failures, 300)`` 백오프 대기.
- ``CancelledError``: 루프 즉시 종료(정상 sleep 중이든 백오프 sleep 중이든).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.demo.session_manager import DemoSessionManager

# jitter 범위: 실패 백오프 base에 [0, JITTER) 추가 (jitter 도입 후).
_JITTER = 0.5
# 정상 주기 sleep(cleanup_interval)은 jitter 없음(정확값).


@pytest.fixture
def mock_chroma_client() -> MagicMock:
    """인메모리 ChromaDB 클라이언트 Mock"""
    client = MagicMock()
    client.delete_collection = MagicMock()
    return client


@pytest.fixture
def manager(mock_chroma_client: MagicMock) -> DemoSessionManager:
    """cleanup_interval=10인 매니저"""
    return DemoSessionManager(
        chroma_client=mock_chroma_client,
        max_sessions=5,
        ttl_seconds=60,
        cleanup_interval=10,
    )


def _split_waits(
    waits: list[float], interval: float
) -> tuple[list[float], list[float]]:
    """
    sleep 시퀀스를 (정상 주기 대기, 실패 백오프 대기)로 분리.

    정상 주기는 정확히 ``interval``, 백오프는 ``interval * 2^n``(+jitter).
    """
    periodic = [w for w in waits if w == interval]
    backoff = [w for w in waits if w != interval]
    return periodic, backoff


@pytest.mark.asyncio
async def test_normal_cycle_calls_cleanup(
    manager: DemoSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """정상 주기: sleep(interval) 후 cleanup_expired 호출, 성공 시 백오프 없음"""
    waits: list[float] = []
    cleanup_calls = {"n": 0}

    async def fake_sleep(seconds: float, *a: object, **k: object) -> None:
        waits.append(seconds)
        # 3번째 주기 sleep에서 루프 종료 신호
        if cleanup_calls["n"] >= 2:
            raise asyncio.CancelledError()

    async def fake_cleanup() -> None:
        cleanup_calls["n"] += 1

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(manager, "cleanup_expired", AsyncMock(side_effect=fake_cleanup))

    await manager._cleanup_loop()

    # 정상 주기 sleep은 정확히 interval(10), cleanup_expired 정상 호출
    periodic, backoff = _split_waits(waits, 10.0)
    assert cleanup_calls["n"] == 2
    assert all(w == 10.0 for w in periodic)
    assert backoff == []  # 실패 없음 → 백오프 없음


@pytest.mark.asyncio
async def test_failure_exponential_backoff(
    manager: DemoSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    연속 실패: interval*2, interval*4, interval*8 ... 백오프.

    cleanup_interval=10 → 실패 1회차 20, 2회차 40, 3회차 80.
    """
    waits: list[float] = []
    state = {"cleanup_count": 0}

    async def fake_sleep(seconds: float, *a: object, **k: object) -> None:
        waits.append(seconds)
        # 백오프 sleep이 3번 누적되면 종료
        backoff_waits = [w for w in waits if w != 10.0]
        if len(backoff_waits) >= 3:
            raise asyncio.CancelledError()

    async def always_fail() -> None:
        state["cleanup_count"] += 1
        raise RuntimeError("cleanup boom")

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(manager, "cleanup_expired", AsyncMock(side_effect=always_fail))

    await manager._cleanup_loop()

    _, backoff = _split_waits(waits, 10.0)
    # 백오프 base 시퀀스: 20, 40, 80 (interval*2^failures, failures=1,2,3)
    expected_bases = [20.0, 40.0, 80.0]
    assert len(backoff) == 3
    for actual, base in zip(backoff, expected_bases, strict=True):
        # jitter 도입 전: 정확값. 도입 후: [base, base+jitter). 둘 다 만족.
        assert base <= actual < base + _JITTER, (
            f"백오프 {actual}가 [{base}, {base + _JITTER}) 범위를 벗어남"
        )


@pytest.mark.asyncio
async def test_backoff_capped_at_300(
    mock_chroma_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """백오프 상한: interval=100이면 1회차 200, 2회차 300(cap), 3회차 300(cap)"""
    mgr = DemoSessionManager(
        chroma_client=mock_chroma_client,
        max_sessions=5,
        ttl_seconds=60,
        cleanup_interval=100,
    )
    waits: list[float] = []

    async def fake_sleep(seconds: float, *a: object, **k: object) -> None:
        waits.append(seconds)
        backoff_waits = [w for w in waits if w != 100.0]
        if len(backoff_waits) >= 3:
            raise asyncio.CancelledError()

    async def always_fail() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(mgr, "cleanup_expired", AsyncMock(side_effect=always_fail))

    await mgr._cleanup_loop()

    _, backoff = _split_waits(waits, 100.0)
    # base: 200(=100*2), 300(=min(400,300)), 300(=min(800,300))
    expected_bases = [200.0, 300.0, 300.0]
    assert len(backoff) == 3
    for actual, base in zip(backoff, expected_bases, strict=True):
        assert base <= actual < base + _JITTER


@pytest.mark.asyncio
async def test_success_resets_failure_counter(
    manager: DemoSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """성공 시 consecutive_failures 리셋: 실패→성공→실패면 백오프가 다시 작아짐"""
    waits: list[float] = []
    # cleanup 시나리오: 실패, 실패, 성공, 실패 → 백오프 base 20, 40, (성공 리셋), 20
    outcomes = iter([False, False, True, False])  # False=실패, True=성공

    async def fake_sleep(seconds: float, *a: object, **k: object) -> None:
        waits.append(seconds)
        backoff_waits = [w for w in waits if w != 10.0]
        if len(backoff_waits) >= 3:
            raise asyncio.CancelledError()

    async def cleanup() -> None:
        ok = next(outcomes, True)
        if not ok:
            raise RuntimeError("boom")

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(manager, "cleanup_expired", AsyncMock(side_effect=cleanup))

    await manager._cleanup_loop()

    _, backoff = _split_waits(waits, 10.0)
    # 실패1→20, 실패2→40, 성공(리셋, 백오프 없음), 실패1→20
    expected_bases = [20.0, 40.0, 20.0]
    assert len(backoff) == 3
    for actual, base in zip(backoff, expected_bases, strict=True):
        assert base <= actual < base + _JITTER


@pytest.mark.asyncio
async def test_cancelled_during_periodic_sleep_exits(
    manager: DemoSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """정상 주기 sleep 중 CancelledError: 루프 즉시 종료"""
    cleanup_mock = AsyncMock()

    async def fake_sleep(seconds: float, *a: object, **k: object) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(manager, "cleanup_expired", cleanup_mock)

    # 예외 전파 없이 정상 반환되어야 함
    await manager._cleanup_loop()

    cleanup_mock.assert_not_called()  # 첫 sleep에서 취소되어 cleanup 미호출
