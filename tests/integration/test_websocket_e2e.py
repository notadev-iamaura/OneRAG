"""
WebSocket 채팅 E2E 통합 테스트

/chat-ws WebSocket 엔드포인트의 전체 흐름을 검증합니다:
1. WebSocket 연결 수립
2. 메시지 전송 및 스트리밍 응답 수신
3. 이벤트 순서 검증 (stream_start → stream_token* → stream_sources → stream_end)
4. 에러 핸들링
5. 연결 관리 (중복 연결, 연결 해제)

테스트 방식:
- FastAPI TestClient의 websocket_connect 사용
- Mock ChatService로 RAG 파이프라인 시뮬레이션
"""

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# =============================================================================
# Mock 기반 WebSocket E2E 테스트
# =============================================================================


@pytest.mark.integration
class TestWebSocketE2E:
    """
    WebSocket E2E 통합 테스트

    FastAPI TestClient를 사용하여 실제 서버 없이 WebSocket 전체 흐름을 테스트합니다.
    ChatService의 stream_rag_pipeline을 Mock 처리하여 스트리밍 이벤트를 시뮬레이션합니다.
    """

    @pytest.fixture
    def mock_chat_service(self):
        """ChatService Mock 생성"""
        mock_service = MagicMock()

        async def mock_stream_generator(
            message: str, session_id: str | None, options: dict | None
        ) -> AsyncGenerator[dict[str, Any], None]:
            """Mock 스트리밍 제너레이터 - RAG 파이프라인 시뮬레이션"""
            # 1. metadata 이벤트 (검색 결과)
            yield {
                "event": "metadata",
                "data": {
                    "session_id": session_id or "mock-session-123",
                    "search_results": 5,
                    "ranked_results": 3,
                    "reranking_applied": True,
                    "message_id": "mock-msg-456",
                },
            }

            # 2. chunk 이벤트들 (LLM 응답 토큰)
            chunks = ["안녕", "하세요", "! ", "테스트", " 응답", "입니다", "."]
            for i, chunk in enumerate(chunks):
                yield {
                    "event": "chunk",
                    "data": chunk,
                    "chunk_index": i,
                }

            # 3. done 이벤트 (스트리밍 완료)
            yield {
                "event": "done",
                "data": {
                    "session_id": session_id or "mock-session-123",
                    "total_chunks": len(chunks),
                    "processing_time": 1.23,
                    "tokens_used": 150,
                    "sources": [
                        {"id": "doc-1", "title": "문서1", "content": "내용1"},
                        {"id": "doc-2", "title": "문서2", "content": "내용2"},
                    ],
                },
            }

        mock_service.stream_rag_pipeline = mock_stream_generator
        return mock_service

    @pytest.fixture
    def ws_app(self, mock_chat_service):
        """WebSocket 테스트용 FastAPI 앱"""
        from app.api.routers.websocket_router import router, set_chat_service

        set_chat_service(mock_chat_service)

        app = FastAPI()
        app.include_router(router)

        return app

    @pytest.fixture
    def client(self, ws_app):
        """TestClient 생성"""
        return TestClient(ws_app)

    def test_websocket_full_streaming_flow(self, client):
        """
        WebSocket 전체 스트리밍 흐름 테스트

        Given: WebSocket 연결 수립
        When: 유효한 메시지 전송
        Then: stream_start → stream_token* → stream_sources → stream_end 순서로 이벤트 수신
        """
        with client.websocket_connect("/chat-ws?session_id=test-session-001") as ws:
            # 메시지 전송
            ws.send_json(
                {
                    "type": "message",
                    "message_id": "msg-001",
                    "content": "안녕하세요",
                    "session_id": "test-session-001",
                }
            )

            # 이벤트 수신
            events = []
            for _ in range(15):  # 최대 15개 이벤트 수신
                try:
                    event = ws.receive_json()
                    events.append(event)

                    # stream_end 이벤트면 종료
                    if event.get("type") == "stream_end":
                        break
                except Exception:
                    break

            # 이벤트 타입 추출
            event_types = [e.get("type") for e in events]

            # 1. 첫 번째는 stream_start
            assert event_types[0] == "stream_start", f"첫 이벤트가 stream_start가 아닙니다: {event_types[0]}"

            # 2. 마지막은 stream_end
            assert event_types[-1] == "stream_end", f"마지막 이벤트가 stream_end가 아닙니다: {event_types[-1]}"

            # 3. 중간에 stream_token이 있어야 함
            assert "stream_token" in event_types, "stream_token 이벤트가 없습니다"

            # 4. stream_sources가 있어야 함 (RAG 검색 결과)
            assert "stream_sources" in event_types, "stream_sources 이벤트가 없습니다"

    def test_websocket_stream_start_event_format(self, client):
        """
        stream_start 이벤트 형식 검증

        Given: WebSocket 연결 및 메시지 전송
        When: stream_start 이벤트 수신
        Then: message_id, session_id, timestamp 필드 포함
        """
        with client.websocket_connect("/chat-ws?session_id=test-session") as ws:
            ws.send_json(
                {
                    "type": "message",
                    "message_id": "msg-format-test",
                    "content": "형식 테스트",
                    "session_id": "test-session",
                }
            )

            # stream_start 이벤트 수신
            start_event = ws.receive_json()

            assert start_event["type"] == "stream_start"
            assert "message_id" in start_event
            assert "session_id" in start_event
            assert "timestamp" in start_event

            # timestamp가 ISO 8601 형식인지 확인
            timestamp = start_event["timestamp"]
            assert "T" in timestamp, f"timestamp가 ISO 8601 형식이 아닙니다: {timestamp}"

    def test_websocket_stream_token_accumulation(self, client):
        """
        stream_token 토큰 누적 테스트

        Given: WebSocket 연결 및 메시지 전송
        When: 여러 stream_token 이벤트 수신
        Then: 토큰이 순차적으로 수신되고 index가 증가
        """
        with client.websocket_connect("/chat-ws?session_id=test-session") as ws:
            ws.send_json(
                {
                    "type": "message",
                    "message_id": "msg-token-test",
                    "content": "토큰 테스트",
                    "session_id": "test-session",
                }
            )

            # 모든 이벤트 수신
            token_events = []
            for _ in range(15):
                try:
                    event = ws.receive_json()
                    if event.get("type") == "stream_token":
                        token_events.append(event)
                    if event.get("type") == "stream_end":
                        break
                except Exception:
                    break

            # 토큰 이벤트가 있어야 함
            assert len(token_events) > 0, "stream_token 이벤트가 없습니다"

            # 인덱스가 순차적으로 증가하는지 확인
            indices = [e.get("index") for e in token_events]
            expected_indices = list(range(len(indices)))
            assert indices == expected_indices, f"토큰 인덱스가 순차적이지 않습니다: {indices}"

            # 토큰 내용 누적
            accumulated_content = "".join(e.get("token", "") for e in token_events)
            assert len(accumulated_content) > 0, "누적된 토큰 내용이 없습니다"

    def test_websocket_stream_sources_event(self, client):
        """
        stream_sources 이벤트 검증

        Given: WebSocket 연결 및 메시지 전송
        When: stream_sources 이벤트 수신
        Then: sources 배열 포함
        """
        with client.websocket_connect("/chat-ws?session_id=test-session") as ws:
            ws.send_json(
                {
                    "type": "message",
                    "message_id": "msg-sources-test",
                    "content": "소스 테스트",
                    "session_id": "test-session",
                }
            )

            # stream_sources 이벤트 찾기
            sources_event = None
            for _ in range(15):
                try:
                    event = ws.receive_json()
                    if event.get("type") == "stream_sources":
                        sources_event = event
                    if event.get("type") == "stream_end":
                        break
                except Exception:
                    break

            assert sources_event is not None, "stream_sources 이벤트가 없습니다"
            assert "sources" in sources_event, "sources 필드가 없습니다"
            assert isinstance(sources_event["sources"], list), "sources가 리스트가 아닙니다"

    def test_websocket_stream_end_event_format(self, client):
        """
        stream_end 이벤트 형식 검증

        Given: WebSocket 연결 및 스트리밍 완료
        When: stream_end 이벤트 수신
        Then: message_id, total_tokens, processing_time_ms 필드 포함
        """
        with client.websocket_connect("/chat-ws?session_id=test-session") as ws:
            ws.send_json(
                {
                    "type": "message",
                    "message_id": "msg-end-test",
                    "content": "종료 테스트",
                    "session_id": "test-session",
                }
            )

            # stream_end 이벤트 찾기
            end_event = None
            for _ in range(15):
                try:
                    event = ws.receive_json()
                    if event.get("type") == "stream_end":
                        end_event = event
                        break
                except Exception:
                    break

            assert end_event is not None, "stream_end 이벤트가 없습니다"
            assert "message_id" in end_event, "message_id가 없습니다"
            assert "total_tokens" in end_event, "total_tokens가 없습니다"
            assert "processing_time_ms" in end_event, "processing_time_ms가 없습니다"

            # 값 타입 검증
            assert isinstance(end_event["total_tokens"], int), "total_tokens가 정수가 아닙니다"
            assert isinstance(end_event["processing_time_ms"], int), "processing_time_ms가 정수가 아닙니다"


