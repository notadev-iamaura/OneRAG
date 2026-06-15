"""인프로세스 동시성 수용 테스트 (이벤트 루프 직렬화 퇴행 게이트).

httpx.ASGITransport로 실제 FastAPI 라우터/미들웨어 스택을 통과시켜,
N개의 동시 POST /chat 요청이 이벤트 루프에서 직렬화되지 않고 동시에
처리되는지를 검증한다.

왜 필요한가(범용 가치):
- 누군가 /chat 경로에 블로킹 호출(예: 동기 I/O)이나 전역 lock을 넣어
  동시성을 깨뜨리면, 단일 순차 요청 테스트로는 잡지 못한다.
- 이 테스트는 mock ChatService를 주입하므로 외부 API/비용이 0이며,
  순수하게 "라우터/미들웨어 스택이 요청을 병렬로 받아들이는가"만 검증한다.

마커 분류:
- integration: in-process 서버(실제 라우터 스택)를 띄우므로 unit보다 무겁다.
- performance: mock 기반 무비용 동시성 게이트(e2e의 "실 API·유료"와 구분).
  기본 게이트(tests/unit)에서는 수집되지 않는다.

JapanRAG 원본 대비 일반화:
- 멀티테넌트 전용 필드(company_id/user_context)와 일본어 응답 문자열 제거.
- OneRAG ChatRequest 필수 필드는 message뿐이므로 {"message": ...}만 전송.
- model_info는 provider/model 모두 도메인 중립 값("test"/"test-model")으로 둔다.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

# 동시성 수준: 이벤트 루프가 직렬화하지 않는다면 N개가 동시에 in-flight여야 한다.
CONCURRENCY = 10

pytestmark = [pytest.mark.integration, pytest.mark.performance]


def _build_app_with_service(mock_service: MagicMock) -> FastAPI:
    """mock ChatService가 주입된 FastAPI 앱을 구성한다.

    실제 chat_router를 include하므로 라우터 핸들러/미들웨어 경로를 그대로 통과한다.
    """
    from app.api.routers.chat_router import router, set_chat_service

    app = FastAPI()
    app.include_router(router)
    set_chat_service(mock_service)
    return app


def _build_concurrent_chat_service() -> MagicMock:
    """동시 in-flight 요청 수를 계측하는 mock ChatService를 생성한다.

    execute_rag_pipeline은 짧게 await asyncio.sleep으로 처리 중 상태를 만들고,
    그 사이 동시에 진입한 요청 수의 최대값(max_active_requests)을 기록한다.
    이벤트 루프가 요청을 직렬화하면 최대값이 1에 머문다.
    """
    mock_service = MagicMock()
    mock_service.modules = {}
    # handle_session 시그니처: (session_id, context) — chat_router.py와 정합.
    mock_service.handle_session = AsyncMock(
        side_effect=lambda session_id, _context: {
            "success": True,
            "session_id": session_id or "perf-session",
        }
    )
    mock_service.add_conversation_to_session = AsyncMock()
    mock_service.update_stats = MagicMock()
    mock_service.get_stats = MagicMock(return_value={})

    lock = asyncio.Lock()
    active_requests = 0
    max_active_requests = 0

    async def execute_rag_pipeline(
        message: str,
        session_id: str,
        options: dict[str, object],
    ) -> dict[str, object]:
        """execute_rag_pipeline 시그니처: (message, session_id, options) — chat_router.py와 정합."""
        nonlocal active_requests, max_active_requests
        async with lock:
            active_requests += 1
            max_active_requests = max(max_active_requests, active_requests)
        # 처리 중 상태를 의도적으로 유지해 동시 진입 여부를 관측 가능하게 한다.
        await asyncio.sleep(0.1)
        async with lock:
            active_requests -= 1
        return {
            "answer": f"answer: {message}",
            "sources": [],
            "tokens_used": 16,
            "topic": "operational_performance",
            "model_info": {
                "provider": "test",
                "model": "test-model",
                "session_id": session_id,
            },
        }

    mock_service.execute_rag_pipeline = AsyncMock(side_effect=execute_rag_pipeline)
    # 테스트에서 관측한 동시 in-flight 최대값을 읽기 위한 헬퍼.
    mock_service.max_active_requests = lambda: max_active_requests
    return mock_service


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_chat_accepts_concurrent_users_without_event_loop_serialization() -> None:
    """N개 동시 /chat 요청이 직렬화 없이 동시에 처리되는지 검증.

    Given: 동시 in-flight 수를 계측하는 mock ChatService가 주입된 in-process 앱
    When: asyncio.gather로 N개 POST /chat을 동시에 발사
    Then:
      - 전체 소요 시간이 N*sleep(직렬화 시 예상치)보다 훨씬 짧고 10초 미만
      - 동시 in-flight 최대값 == N (이벤트 루프가 요청을 직렬화하지 않음)
      - 모든 응답 200, processing_time < 10초
      - execute_rag_pipeline이 정확히 N회 await됨
    """
    from app.api.routers.chat_router import set_chat_service

    service = _build_concurrent_chat_service()
    app = _build_app_with_service(service)
    transport = httpx.ASGITransport(app=app)

    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://onerag.local",
            timeout=10.0,
        ) as client:
            started = time.monotonic()
            responses = await asyncio.gather(
                *[
                    # 범용화: message만 전송(멀티테넌트 전용 필드 제거).
                    client.post("/chat", json={"message": f"perf check {index}"})
                    for index in range(CONCURRENCY)
                ]
            )
            elapsed = time.monotonic() - started

        assert elapsed < 10.0, f"동시 처리가 비정상적으로 느림: {elapsed:.2f}s"
        assert service.max_active_requests() == CONCURRENCY, (
            "이벤트 루프가 요청을 직렬화함 "
            f"(최대 동시 in-flight={service.max_active_requests()}, 기대={CONCURRENCY})"
        )
        assert all(response.status_code == 200 for response in responses)
        assert all(response.json()["processing_time"] < 10.0 for response in responses)
        assert service.execute_rag_pipeline.await_count == CONCURRENCY
    finally:
        # 전역 chat_service 상태를 다른 테스트에 누수시키지 않도록 정리한다.
        set_chat_service(None)  # type: ignore[arg-type]
