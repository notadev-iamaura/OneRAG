"""
WebSocket 라우터 단위 테스트

TDD 방식으로 WebSocket 채팅 엔드포인트를 검증합니다.
- 엔드포인트 존재 확인
- 의존성 주입 테스트
- 메시지 흐름 테스트
- 에러 처리 테스트
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import websocket_router
from app.api.routers.websocket_router import router, set_chat_service, ws_manager


class TestWebSocketRouterEndpoint:
    """WebSocket 라우터 엔드포인트 테스트"""

    def test_chat_ws_endpoint_exists(self):
        """chat-ws 엔드포인트 존재 확인"""
        # Given: FastAPI 라우터
        routes = router.routes

        # When: WebSocket 라우트 검색
        websocket_routes = [r for r in routes if hasattr(r, "path") and r.path == "/chat-ws"]

        # Then: 엔드포인트가 존재해야 함
        assert len(websocket_routes) == 1, "/chat-ws 엔드포인트가 존재해야 합니다"

    def test_set_chat_service_injection(self):
        """ChatService 의존성 주입 테스트"""
        # Given: Mock ChatService
        mock_service = MagicMock()

        # When: 의존성 주입
        set_chat_service(mock_service)

        # Then: 전역 변수에 저장되어야 함
        assert websocket_router._chat_service is mock_service

        # Cleanup
        set_chat_service(None)

    def test_ws_manager_exists(self):
        """WebSocketManager 전역 인스턴스 존재 확인"""
        # Then: ws_manager가 존재해야 함
        assert ws_manager is not None
        assert hasattr(ws_manager, "connect")
        assert hasattr(ws_manager, "disconnect")
        assert hasattr(ws_manager, "send_json")


class TestWebSocketChatFlow:
    """WebSocket 채팅 흐름 테스트"""

    @pytest.fixture
    def app(self):
        """테스트용 FastAPI 앱 생성"""
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.fixture
    def mock_chat_service(self):
        """Mock ChatService 생성"""
        service = MagicMock()

        # stream_rag_pipeline은 async generator를 반환해야 함
        async def mock_stream():
            yield {"event": "metadata", "data": {"session_id": "test-session", "search_results": 3}}
            yield {"event": "chunk", "data": "안녕", "chunk_index": 0}
            yield {"event": "chunk", "data": "하세요", "chunk_index": 1}
            yield {"event": "done", "data": {"session_id": "test-session", "total_chunks": 2}}

        service.stream_rag_pipeline = MagicMock(return_value=mock_stream())
        return service

    @pytest.mark.asyncio
    async def test_valid_message_triggers_streaming(self, app, mock_chat_service):
        """유효한 메시지 수신 시 스트리밍 시작"""
        # Given: ChatService 주입
        set_chat_service(mock_chat_service)

        # When: WebSocket 연결 및 메시지 전송
        with TestClient(app) as client:
            with client.websocket_connect("/chat-ws?session_id=test-session") as websocket:
                # 유효한 ClientMessage 전송
                client_message = {
                    "type": "message",
                    "message_id": "msg-001",
                    "content": "안녕하세요",
                    "session_id": "test-session",
                }
                websocket.send_json(client_message)

                # Then: stream_start 이벤트 수신
                response = websocket.receive_json()
                assert response["type"] == "stream_start"
                assert response["message_id"] == "msg-001"
                assert response["session_id"] == "test-session"

                # Then: stream_token 이벤트 수신
                token1 = websocket.receive_json()
                assert token1["type"] == "stream_token"
                assert token1["token"] == "안녕"

                token2 = websocket.receive_json()
                assert token2["type"] == "stream_token"
                assert token2["token"] == "하세요"

                # Then: stream_sources 이벤트 수신
                sources = websocket.receive_json()
                assert sources["type"] == "stream_sources"

                # Then: stream_end 이벤트 수신
                end = websocket.receive_json()
                assert end["type"] == "stream_end"
                assert end["total_tokens"] >= 0

        # Cleanup
        set_chat_service(None)

    @pytest.mark.asyncio
    async def test_invalid_message_sends_error(self, app):
        """잘못된 메시지 형식 시 에러 전송"""
        # Given: ChatService 주입
        mock_service = MagicMock()
        set_chat_service(mock_service)

        # When: 잘못된 형식의 메시지 전송
        with TestClient(app) as client:
            with client.websocket_connect("/chat-ws?session_id=test-session") as websocket:
                # content 필드 누락된 잘못된 메시지
                invalid_message = {
                    "type": "message",
                    "message_id": "msg-001",
                    # content 누락
                    "session_id": "test-session",
                }
                websocket.send_json(invalid_message)

                # Then: stream_error 이벤트 수신
                response = websocket.receive_json()
                assert response["type"] == "stream_error"
                assert "error_code" in response
                assert "message" in response

        # Cleanup
        set_chat_service(None)

    @pytest.mark.asyncio
    async def test_service_not_initialized_sends_error(self, app):
        """ChatService 미초기화 시 에러 전송"""
        # Given: ChatService 미주입
        set_chat_service(None)

        # When: 메시지 전송
        with TestClient(app) as client:
            with client.websocket_connect("/chat-ws?session_id=test-session") as websocket:
                client_message = {
                    "type": "message",
                    "message_id": "msg-001",
                    "content": "안녕하세요",
                    "session_id": "test-session",
                }
                websocket.send_json(client_message)

                # Then: stream_error 이벤트 수신
                response = websocket.receive_json()
                assert response["type"] == "stream_error"
                assert "SERVICE_NOT_INITIALIZED" in response.get("error_code", "")

        # Cleanup
        set_chat_service(None)

    @pytest.mark.asyncio
    async def test_empty_content_sends_error(self, app):
        """빈 content 전송 시 에러 전송"""
        # Given: ChatService 주입
        mock_service = MagicMock()
        set_chat_service(mock_service)

        # When: 빈 content 메시지 전송
        with TestClient(app) as client:
            with client.websocket_connect("/chat-ws?session_id=test-session") as websocket:
                empty_message = {
                    "type": "message",
                    "message_id": "msg-001",
                    "content": "",  # 빈 문자열
                    "session_id": "test-session",
                }
                websocket.send_json(empty_message)

                # Then: stream_error 이벤트 수신
                response = websocket.receive_json()
                assert response["type"] == "stream_error"

        # Cleanup
        set_chat_service(None)


class TestWebSocketEventFormat:
    """WebSocket 이벤트 형식 테스트"""

    @pytest.fixture
    def app(self):
        """테스트용 FastAPI 앱 생성"""
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.fixture
    def mock_chat_service_with_sources(self):
        """소스 정보를 포함하는 Mock ChatService"""
        service = MagicMock()

        async def mock_stream():
            yield {
                "event": "metadata",
                "data": {
                    "session_id": "test-session",
                    "search_results": 2,
                    "ranked_results": 2,
                },
            }
            yield {"event": "chunk", "data": "답변입니다", "chunk_index": 0}
            yield {
                "event": "done",
                "data": {
                    "session_id": "test-session",
                    "total_chunks": 1,
                    "processing_time": 0.5,
                    "sources": [
                        {"title": "문서1", "content": "내용1"},
                        {"title": "문서2", "content": "내용2"},
                    ],
                },
            }

        service.stream_rag_pipeline = MagicMock(return_value=mock_stream())
        return service

    @pytest.mark.asyncio
    async def test_stream_start_event_format(self, app, mock_chat_service_with_sources):
        """StreamStartEvent 형식 검증"""
        set_chat_service(mock_chat_service_with_sources)

        with TestClient(app) as client:
            with client.websocket_connect("/chat-ws?session_id=test-session") as websocket:
                client_message = {
                    "type": "message",
                    "message_id": "msg-001",
                    "content": "테스트",
                    "session_id": "test-session",
                }
                websocket.send_json(client_message)

                # Then: StreamStartEvent 필드 검증
                start_event = websocket.receive_json()
                assert start_event["type"] == "stream_start"
                assert "message_id" in start_event
                assert "session_id" in start_event
                assert "timestamp" in start_event

                # timestamp가 ISO 8601 형식인지 확인
                try:
                    datetime.fromisoformat(start_event["timestamp"].replace("Z", "+00:00"))
                except ValueError:
                    pytest.fail("timestamp가 ISO 8601 형식이 아닙니다")

        set_chat_service(None)

    @pytest.mark.asyncio
    async def test_stream_token_event_format(self, app, mock_chat_service_with_sources):
        """StreamTokenEvent 형식 검증"""
        set_chat_service(mock_chat_service_with_sources)

        with TestClient(app) as client:
            with client.websocket_connect("/chat-ws?session_id=test-session") as websocket:
                client_message = {
                    "type": "message",
                    "message_id": "msg-001",
                    "content": "테스트",
                    "session_id": "test-session",
                }
                websocket.send_json(client_message)

                # stream_start 스킵
                websocket.receive_json()

                # Then: StreamTokenEvent 필드 검증
                token_event = websocket.receive_json()
                assert token_event["type"] == "stream_token"
                assert "message_id" in token_event
                assert "token" in token_event
                assert "index" in token_event
                assert isinstance(token_event["index"], int)
                assert token_event["index"] >= 0

        set_chat_service(None)

    @pytest.mark.asyncio
    async def test_stream_end_event_format(self, app, mock_chat_service_with_sources):
        """StreamEndEvent 형식 검증"""
        set_chat_service(mock_chat_service_with_sources)

        with TestClient(app) as client:
            with client.websocket_connect("/chat-ws?session_id=test-session") as websocket:
                client_message = {
                    "type": "message",
                    "message_id": "msg-001",
                    "content": "테스트",
                    "session_id": "test-session",
                }
                websocket.send_json(client_message)

                # 모든 이벤트 수신
                events = []
                for _ in range(10):  # 최대 10개 이벤트
                    try:
                        event = websocket.receive_json()
                        events.append(event)
                        if event["type"] == "stream_end":
                            break
                    except Exception:
                        break

                # Then: StreamEndEvent 찾기 및 검증
                end_events = [e for e in events if e["type"] == "stream_end"]
                assert len(end_events) == 1, "stream_end 이벤트가 정확히 1개 있어야 합니다"

                end_event = end_events[0]
                assert "message_id" in end_event
                assert "total_tokens" in end_event
                assert "processing_time_ms" in end_event
                assert isinstance(end_event["total_tokens"], int)
                assert isinstance(end_event["processing_time_ms"], int)

        set_chat_service(None)


class TestWebSocketErrorHandling:
    """WebSocket 에러 처리 테스트"""

    @pytest.fixture
    def app(self):
        """테스트용 FastAPI 앱 생성"""
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.fixture
    def mock_chat_service_with_error(self):
        """에러를 발생시키는 Mock ChatService"""
        service = MagicMock()

        async def mock_stream():
            yield {"event": "metadata", "data": {"session_id": "test-session"}}
            yield {"event": "chunk", "data": "부분 응답", "chunk_index": 0}
            # 스트리밍 중 에러 발생
            yield {
                "event": "error",
                "error_code": "GEN-001",
                "message": "생성 중 오류 발생",
            }

        service.stream_rag_pipeline = MagicMock(return_value=mock_stream())
        return service

    @pytest.mark.asyncio
    async def test_streaming_error_handling(self, app, mock_chat_service_with_error):
        """스트리밍 중 에러 발생 시 처리"""
        set_chat_service(mock_chat_service_with_error)

        with TestClient(app) as client:
            with client.websocket_connect("/chat-ws?session_id=test-session") as websocket:
                client_message = {
                    "type": "message",
                    "message_id": "msg-001",
                    "content": "테스트",
                    "session_id": "test-session",
                }
                websocket.send_json(client_message)

                # 이벤트 수신
                events = []
                for _ in range(10):
                    try:
                        event = websocket.receive_json()
                        events.append(event)
                        if event["type"] in ("stream_error", "stream_end"):
                            break
                    except Exception:
                        break

                # Then: stream_error 이벤트가 있어야 함
                error_events = [e for e in events if e["type"] == "stream_error"]
                assert len(error_events) >= 1, "에러 발생 시 stream_error 이벤트가 있어야 합니다"

                error_event = error_events[0]
                assert "error_code" in error_event
                assert "message" in error_event

        set_chat_service(None)

    @pytest.mark.asyncio
    async def test_malformed_json_handling(self, app):
        """잘못된 JSON 형식 처리"""
        mock_service = MagicMock()
        set_chat_service(mock_service)

        with TestClient(app) as client:
            with client.websocket_connect("/chat-ws?session_id=test-session") as websocket:
                # 잘못된 JSON (문자열로 전송)
                websocket.send_text("not a valid json {{{")

                # Then: stream_error 이벤트 수신
                response = websocket.receive_json()
                assert response["type"] == "stream_error"

        set_chat_service(None)


class TestWebSocketConnection:
    """WebSocket 연결 관리 테스트"""

    @pytest.fixture
    def app(self):
        """테스트용 FastAPI 앱 생성"""
        app = FastAPI()
        app.include_router(router)
        return app

    def test_session_id_required(self, app):
        """session_id 쿼리 파라미터 필수 확인"""
        with TestClient(app) as client:
            # session_id 없이 연결 시도하면 422 에러
            with pytest.raises(Exception):  # noqa: B017
                with client.websocket_connect("/chat-ws"):
                    pass

    @pytest.mark.asyncio
    async def test_connection_registered_in_manager(self, app):
        """연결 시 WebSocketManager에 등록 확인"""
        mock_service = MagicMock()

        async def mock_stream():
            yield {"event": "done", "data": {}}

        mock_service.stream_rag_pipeline = MagicMock(return_value=mock_stream())
        set_chat_service(mock_service)

        with TestClient(app) as client:
            with client.websocket_connect("/chat-ws?session_id=unique-session-123"):
                # Then: 연결이 등록되어야 함
                assert ws_manager.is_connected("unique-session-123")

        # 연결 종료 후 등록 해제 확인
        assert not ws_manager.is_connected("unique-session-123")

        set_chat_service(None)