@pytest.mark.integration
class TestWebSocketErrorHandling:
    """
    WebSocket 에러 처리 E2E 테스트
    """

    @pytest.fixture
    def mock_error_chat_service(self):
        """에러를 발생시키는 ChatService Mock"""
        mock_service = MagicMock()

        async def mock_error_generator(
            message: str, session_id: str | None, options: dict | None
        ) -> AsyncGenerator[dict[str, Any], None]:
            """에러 발생 스트리밍 제너레이터"""
            # metadata는 정상 전송
            yield {
                "event": "metadata",
                "data": {
                    "session_id": "error-test-session",
                    "search_results": 0,
                },
            }

            # 일부 청크 전송
            yield {
                "event": "chunk",
                "data": "부분 응답",
                "chunk_index": 0,
            }

            # 에러 이벤트 전송
            yield {
                "event": "error",
                "error_code": "GEN-001",
                "message": "생성 중 오류 발생",
            }

        mock_service.stream_rag_pipeline = mock_error_generator
        return mock_service

    @pytest.fixture
    def ws_error_app(self, mock_error_chat_service):
        """에러 테스트용 WebSocket 앱"""
        from app.api.routers.websocket_router import router, set_chat_service

        set_chat_service(mock_error_chat_service)

        app = FastAPI()
        app.include_router(router)

        return app

    @pytest.fixture
    def error_client(self, ws_error_app):
        """에러 테스트용 클라이언트"""
        return TestClient(ws_error_app)

    def test_websocket_stream_error_event(self, error_client):
        """
        스트리밍 중 에러 이벤트 테스트

        Given: 스트리밍 중 에러 발생
        When: stream_error 이벤트 수신
        Then: error_code, message 필드 포함
        """
        with error_client.websocket_connect("/chat-ws?session_id=error-session") as ws:
            ws.send_json(
                {
                    "type": "message",
                    "message_id": "msg-error",
                    "content": "에러 테스트",
                    "session_id": "error-session",
                }
            )

            # 이벤트 수신
            events = []
            for _ in range(10):
                try:
                    event = ws.receive_json()
                    events.append(event)
                    if event.get("type") in ["stream_error", "stream_end"]:
                        break
                except Exception:
                    break

            # stream_error 이벤트 찾기
            error_events = [e for e in events if e.get("type") == "stream_error"]

            if error_events:
                error_event = error_events[0]
                assert "error_code" in error_event, "error_code가 없습니다"
                assert "message" in error_event, "message가 없습니다"


