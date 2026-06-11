"""
Chat Router 대화 저장(영속화) 동작 테스트

/chat 엔드포인트의 대화 저장이 응답 반환 전에 인라인 await로 수행되는지 검증합니다.
- BackgroundTask로 미뤄지면 즉시 후속 질문이 직전 턴 없는 세션 컨텍스트를 읽는
  경합(race)이 발생하고, 저장 실패가 조용히 삼켜지는 문제가 있었습니다.
- 스트리밍 경로(chat_service.stream_rag_pipeline)는 인라인 저장이므로
  비스트리밍 경로도 동일하게 read-your-writes를 보장해야 합니다.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.chat_router import router, set_chat_service


def _build_rag_result() -> dict[str, Any]:
    """테스트용 RAG 파이프라인 결과 생성"""
    return {
        "answer": "테스트 답변입니다",
        "tokens_used": 42,
        "sources": [
            {
                "id": 1,
                "document": "문서1",
                "relevance": 0.9,
                "content_preview": "문서1 미리보기",
            }
        ],
        "topic": "테스트",
        "model_info": {"model": "test-model"},
    }


def _build_chat_service(call_order: list[str]) -> MagicMock:
    """호출 순서를 기록하는 스텁 ChatService 생성

    Args:
        call_order: 메서드 호출 순서가 기록될 리스트

    Returns:
        스텁 ChatService (MagicMock)
    """
    service = MagicMock()

    async def fake_handle_session(session_id: str | None, context: dict[str, Any]) -> dict[str, Any]:
        call_order.append("handle_session")
        return {"success": True, "session_id": "resolved-session-id"}

    async def fake_execute_rag_pipeline(
        message: str, session_id: str, options: dict[str, Any]
    ) -> dict[str, Any]:
        call_order.append("execute_rag_pipeline")
        return _build_rag_result()

    async def fake_add_conversation(
        session_id: str,
        user_message: str,
        assistant_answer: str,
        metadata: dict[str, Any],
    ) -> None:
        call_order.append("add_conversation_to_session")

    def fake_update_stats(stats: dict[str, Any]) -> None:
        call_order.append("update_stats")

    service.handle_session = AsyncMock(side_effect=fake_handle_session)
    service.execute_rag_pipeline = AsyncMock(side_effect=fake_execute_rag_pipeline)
    service.add_conversation_to_session = AsyncMock(side_effect=fake_add_conversation)
    service.update_stats = MagicMock(side_effect=fake_update_stats)
    return service


@pytest.fixture
def call_order() -> list[str]:
    """호출 순서 기록용 리스트"""
    return []


@pytest.fixture
def app_with_stub_service(call_order: list[str]):
    """스텁 ChatService가 주입된 FastAPI 앱 생성"""
    service = _build_chat_service(call_order)
    app = FastAPI()
    app.include_router(router)
    set_chat_service(service)
    yield app, service
    set_chat_service(None)  # type: ignore[arg-type]


@pytest.mark.unit
class TestChatPersistenceInline:
    """대화 저장이 응답 반환 전 인라인 await로 수행되는지 검증"""

    def test_persistence_awaited_before_response_handler_completes(
        self, app_with_stub_service, call_order: list[str]
    ) -> None:
        """
        저장이 응답 핸들러 완료 전에 await되는지 검증

        Given: 호출 순서를 기록하는 스텁 ChatService
        When: POST /chat 요청
        Then: add_conversation_to_session이 update_stats(핸들러 내 응답 직전 호출)보다
              먼저 호출됨 — BackgroundTask였다면 응답 후(update_stats 뒤)에 실행됨
        """
        app, service = app_with_stub_service
        client = TestClient(app)

        response = client.post("/chat", json={"message": "안녕하세요"})

        assert response.status_code == 200
        assert "add_conversation_to_session" in call_order, "대화 저장이 호출되어야 함"
        # 핵심 단언: 저장(add_conversation_to_session)이 핸들러 내부의
        # update_stats보다 먼저 실행되어야 함 (인라인 await 증거).
        # BackgroundTask 방식이면 순서가 [.., update_stats, add_conversation_to_session]이 됨.
        assert call_order.index("add_conversation_to_session") < call_order.index(
            "update_stats"
        ), f"저장이 응답 반환 전에 await되어야 함. 실제 순서: {call_order}"

    def test_persistence_called_with_resolved_session_and_answer(
        self, app_with_stub_service, call_order: list[str]
    ) -> None:
        """
        저장 호출 인자 검증 (세션 ID, 사용자 메시지, 답변)

        Given: 스텁 ChatService
        When: POST /chat 요청
        Then: 확정된 세션 ID, 원본 메시지, RAG 답변으로 저장 호출
        """
        app, service = app_with_stub_service
        client = TestClient(app)

        client.post("/chat", json={"message": "질문입니다"})

        service.add_conversation_to_session.assert_awaited_once()
        args = service.add_conversation_to_session.await_args.args
        assert args[0] == "resolved-session-id"
        assert args[1] == "질문입니다"
        assert args[2] == "테스트 답변입니다"

    def test_persistence_failure_propagates_to_client(
        self, call_order: list[str]
    ) -> None:
        """
        저장 실패가 삼켜지지 않고 에러로 전파되는지 검증

        Given: add_conversation_to_session이 예외를 던지는 스텁 ChatService
        When: POST /chat 요청
        Then: 200이 아닌 에러 응답 (저장 실패 숨김 금지)
        """
        service = _build_chat_service(call_order)
        service.add_conversation_to_session = AsyncMock(
            side_effect=RuntimeError("DB 저장 실패")
        )
        app = FastAPI()
        app.include_router(router)
        set_chat_service(service)
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/chat", json={"message": "저장 실패 테스트"})

            # 저장 실패는 사용자에게 전파되어야 함 (BackgroundTask 방식은 200 반환).
            assert response.status_code != 200, (
                "저장 실패 시 성공 응답을 반환하면 안 됨 (에러 숨김 금지)"
            )
        finally:
            set_chat_service(None)  # type: ignore[arg-type]
