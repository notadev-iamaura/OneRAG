"""동기 iterable을 비동기 제너레이터로 안전하게 브리지하는 동시성 유틸리티.

목적
----
동기(synchronous) OpenAI 클라이언트가 반환하는 스트리밍 `Stream` 객체는
`__iter__`만 제공하므로 `async for`로 직접 순회할 수 없고, 동기 순회는 네트워크
I/O 대기 동안 이벤트 루프(event loop)를 블로킹한다. 이 모듈은 동기 순회를
백그라운드 스레드에서 수행하고, 각 청크를 `asyncio.Queue`로 전달해 호출 측이
`async for`로 안전하게 소비하도록 한다.

데드락 방지 설계
----------------
청크마다 `asyncio.to_thread(next, ...)`를 호출하는 단순 구현은 (1) 청크당
스레드 디스패치 비용이 들고, (2) 소비자가 조기 종료(early-break)하면 네트워크
read에 블로킹된 `next` 호출이 남아 스트림이 닫히지 않는 문제가 있다.

본 구현은 다음으로 데드락 표면을 제거한다.
1. **비블로킹 적재**: `loop.call_soon_threadsafe(queue.put_nowait, item)`. 생산
   스레드는 이벤트 루프에 적재를 위임만 하고 절대 블로킹하지 않는다.
2. **협조적 중단(cooperative cancellation)**: `threading.Event`(stop_event)를 매
   청크마다 검사. 소비자 조기 종료 시 이 이벤트를 set하면 생산 루프가 다음
   반복에서 break하여 자연 종료한다. 추가로 `sync_stream.close()`를 호출해
   네트워크 read에 블로킹된 스레드를 풀어준다.
3. **정리 시간 한정**: 정리 단계에서 `asyncio.wait_for(asyncio.shield(producer),
   timeout)`로 생산 태스크 완료를 **유한 시간**만 기다린다. 타임아웃 시 더
   기다리지 않고 분리(스레드는 close 후 자연 종료에 맡김) → `finally` 영구 hang 방지.

백프레셔(backpressure) 트레이드오프
-----------------------------------
비블로킹 `put_nowait`를 쓰려면 큐가 **unbounded**여야 한다(bounded면 가득 찼을 때
put_nowait가 실패 → 데이터 손실 또는 블로킹 재도입). 여기서는 **unbounded 큐를
의도적으로 선택**한다. 근거:
- LLM 토큰 청크는 보통 수~수십 바이트로 매우 작다.
- 한 응답은 `max_tokens`로 상한이 있어 큐에 쌓일 총량이 유한하고 작다
  (예: 20K 토큰 × 수 바이트 ≈ 수백 KB 수준, 일시적).
- 소비자(SSE/WebSocket)는 일반적으로 생산 속도(네트워크 LLM 응답)와 비슷하거나
  빠르게 소비하므로 큐가 무한정 누적되지 않는다.
따라서 백프레셔 부재로 인한 메모리 위험은 무시 가능하며, 데드락 제거 이득이 훨씬 크다.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator
from typing import Any

from ....lib.logger import get_logger

logger = get_logger(__name__)

# 정리 단계에서 생산 태스크 종료를 기다리는 최대 시간(초).
# 이 시간을 넘기면 더 기다리지 않고 분리한다(데드락/영구 hang 방지).
_CLEANUP_TIMEOUT_SECONDS = 5.0


class _StreamError:
    """생산 스레드에서 발생한 예외를 소비 측으로 전달하기 위한 래퍼.

    생산 측(`except Exception`)과 소비 측 검사를 대칭으로 맞추기 위해
    예외를 명시적 마커 객체로 감싼다. 소비 측은 `isinstance(item, _StreamError)`로
    명확히 구분한다.
    """

    __slots__ = ("error",)

    def __init__(self, error: BaseException) -> None:
        self.error = error


async def aiter_sync_stream(
    sync_stream: Any,
    *,
    cleanup_timeout: float = _CLEANUP_TIMEOUT_SECONDS,
) -> AsyncGenerator[Any, None]:
    """동기 iterable(OpenAI 동기 Stream)을 비동기 제너레이터로 브리지한다.

    동기 순회는 백그라운드 스레드에서 수행하고, 각 청크를 이벤트 루프에 비블로킹으로
    적재한다. 소비자 조기 종료/예외 시에도 유한 시간 내 정리되어 데드락이 없다.

    Args:
        sync_stream: `__iter__`를 제공하는 동기 iterable (OpenAI Stream 등).
            선택적으로 `close()`를 제공하면 조기 종료 시 호출해 네트워크 연결을 닫는다.
        cleanup_timeout: 정리 단계에서 생산 태스크 종료를 기다릴 최대 시간(초).

    Yields:
        Any: 동기 Stream이 산출하는 각 청크.

    Raises:
        BaseException: 동기 순회 중 발생한 예외를 소비 측으로 그대로 전파한다.
    """
    loop = asyncio.get_running_loop()
    # unbounded 큐(상단 docstring의 백프레셔 트레이드오프 참고)
    queue: asyncio.Queue[Any] = asyncio.Queue()
    # 스트림 정상 종료를 알리는 센티넬
    done_sentinel = object()
    # 소비자 조기 종료를 생산 스레드에 알리는 협조적 중단 신호
    stop_event = threading.Event()

    def _enqueue(item: Any) -> None:
        """이벤트 루프 스레드에서 큐에 비블로킹 적재한다."""
        # call_soon_threadsafe로 루프 스레드에 위임 → 생산 스레드는 블로킹하지 않음
        loop.call_soon_threadsafe(queue.put_nowait, item)

    def _produce() -> None:
        """백그라운드 스레드: 동기 Stream을 순회하며 큐에 청크를 적재한다.

        매 청크마다 stop_event를 검사해 소비자 조기 종료에 협조적으로 응답한다.
        """
        try:
            for chunk in sync_stream:
                if stop_event.is_set():
                    # 소비자가 중단을 요청 → 생산 루프 자연 종료
                    break
                _enqueue(chunk)
            else:
                # break 없이 정상 소진된 경우에만 종료 센티넬 전송
                _enqueue(done_sentinel)
        except Exception as exc:  # noqa: BLE001 - 예외를 소비 측으로 전파
            _enqueue(_StreamError(exc))

    producer = asyncio.create_task(asyncio.to_thread(_produce))
    try:
        while True:
            item = await queue.get()
            if item is done_sentinel:
                break
            if isinstance(item, _StreamError):
                raise item.error
            yield item
    finally:
        # 조기 종료(early-break)/예외/취소 시 정리.
        # 1) 협조적 중단 신호 → 생산 루프가 다음 반복에서 break
        stop_event.set()
        # 2) 동기 Stream close() → 네트워크 read에 블로킹된 스레드를 풀어줌
        close = getattr(sync_stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:  # noqa: BLE001 - 정리 단계 close 실패는 치명적이지 않음
                logger.debug(f"스트림 close 실패(무시): {exc}")
        # 3) 생산 태스크 완료를 유한 시간만 대기(영구 hang 방지).
        #    shield로 감싸 wait_for 타임아웃이 producer 자체를 취소하지 않도록 한다.
        try:
            await asyncio.wait_for(asyncio.shield(producer), timeout=cleanup_timeout)
        except TimeoutError:
            # 타임아웃: 스레드는 close 후 자연 종료에 맡기고 더 기다리지 않는다.
            logger.warning(
                "스트림 브리지 정리 타임아웃(%.1fs) — 생산 스레드를 분리합니다.",
                cleanup_timeout,
            )
        except asyncio.CancelledError:
            # 소비 측 취소는 그대로 전파
            raise
        except Exception as exc:  # noqa: BLE001 - 정리 단계 예외는 로깅 후 흡수
            logger.warning(f"스트림 브리지 정리 중 예외(무시): {exc}")
