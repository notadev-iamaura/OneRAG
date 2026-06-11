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
from starlette.websockets import WebSocketDisconnect

from app.api.routers import websocket_router
from app.api.routers.websocket_router import router, set_chat_service, ws_manager
from app.lib.auth import APIKeyAuth, create_websocket_session_token


@pytest.fixture(autouse=True)
def _isolate_ws_auth_singleton(monkeypatch):
    """전역 auth 싱글톤/환경 오염으로부터 WebSocket 테스트를 격리한다.

    get_api_key_auth()는 _auth_instance 싱글톤을 캐시하고 FASTAPI_AUTH_KEY를 읽는다.
    다른 테스트가 키를 남기면 무인증을 전제로 한 WebSocket 테스트가 순서에 따라 실패하므로,
    각 테스트 시작 시 기본(무인증) 상태로 리셋해 순서 독립성을 보장한다.
    인증 강제 테스트는 테스트 내부에서 _auth_instance를 직접 설정한다.
    """
    import app.lib.auth as auth_module

    monkeypatch.delenv("FASTAPI_AUTH_KEY", raising=False)
    original_instance = auth_module._auth_instance
    auth_module._auth_instance = None
    try:
        yield
    finally:
        auth_module._auth_instance = original_instance


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


class TestWebSocketServerConfirmedSessionId:
    """stream_start가 서버 확정 세션 ID를 회신하는지 테스트

    session_service는 비-UUID4 클라이언트 ID를 무통보로 새 UUID4로 교체한다.
    클라이언트가 교체된 ID를 알 수 있도록 stream_start는 파이프라인 metadata
    이벤트의 session_id(서버 확정 ID)를 담아 전송해야 한다.
    """

    @pytest.fixture
    def app(self):
        """테스트용 FastAPI 앱 생성"""
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.mark.asyncio
    async def test_stream_start_uses_server_confirmed_session_id(self, app):
        """metadata의 session_id(서버 확정 ID)가 stream_start에 담겨야 함"""
        # Given: 파이프라인이 교체된 세션 ID를 metadata로 반환
        service = MagicMock()

        async def mock_stream():
            # 서버가 비-UUID4 ID를 교체한 상황: metadata에 새 UUID 포함
            yield {
                "event": "metadata",
                "data": {"session_id": "server-replaced-uuid", "search_results": 1},
            }
            yield {"event": "chunk", "data": "답변", "chunk_index": 0}
            yield {"event": "done", "data": {"session_id": "server-replaced-uuid"}}

        service.stream_rag_pipeline = MagicMock(return_value=mock_stream())
        set_chat_service(service)

        # When: 비-UUID4 커스텀 ID로 연결 후 메시지 전송
        with TestClient(app) as client:
            with client.websocket_connect("/chat-ws?session_id=my-custom-session") as websocket:
                websocket.send_json({
                    "type": "message",
                    "message_id": "msg-001",
                    "content": "테스트",
                    "session_id": "my-custom-session",
                })

                # Then: stream_start에 서버 확정 ID가 담겨야 함 (원본 ID 아님)
                start_event = websocket.receive_json()
                assert start_event["type"] == "stream_start"
                assert start_event["session_id"] == "server-replaced-uuid", (
                    "stream_start는 metadata의 서버 확정 session_id를 회신해야 합니다"
                )

        set_chat_service(None)

    @pytest.mark.asyncio
    async def test_stream_start_fallback_to_original_id_without_metadata(self, app):
        """metadata 없이 토큰이 시작되면 원본 ID로 stream_start 폴백 전송"""
        # Given: metadata 없이 chunk부터 시작하는 비정상 파이프라인
        service = MagicMock()

        async def mock_stream():
            yield {"event": "chunk", "data": "토큰", "chunk_index": 0}
            yield {"event": "done", "data": {}}

        service.stream_rag_pipeline = MagicMock(return_value=mock_stream())
        set_chat_service(service)

        # When: 메시지 전송
        with TestClient(app) as client:
            with client.websocket_connect("/chat-ws?session_id=fallback-session") as websocket:
                websocket.send_json({
                    "type": "message",
                    "message_id": "msg-001",
                    "content": "테스트",
                    "session_id": "fallback-session",
                })

                # Then: 첫 이벤트는 원본 ID를 담은 stream_start (프로토콜 순서 보장)
                start_event = websocket.receive_json()
                assert start_event["type"] == "stream_start"
                assert start_event["session_id"] == "fallback-session"

                # 이어서 stream_token 수신
                token_event = websocket.receive_json()
                assert token_event["type"] == "stream_token"
                assert token_event["token"] == "토큰"

        set_chat_service(None)

    @pytest.mark.asyncio
    async def test_error_before_metadata_sends_only_stream_error(self, app):
        """metadata 이전 에러 경로에서는 stream_error만 전송 (stream_start 생략 허용)"""
        # Given: metadata 없이 즉시 에러를 반환하는 파이프라인
        service = MagicMock()

        async def mock_stream():
            yield {
                "event": "error",
                "error_code": "GEN-004",
                "message": "파이프라인 초기화 실패",
            }

        service.stream_rag_pipeline = MagicMock(return_value=mock_stream())
        set_chat_service(service)

        # When: 메시지 전송
        with TestClient(app) as client:
            with client.websocket_connect("/chat-ws?session_id=err-session") as websocket:
                websocket.send_json({
                    "type": "message",
                    "message_id": "msg-001",
                    "content": "테스트",
                    "session_id": "err-session",
                })

                # Then: 첫 이벤트가 stream_error (stream_start 선전송 없음)
                first_event = websocket.receive_json()
                assert first_event["type"] == "stream_error"
                assert first_event["error_code"] == "GEN-004"

        set_chat_service(None)


