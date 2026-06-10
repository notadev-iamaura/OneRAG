"""동기→비동기 스트림 브리지(`aiter_sync_stream`) 단위 테스트.

정상 경로뿐 아니라 조기 종료(early-break)·소비 task 취소 시
**정리가 유한 시간 내에 끝남**을 `asyncio.wait_for(..., timeout=...)`로
단언한다(임의 sleep 대신 상태/타임아웃 기반 검증).
"""

import asyncio
import threading

import pytest

from app.modules.core.generation._async_bridge import aiter_sync_stream


class _InfiniteSyncStream:
    """무한히 청크를 산출하는 동기 Stream 모방 객체.

    실제 SDK Stream처럼 `__iter__`만 제공하고 `__aiter__`는 없다.
    `close()` 호출 또는 stop_event를 통해 협조적으로 종료된다.
    """

    def __init__(self) -> None:
        self.closed = threading.Event()
        self.iterations = 0

    def __iter__(self):
        while not self.closed.is_set():
            self.iterations += 1
            yield f"chunk-{self.iterations}"

    def close(self) -> None:
        self.closed.set()


class _FiniteSyncStream:
    """유한 청크를 산출하는 동기 Stream 모방 객체."""

    def __init__(self, items):
        self.items = list(items)
        self.closed = False

    def __iter__(self):
        yield from self.items

    def close(self) -> None:
        self.closed = True


class _ExplodingSyncStream:
    """일부 청크 후 예외를 던지는 동기 Stream 모방 객체."""

    def __iter__(self):
        yield "정상"
        raise RuntimeError("스트림 중단")


@pytest.mark.asyncio
async def test_aiter_yields_all_chunks_in_order():
    """정상 경로: 모든 청크를 순서대로 yield한다."""
    stream = _FiniteSyncStream(["a", "b", "c"])

    received = []
    async for chunk in aiter_sync_stream(stream):
        received.append(chunk)

    assert received == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_aiter_propagates_iteration_error():
    """동기 순회 중 예외가 소비 측으로 전파된다."""
    stream = _ExplodingSyncStream()

    received = []
    with pytest.raises(RuntimeError, match="스트림 중단"):
        async for chunk in aiter_sync_stream(stream):
            received.append(chunk)

    assert received == ["정상"]


@pytest.mark.asyncio
async def test_early_break_cleans_up_within_timeout():
    """조기 종료(early-break): 무한 스트림을 1청크만 소비 후 break해도
    정리가 유한 시간 내에 끝나야 한다(데드락 없음)."""
    stream = _InfiniteSyncStream()

    async def consume_one_then_break():
        async for chunk in aiter_sync_stream(stream):
            assert chunk.startswith("chunk-")
            break  # 첫 청크만 소비하고 즉시 종료

    # 정리가 hang하면 wait_for가 TimeoutError를 던진다 → 데드락 검출
    await asyncio.wait_for(consume_one_then_break(), timeout=2.0)

    # 협조적 중단으로 스트림이 닫혀야 한다
    assert stream.closed.is_set()


@pytest.mark.asyncio
async def test_consumer_cancellation_cleans_up_within_timeout():
    """소비 task 취소: 무한 스트림을 소비 중 task를 cancel해도
    정리가 유한 시간 내에 끝나야 한다(데드락 없음)."""
    stream = _InfiniteSyncStream()
    started = asyncio.Event()

    async def consume_forever():
        async for _chunk in aiter_sync_stream(stream):
            started.set()
            # 계속 소비(취소될 때까지)
            await asyncio.sleep(0.01)

    task = asyncio.create_task(consume_forever())
    # 소비가 실제로 시작될 때까지 대기(임의 sleep 아님)
    await asyncio.wait_for(started.wait(), timeout=2.0)

    task.cancel()
    # 취소 후 정리가 유한 시간 내 완료되어야 한다
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_cleanup_timeout_does_not_hang_when_close_ineffective():
    """close()가 무력하고 스트림이 멈추지 않아도, cleanup_timeout 내에
    정리가 분리(detach)되어 영구 hang하지 않는다."""

    class _UnstoppableStream:
        """stop_event/close를 무시하고 계속 청크를 내는 악성 스트림.

        단, 테스트가 영원히 돌지 않도록 상한을 둔다(생산 스레드가 결국 종료되도록).
        """

        def __init__(self) -> None:
            self.count = 0

        def __iter__(self):
            # close()를 제공하지 않아 협조적 중단 신호에도 즉시 멈추지 않음.
            # 다만 무한 루프 방지를 위해 큰 상한을 둔다.
            while self.count < 100_000:
                self.count += 1
                yield f"x-{self.count}"

        # close 미제공: getattr(stream, "close", None) → None

    stream = _UnstoppableStream()

    async def consume_one_then_break():
        # cleanup_timeout을 짧게 주어 정리가 빠르게 분리되는지 확인
        async for _chunk in aiter_sync_stream(stream, cleanup_timeout=0.2):
            break

    # 정리가 분리되어 유한 시간 내 반환되어야 한다
    await asyncio.wait_for(consume_one_then_break(), timeout=3.0)
