"""
Chat Router 스트리밍 엔드포인트 테스트

TDD 방식으로 작성된 /chat/stream 엔드포인트 테스트.
SSE(Server-Sent Events) 형식의 스트리밍 응답을 검증합니다.
"""

import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestStreamEndpointExists:
    """스트리밍 엔드포인트 존재 여부 테스트"""

    def test_stream_endpoint_exists(self):
        """스트리밍 엔드포인트가 라우터에 등록되어 있는지 확인"""
        from app.api.routers.chat_router import router

        routes = [route.path for route in router.routes]
        assert "/chat/stream" in routes, "'/chat/stream' 엔드포인트가 라우터에 등록되어야 함"

    def test_stream_endpoint_is_post_method(self):
        """스트리밍 엔드포인트가 POST 메서드인지 확인"""
        from app.api.routers.chat_router import router

        for route in router.routes:
            if hasattr(route, "path") and route.path == "/chat/stream":
                assert "POST" in route.methods, "'/chat/stream'은 POST 메서드여야 함"
                break


class TestStreamEndpointResponse:
    """스트리밍 엔드포인트 응답 테스트"""

    @pytest.fixture
    def mock_chat_service(self):
        """ChatService Mock 생성"""
        mock_service = MagicMock()

        async def mock_stream(*args, **kwargs):
            """Mock 스트리밍 응답 생성기"""
            yield {"event": "metadata", "data": {"session_id": "test-session", "search_results": 3}}
            yield {"event": "chunk", "data": "안녕", "chunk_index": 0}
            yield {"event": "chunk", "data": "하세요", "chunk_index": 1}
            yield {"event": "done", "data": {"session_id": "test-session", "total_chunks": 2}}

        mock_service.stream_rag_pipeline = mock_stream
        return mock_service

    @pytest.fixture
    def app_with_mock_service(self, mock_chat_service):
        """Mock ChatService가 주입된 FastAPI 앱 생성"""
        from app.api.routers.chat_router import router, set_chat_service

        app = FastAPI()
        app.include_router(router)
        set_chat_service(mock_chat_service)

        return app

    def test_stream_endpoint_returns_event_stream_content_type(self, app_with_mock_service):
        """스트리밍 엔드포인트가 text/event-stream Content-Type을 반환하는지 확인"""
        client = TestClient(app_with_mock_service)

        response = client.post(
            "/chat/stream",
            json={"message": "테스트 질문입니다"},
        )

        assert response.status_code == 200, f"응답 상태 코드가 200이어야 함. 실제: {response.status_code}"
        content_type = response.headers.get("content-type", "")
        assert content_type.startswith("text/event-stream"), (
            f"Content-Type이 text/event-stream이어야 함. 실제: {content_type}"
        )

    def test_stream_endpoint_returns_sse_format(self, app_with_mock_service):
        """스트리밍 엔드포인트가 SSE 형식으로 응답하는지 확인"""
        client = TestClient(app_with_mock_service)

        response = client.post(
            "/chat/stream",
            json={"message": "SSE 형식 테스트"},
        )

        # SSE 이벤트 파싱
        content = response.text
        events = []

        for line in content.split("\n"):
            if line.startswith("event:"):
                event_type = line.replace("event:", "").strip()
            elif line.startswith("data:"):
                data_str = line.replace("data:", "").strip()
                try:
                    data = json.loads(data_str)
                    events.append({"type": event_type, "data": data})
                except json.JSONDecodeError:
                    pass

        # 최소 하나의 이벤트가 있어야 함
        assert len(events) > 0, "SSE 이벤트가 최소 하나 이상 있어야 함"

    def test_stream_endpoint_has_cache_control_header(self, app_with_mock_service):
        """스트리밍 엔드포인트가 Cache-Control 헤더를 포함하는지 확인"""
        client = TestClient(app_with_mock_service)

        response = client.post(
            "/chat/stream",
            json={"message": "헤더 테스트"},
        )

        cache_control = response.headers.get("cache-control", "")
        assert "no-cache" in cache_control, (
            f"Cache-Control에 no-cache가 포함되어야 함. 실제: {cache_control}"
        )

    def test_stream_endpoint_has_connection_header(self, app_with_mock_service):
        """스트리밍 엔드포인트가 Connection 헤더를 포함하는지 확인"""
        client = TestClient(app_with_mock_service)

        response = client.post(
            "/chat/stream",
            json={"message": "헤더 테스트"},
        )

        connection = response.headers.get("connection", "")
        assert "keep-alive" in connection.lower(), (
            f"Connection에 keep-alive가 포함되어야 함. 실제: {connection}"
        )

    def test_stream_endpoint_has_x_accel_buffering_header(self, app_with_mock_service):
        """스트리밍 엔드포인트가 X-Accel-Buffering 헤더를 포함하는지 확인"""
        client = TestClient(app_with_mock_service)

        response = client.post(
            "/chat/stream",
            json={"message": "헤더 테스트"},
        )

        x_accel_buffering = response.headers.get("x-accel-buffering", "")
        assert x_accel_buffering == "no", (
            f"X-Accel-Buffering이 'no'여야 함. 실제: {x_accel_buffering}"
        )