class TestWebSocketPayloadSessionIdAdoption:
    """후속 메시지의 payload session_id 채택 테스트 (멀티턴 핵심)

    문서(websocket-api-guide.md)와 ClientMessage 스키마는 "후속 메시지의
    session_id 필드에 stream_start로 회신된 서버 확정 ID를 사용하라"고 지시한다.
    따라서 핸들러는 연결 쿼리 파라미터가 아닌 각 메시지 payload의 session_id로
    stream_rag_pipeline을 호출해야 비-UUID4 커스텀 ID 클라이언트의
    대화 컨텍스트(멀티턴)가 유지된다.
    """

    @pytest.fixture
    def app(self):
        """테스트용 FastAPI 앱 생성"""
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.mark.asyncio
    async def test_each_message_uses_its_payload_session_id(self, app):
        """각 메시지는 자신의 payload session_id로 파이프라인을 호출해야 함

        시나리오:
        1. 비-UUID4 커스텀 ID(my-custom-session)로 연결 + 1번 메시지 전송
           → 파이프라인은 payload ID(my-custom-session)로 호출
           → 서버가 교체한 확정 ID(server-confirmed-uuid)를 stream_start로 회신
        2. 2번 메시지의 payload에 확정 ID(server-confirmed-uuid)를 담아 전송
           → 파이프라인은 쿼리 파라미터가 아닌 payload ID로 호출되어야 함
        """
        # Given: 호출된 session_id를 기록하는 Mock 파이프라인
        service = MagicMock()
        pipeline_session_ids: list[str] = []

        def fake_pipeline(message, session_id, options):
            # 호출마다 새 generator를 반환 (1회성 generator 재사용 방지)
            pipeline_session_ids.append(session_id)

            async def gen():
                yield {
                    "event": "metadata",
                    "data": {"session_id": "server-confirmed-uuid"},
                }
                yield {"event": "chunk", "data": "답변", "chunk_index": 0}
                yield {"event": "done", "data": {}}

            return gen()

        service.stream_rag_pipeline = MagicMock(side_effect=fake_pipeline)
        set_chat_service(service)

        def drain_until_stream_end(websocket):
            """stream_end까지 이벤트를 소비 (최대 10개 안전 한도)"""
            for _ in range(10):
                event = websocket.receive_json()
                if event["type"] in ("stream_end", "stream_error"):
                    return

        # When: 1번 메시지(쿼리 파라미터와 동일 ID) → 2번 메시지(서버 확정 ID)
        with TestClient(app) as client:
            with client.websocket_connect(
                "/chat-ws?session_id=my-custom-session"
            ) as websocket:
                websocket.send_json({
                    "type": "message",
                    "message_id": "msg-001",
                    "content": "첫 번째 질문",
                    "session_id": "my-custom-session",
                })
                drain_until_stream_end(websocket)

                # 문서 프로토콜대로 stream_start로 회신된 확정 ID를 payload에 사용
                websocket.send_json({
                    "type": "message",
                    "message_id": "msg-002",
                    "content": "두 번째 질문",
                    "session_id": "server-confirmed-uuid",
                })
                drain_until_stream_end(websocket)

        # Then: 각 메시지의 payload session_id로 파이프라인이 호출되어야 함
        assert pipeline_session_ids == [
            "my-custom-session",
            "server-confirmed-uuid",
        ], (
            "파이프라인은 연결 쿼리 파라미터가 아닌 각 메시지 payload의 "
            "session_id로 호출되어야 멀티턴 컨텍스트가 유지됩니다"
        )

        set_chat_service(None)