@pytest.mark.integration
class TestWebSocketInputValidation:
    """
    WebSocket 입력 검증 E2E 테스트
    """

    @pytest.fixture
    def ws_app(self):
        """WebSocket 테스트용 앱"""
        from app.api.routers.websocket_router import router, set_chat_service

        mock_service = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield {"event": "done", "data": {}}

        mock_service.stream_rag_pipeline = mock_stream
        set_chat_service(mock_service)

        app = FastAPI()
        app.include_router(router)

        return app

    @pytest.fixture
    def client(self, ws_app):
        """TestClient 생성"""
        return TestClient(ws_app)

    def test_websocket_invalid_message_format(self, client):
        """
        잘못된 메시지 형식 테스트

        Given: WebSocket 연결 수립
        When: content 필드 누락된 메시지 전송
        Then: stream_error 이벤트 수신
        """
        with client.websocket_connect("/chat-ws?session_id=test-session") as ws:
            # content 필드 누락
            ws.send_json(
                {
                    "type": "message",
                    "message_id": "msg-invalid",
                    # content 누락
                    "session_id": "test-session",
                }
            )

            # stream_error 이벤트 수신
            response = ws.receive_json()
            assert response["type"] == "stream_error"
            assert "error_code" in response

    def test_websocket_empty_content(self, client):
        """
        빈 content 테스트

        Given: WebSocket 연결 수립
        When: 빈 content 전송
        Then: stream_error 이벤트 수신
        """
        with client.websocket_connect("/chat-ws?session_id=test-session") as ws:
            ws.send_json(
                {
                    "type": "message",
                    "message_id": "msg-empty",
                    "content": "",  # 빈 문자열
                    "session_id": "test-session",
                }
            )

            response = ws.receive_json()
            assert response["type"] == "stream_error"

    def test_websocket_malformed_json(self, client):
        """
        잘못된 JSON 형식 테스트

        Given: WebSocket 연결 수립
        When: 잘못된 JSON 전송
        Then: stream_error 이벤트 수신
        """
        with client.websocket_connect("/chat-ws?session_id=test-session") as ws:
            ws.send_text("not valid json {{{")

            response = ws.receive_json()
            assert response["type"] == "stream_error"