class TestStreamEndpointValidation:
    """스트리밍 엔드포인트 유효성 검사 테스트"""

    @pytest.fixture
    def mock_chat_service(self):
        """ChatService Mock 생성"""
        mock_service = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield {"event": "done", "data": {"session_id": "test", "total_chunks": 0}}

        mock_service.stream_rag_pipeline = mock_stream
        return mock_service

    @pytest.fixture
    def app_with_mock_service(self, mock_chat_service):
        """Mock ChatService가 주입된 FastAPI 앱 생성"""
        from app.api.routers.chat_router import router, set_chat_service

        app = FastAPI()
        app.include_router(router)
        set_chat_service(mock_chat_service)

        return app

    def test_stream_endpoint_requires_message(self, app_with_mock_service):
        """스트리밍 엔드포인트에 message가 필수인지 확인"""
        client = TestClient(app_with_mock_service)

        response = client.post(
            "/chat/stream",
            json={},  # message 없음
        )

        # Pydantic 유효성 검사 실패 → 422
        assert response.status_code == 422, f"message 없이 요청 시 422 에러 반환해야 함. 실제: {response.status_code}"

    def test_stream_endpoint_accepts_optional_session_id(self, app_with_mock_service):
        """스트리밍 엔드포인트가 선택적 session_id를 처리하는지 확인"""
        client = TestClient(app_with_mock_service)

        # session_id 포함
        response = client.post(
            "/chat/stream",
            json={"message": "테스트", "session_id": "existing-session-123"},
        )

        assert response.status_code == 200, f"session_id 포함 요청이 성공해야 함. 실제: {response.status_code}"

    def test_stream_endpoint_accepts_options(self, app_with_mock_service):
        """스트리밍 엔드포인트가 options를 처리하는지 확인"""
        client = TestClient(app_with_mock_service)

        response = client.post(
            "/chat/stream",
            json={
                "message": "옵션 테스트",
                "options": {"temperature": 0.7, "max_tokens": 1000},
            },
        )

        assert response.status_code == 200, f"options 포함 요청이 성공해야 함. 실제: {response.status_code}"


class TestStreamEndpointErrorHandling:
    """스트리밍 엔드포인트 에러 처리 테스트"""

    @pytest.fixture
    def mock_error_chat_service(self):
        """에러 발생하는 ChatService Mock 생성"""
        mock_service = MagicMock()

        async def mock_stream_with_error(*args, **kwargs):
            yield {"event": "metadata", "data": {"session_id": "test"}}
            raise Exception("스트리밍 중 테스트 에러")

        mock_service.stream_rag_pipeline = mock_stream_with_error
        return mock_service

    @pytest.fixture
    def app_with_error_service(self, mock_error_chat_service):
        """에러 ChatService가 주입된 FastAPI 앱 생성"""
        from app.api.routers.chat_router import router, set_chat_service

        app = FastAPI()
        app.include_router(router)
        set_chat_service(mock_error_chat_service)

        return app

    def test_stream_endpoint_handles_service_error_gracefully(self, app_with_error_service):
        """스트리밍 중 에러 발생 시 에러 이벤트를 전송하는지 확인"""
        client = TestClient(app_with_error_service)

        response = client.post(
            "/chat/stream",
            json={"message": "에러 테스트"},
        )

        # 스트리밍 응답은 일단 시작되므로 200 반환
        assert response.status_code == 200

        content = response.text
        # 에러 이벤트 또는 에러 관련 내용이 포함되어야 함
        assert "error" in content.lower() or "STREAM-001" in content, (
            "에러 발생 시 error 이벤트가 전송되어야 함"
        )


class TestStreamEndpointWithoutService:
    """ChatService 미초기화 상태 테스트"""

    def test_stream_endpoint_returns_503_when_service_not_initialized(self):
        """ChatService가 초기화되지 않았을 때 503 반환하는지 확인"""
        import sys

        # 모듈 캐시에서 직접 가져오기
        # (패키지 __init__.py에서 router as chat_router로 덮어쓰기 전 모듈)
        if "app.api.routers.chat_router" in sys.modules:
            chat_router_module = sys.modules["app.api.routers.chat_router"]
        else:
            # 직접 import (패키지 __init__.py 로드 전 강제 모듈 로드)
            import importlib.util

            spec = importlib.util.find_spec("app.api.routers.chat_router")
            if spec and spec.loader:
                chat_router_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(chat_router_module)
            else:
                pytest.skip("chat_router 모듈을 찾을 수 없음")
                return

        # router 가져오기
        router = chat_router_module.router

        # 서비스를 None으로 설정
        original_service = chat_router_module.chat_service
        chat_router_module.chat_service = None

        try:
            app = FastAPI()
            app.include_router(router)
            client = TestClient(app, raise_server_exceptions=False)

            response = client.post(
                "/chat/stream",
                json={"message": "테스트"},
            )

            assert response.status_code == 503, (
                f"ChatService 미초기화 시 503 에러 반환해야 함. 실제: {response.status_code}"
            )
        finally:
            # 원래 서비스 복원
            chat_router_module.chat_service = original_service
