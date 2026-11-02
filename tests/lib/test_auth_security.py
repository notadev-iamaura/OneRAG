"""
API Key 인증 보안 테스트 (TDD)

테스트 시나리오:
1. 프로덕션 환경에서 인증 우회 차단
2. 환경 변수 조작 공격 차단
3. 개발 환경에서도 보호 경로는 fail-closed(키 미설정 시 거부)
4. 자리표시자/짧은 키는 프로덕션 기동 거부
"""

import os
from unittest.mock import AsyncMock

import pytest
from fastapi import Request


class TestProductionAuthBypass:
    """프로덕션 환경 인증 우회 차단 테스트"""

    def setup_method(self) -> None:
        """각 테스트 전에 환경 변수 초기화"""
        for key in ["ENVIRONMENT", "NODE_ENV", "WEAVIATE_URL", "FASTAPI_AUTH_KEY"]:
            os.environ.pop(key, None)

    @pytest.mark.asyncio
    async def test_block_auth_bypass_in_production(self) -> None:
        """프로덕션 환경에서 API Key 없이 접근 시도 차단"""
        from app.lib.auth import APIKeyAuth

        # 프로덕션 지표 설정
        os.environ["WEAVIATE_URL"] = "https://weaviate.example.com"

        # API Key 없이 인증 시스템 초기화 시도
        with pytest.raises(RuntimeError, match="FASTAPI_AUTH_KEY.*필수"):
            APIKeyAuth(api_key=None)

    @pytest.mark.asyncio
    async def test_explicit_environment_takes_priority_in_middleware(self) -> None:
        """명시적 ENVIRONMENT 설정이 인프라 지표보다 우선됨

        ENVIRONMENT=development가 명시적으로 설정되면, 인프라가 HTTPS를 사용하더라도
        개발 환경으로 인식됨. 이는 프로덕션 인프라에서 개발/테스트를 할 수 있게 함.
        """
        from app.lib.auth import APIKeyAuth

        # ENVIRONMENT=development를 명시적으로 설정
        os.environ["ENVIRONMENT"] = "development"
        # 인프라는 HTTPS를 사용 (프로덕션 인프라에서 개발 테스트하는 경우)
        os.environ["WEAVIATE_URL"] = "https://weaviate.example.com"

        # 명시적 ENVIRONMENT 설정이 우선되어 개발 환경으로 판단
        # API Key 없이도 초기화 가능 (경고만 출력)
        auth = APIKeyAuth(api_key=None)
        assert auth is not None

    @pytest.mark.asyncio
    async def test_unprotected_paths_pass_without_key_in_development(self) -> None:
        """개발 환경에서 키가 없어도 보호 경로가 아닌 요청(브라우저 채팅 등)은 통과"""
        from app.lib.auth import APIKeyAuth

        # 개발 환경 설정
        os.environ["ENVIRONMENT"] = "development"
        os.environ["WEAVIATE_URL"] = "http://localhost:8080"

        # API Key 없이도 초기화 가능 (경고만 출력)
        auth = APIKeyAuth(api_key=None)

        # Mock request
        request = AsyncMock(spec=Request)
        request.url.path = "/api/test"
        request.method = "GET"

        async def mock_call_next(req: Request) -> AsyncMock:
            return AsyncMock(status_code=200)

        # 보호 경로가 아니므로 정상 처리
        response = await auth.authenticate_request(request, mock_call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_protected_paths_are_fail_closed_without_key_in_development(self) -> None:
        """키가 없으면 개발 환경이라도 보호 경로(/v1)는 401이어야 한다(fail-closed).

        예전에는 개발 환경이면 인증을 통째로 건너뛰어, ENVIRONMENT만 development로
        바꾸면 보호 경로가 열리는 구조였다.
        """
        from app.lib.auth import APIKeyAuth

        os.environ["ENVIRONMENT"] = "development"
        auth = APIKeyAuth(api_key=None)

        request = AsyncMock(spec=Request)
        request.url.path = "/v1/models"
        request.method = "GET"
        request.headers = {"X-API-Key": "anything"}
        request.client = None

        async def mock_call_next(req: Request) -> AsyncMock:
            return AsyncMock(status_code=200)

        response = await auth.authenticate_request(request, mock_call_next)
        assert response.status_code == 401

    def test_get_api_key_rejects_any_header_when_server_key_missing(self) -> None:
        """서버 키가 없으면 get_api_key는 어떤 X-API-Key 값도 통과시키지 않는다."""
        from fastapi import HTTPException

        import app.lib.auth as auth_module
        from app.lib.auth import APIKeyAuth, get_api_key

        os.environ["ENVIRONMENT"] = "development"
        original = auth_module._auth_instance
        auth_module._auth_instance = APIKeyAuth(api_key=None)
        try:
            request = AsyncMock(spec=Request)
            request.url.path = "/api/admin/stats"
            request.headers = {"X-API-Key": "whatever"}
            with pytest.raises(HTTPException) as exc_info:
                get_api_key(request)
            assert exc_info.value.status_code == 401
            assert exc_info.value.detail["error"] == "서버 인증 미구성"
        finally:
            auth_module._auth_instance = original


class TestWeakApiKeyValidation:
    """자리표시자/짧은 키 검증 테스트"""

    def setup_method(self) -> None:
        for key in ["ENVIRONMENT", "NODE_ENV", "WEAVIATE_URL", "FASTAPI_AUTH_KEY"]:
            os.environ.pop(key, None)

    def test_validate_api_key_strength_flags_placeholders_and_short_keys(self) -> None:
        from app.lib.auth import validate_api_key_strength

        assert "placeholder" in validate_api_key_strength("your_api_auth_key_here")
        assert "placeholder" in validate_api_key_strength("local-dev-only-change-me")
        assert "placeholder" in validate_api_key_strength("ChangeMe")
        assert validate_api_key_strength("abc") == ["too_short"]
        assert validate_api_key_strength("a-strong-random-key-0123456789") == []
        assert validate_api_key_strength(None) == []

    def test_placeholder_key_refuses_to_start_in_production(self) -> None:
        from app.lib.auth import APIKeyAuth

        os.environ["ENVIRONMENT"] = "production"
        with pytest.raises(RuntimeError, match="안전하지 않습니다"):
            APIKeyAuth(api_key="your_api_auth_key_here")

    def test_short_key_refuses_to_start_in_production(self) -> None:
        from app.lib.auth import APIKeyAuth

        os.environ["ENVIRONMENT"] = "production"
        with pytest.raises(RuntimeError, match="too_short"):
            APIKeyAuth(api_key="short")

    def test_weak_key_only_warns_in_development(self) -> None:
        """개발 환경에서는 퀵스타트 템플릿 키로도 기동할 수 있어야 한다(경고만)."""
        from app.lib.auth import APIKeyAuth

        os.environ["ENVIRONMENT"] = "development"
        auth = APIKeyAuth(api_key="local-dev-only-change-me")
        assert auth.api_key == "local-dev-only-change-me"

    def test_strong_key_starts_in_production(self) -> None:
        from app.lib.auth import APIKeyAuth

        os.environ["ENVIRONMENT"] = "production"
        auth = APIKeyAuth(api_key="a-strong-random-key-0123456789abcdef")
        assert auth.api_key

    def test_v1_paths_are_protected_without_blocking_browser_chat_by_default(self) -> None:
        """OpenAI-compatible /v1 경로는 보호하되 브라우저 채팅 경로는 전역 차단하지 않음"""
        from app.lib.auth import APIKeyAuth

        auth = APIKeyAuth(api_key="test-key")

        assert not auth.is_protected_path("/api/chat")
        assert not auth.is_protected_path("/api/chat/session")
        assert auth.is_protected_path("/v1/models")
        assert auth.is_protected_path("/v1/chat/completions")

    @pytest.mark.asyncio
    async def test_v1_request_requires_api_key_when_configured(self) -> None:
        """API Key가 설정되면 /v1 요청도 인증 없이 통과하면 안 됨"""
        from app.lib.auth import APIKeyAuth

        auth = APIKeyAuth(api_key="test-key")

        request = AsyncMock(spec=Request)
        request.url.path = "/v1/models"
        request.method = "GET"
        request.headers = {}
        request.client = None

        async def mock_call_next(req: Request) -> AsyncMock:
            return AsyncMock(status_code=200)

        response = await auth.authenticate_request(request, mock_call_next)

        assert response.status_code == 401

    def test_websocket_session_token_is_bound_to_session_and_expiry(self) -> None:
        """WebSocket 세션 토큰은 세션 ID와 만료 시간에 묶여야 함"""
        from app.lib.auth import create_websocket_session_token, verify_websocket_session_token

        token = create_websocket_session_token(
            session_id="session-a",
            secret="test-key",
            ttl_seconds=60,
            now=1000,
        )

        assert verify_websocket_session_token("session-a", token, "test-key", now=1010)
        assert not verify_websocket_session_token("session-b", token, "test-key", now=1010)
        assert not verify_websocket_session_token("session-a", token, "wrong-key", now=1010)
        assert not verify_websocket_session_token("session-a", token, "test-key", now=1061)