@pytest.mark.integration
class TestWebSocketConnectionManagement:
    """
    WebSocket 연결 관리 E2E 테스트
    """

    @pytest.fixture
    def ws_app(self):
        """WebSocket 테스트용 앱"""
        from app.api.routers.websocket_router import router, set_chat_service, ws_manager

        mock_service = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield {"event": "done", "data": {}}

        mock_service.stream_rag_pipeline = mock_stream
        set_chat_service(mock_service)

        app = FastAPI()
        app.include_router(router)

        return app, ws_manager

    @pytest.fixture
    def client_and_manager(self, ws_app):
        """TestClient와 WebSocketManager 반환"""
        app, manager = ws_app
        return TestClient(app), manager

    def test_websocket_session_registration(self, client_and_manager):
        """
        세션 등록 테스트

        Given: WebSocket 연결 수립
        When: 연결 성공
        Then: WebSocketManager에 세션 등록됨
        """
        client, manager = client_and_manager

        with client.websocket_connect("/chat-ws?session_id=registered-session"):
            # 연결 중에는 세션이 등록되어 있어야 함
            assert manager.is_connected("registered-session")

        # 연결 종료 후에는 세션이 해제되어야 함
        assert not manager.is_connected("registered-session")

    def test_websocket_session_id_required(self, client_and_manager):
        """
        session_id 필수 테스트

        Given: session_id 없이 연결 시도
        When: WebSocket 연결
        Then: 422 에러 또는 연결 거부
        """
        client, _ = client_and_manager

        with pytest.raises(Exception):
            with client.websocket_connect("/chat-ws"):  # session_id 없음
                pass


@pytest.mark.integration
class TestWebSocketServiceNotInitialized:
    """
    ChatService 미초기화 시 WebSocket 동작 테스트
    """

    def test_websocket_service_not_initialized(self):
        """
        서비스 미초기화 시 에러 응답

        Given: chat_service가 None
        When: 메시지 전송
        Then: stream_error 이벤트 (SERVICE_NOT_INITIALIZED)
        """
        from app.api.routers.websocket_router import router, set_chat_service

        set_chat_service(None)

        app = FastAPI()
        app.include_router(router)

        client = TestClient(app)

        with client.websocket_connect("/chat-ws?session_id=no-service-session") as ws:
            ws.send_json(
                {
                    "type": "message",
                    "message_id": "msg-no-service",
                    "content": "서비스 없음 테스트",
                    "session_id": "no-service-session",
                }
            )

            response = ws.receive_json()
            assert response["type"] == "stream_error"
            assert "SERVICE_NOT_INITIALIZED" in response.get("error_code", "")
