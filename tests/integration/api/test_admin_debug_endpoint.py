"""
Admin 디버깅 API 통합 테스트

Task 5: 디버깅 API - Admin 엔드포인트 테스트
"""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.api.routers.admin_router import set_session_module
from app.lib.auth import get_api_key, get_api_key_auth
from main import app


@pytest.fixture
def mock_admin_auth(monkeypatch):
    """테스트용 관리자 인증 설정"""
    test_key = "admin-test-secret"

    # 미들웨어가 참조하는 싱글톤 인스턴스의 키를 강제로 설정
    auth = get_api_key_auth()
    original_key = auth.api_key
    auth.api_key = test_key

    # 라우터의 Depends(get_api_key) 오버라이드
    async def override_get_api_key():
        return test_key

    app.dependency_overrides[get_api_key] = override_get_api_key

    yield test_key

    # 원상 복구
    auth.api_key = original_key
    app.dependency_overrides.clear()


@pytest.fixture
def mock_session_module():
    """테스트용 세션 모듈 Mock"""
    mock_module = AsyncMock()
    # get_debug_trace가 None을 반환하여 404 유도
    mock_module.get_debug_trace = AsyncMock(return_value=None)

    # 세션 모듈 주입
    set_session_module(mock_module)

    yield mock_module

    # 원상 복구
    set_session_module(None)


@pytest.mark.integration
class TestAdminDebugEndpoint:
    """Admin 디버깅 API 통합 테스트"""

    @pytest.mark.asyncio
    async def test_get_debug_trace_not_found(self, mock_admin_auth, mock_session_module):
        """
        존재하지 않는 메시지 조회

        Given: 존재하지 않는 message_id, 유효한 API 키, 세션 모듈 주입됨
        When: GET /api/admin/debug/...
        Then: 404 Not Found
        """
        async with AsyncClient(app=app, base_url="http://test") as ac:
            response = await ac.get(
                "/api/admin/debug/session/invalid-session/messages/invalid-msg",
                headers={"X-API-Key": mock_admin_auth},
            )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_debug_trace_unauthorized(self):
        """
        인증 실패 - 잘못된 API 키

        Given: 잘못된 API 키
        When: GET /api/admin/debug/...
        Then: 401 Unauthorized
        """
        # API 키를 설정하여 인증 미들웨어 활성화
        auth = get_api_key_auth()
        original_key = auth.api_key
        auth.api_key = "correct-secret-key"

        try:
            async with AsyncClient(app=app, base_url="http://test") as ac:
                response = await ac.get(
                    "/api/admin/debug/session/test-session/messages/msg-123",
                    headers={"X-API-Key": "wrong-key"},
                )

            assert response.status_code == 401
        finally:
            auth.api_key = original_key

    @pytest.mark.asyncio
    async def test_get_debug_trace_no_auth_header(self):
        """
        인증 실패 - 헤더 없음

        Given: API 키 헤더 없음
        When: GET /api/admin/debug/...
        Then: 401 Unauthorized
        """
        # API 키를 설정하여 인증 미들웨어 활성화
        auth = get_api_key_auth()
        original_key = auth.api_key
        auth.api_key = "some-secret-key"

        try:
            async with AsyncClient(app=app, base_url="http://test") as ac:
                response = await ac.get(
                    "/api/admin/debug/session/test-session/messages/msg-123",
                )

            assert response.status_code == 401
        finally:
            auth.api_key = original_key