class TestWebSocketConnection:
    """WebSocket 연결 관리 테스트"""

    @pytest.fixture
    def app(self):
        """테스트용 FastAPI 앱 생성"""
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.fixture
    def require_ws_auth(self):
        """WebSocket 인증을 강제하는 테스트용 auth singleton."""
        import app.lib.auth as auth_module

        original_auth = auth_module._auth_instance
        auth_module._auth_instance = APIKeyAuth(api_key="test-ws-key")
        yield "test-ws-key"
        auth_module._auth_instance = original_auth

    def test_missing_api_key_rejects_when_auth_configured(self, app, require_ws_auth):
        """FASTAPI_AUTH_KEY가 설정된 경우 API Key 없는 WebSocket 연결 차단"""
        with TestClient(app) as client:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect("/chat-ws?session_id=test-session"):
                    pass

    def test_wrong_api_key_rejects_when_auth_configured(self, app, require_ws_auth):
        """잘못된 API Key로 WebSocket 연결 차단"""
        with TestClient(app) as client:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(
                    "/chat-ws?session_id=test-session",
                    headers={"x-api-key": "wrong-key"},
                ):
                    pass

    def test_wrong_session_token_rejects_when_auth_configured(self, app, require_ws_auth):
        """잘못된 세션 토큰으로 WebSocket 연결 차단"""
        token = create_websocket_session_token("other-session", require_ws_auth)

        with TestClient(app) as client:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(f"/chat-ws?session_id=test-session&ws_token={token}"):
                    pass

    def test_session_id_required(self, app):
        """session_id 쿼리 파라미터 필수 확인"""
        with TestClient(app) as client:
            # session_id 없이 연결 시도하면 422 에러
            with pytest.raises(Exception):  # noqa: B017
                with client.websocket_connect("/chat-ws"):
                    pass

    @pytest.mark.asyncio
    async def test_connection_registered_in_manager(self, app, require_ws_auth):
        """연결 시 WebSocketManager에 등록 확인"""
        mock_service = MagicMock()

        async def mock_stream():
            yield {"event": "done", "data": {}}

        mock_service.stream_rag_pipeline = MagicMock(return_value=mock_stream())
        set_chat_service(mock_service)
        ws_token = create_websocket_session_token("unique-session-123", require_ws_auth)

        with TestClient(app) as client:
            with client.websocket_connect(
                f"/chat-ws?session_id=unique-session-123&ws_token={ws_token}"
            ):
                # Then: 연결이 등록되어야 함
                assert ws_manager.is_connected("unique-session-123")

        # 연결 종료 후 등록 해제 확인
        assert not ws_manager.is_connected("unique-session-123")

        set_chat_service(None)
