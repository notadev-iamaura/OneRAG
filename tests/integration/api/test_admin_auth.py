import httpx
import pytest
from httpx import AsyncClient

from app.lib.auth import get_api_key, get_api_key_auth
from main import app as fastapi_app


@pytest.fixture
def mock_admin_auth(monkeypatch):
    """테스트용 관리자 인증 설정"""
    test_key = "admin-test-secret"

    # 1. 미들웨어가 참조하는 싱글톤 인스턴스의 키를 강제로 설정
    auth = get_api_key_auth()
    original_key = auth.api_key
    auth.api_key = test_key

    # 2. 라우터의 Depends(get_api_key) 오버라이드
    async def override_get_api_key():
        return test_key

    fastapi_app.dependency_overrides[get_api_key] = override_get_api_key

    yield test_key

    # 원상 복구
    auth.api_key = original_key
    fastapi_app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_admin_status_requires_auth(monkeypatch):
    """인증 헤더가 없으면 실패해야 함"""
    # 키를 강제로 설정하여 미들웨어 활성화
    auth = get_api_key_auth()
    original_key = auth.api_key
    auth.api_key = "some-key"

    try:
        async with AsyncClient(transport=httpx.ASGITransport(app=fastapi_app), base_url="http://test") as ac:
            response = await ac.get("/api/admin/status")
            assert response.status_code == 401
    finally:
        auth.api_key = original_key

@pytest.mark.asyncio
async def test_admin_status_with_valid_auth(mock_admin_auth):
    """올바른 키를 제공하면 성공해야 함"""
    test_key = mock_admin_auth
    async with AsyncClient(transport=httpx.ASGITransport(app=fastapi_app), base_url="http://test") as ac:
        headers = {"X-API-Key": test_key}
        response = await ac.get("/api/admin/status", headers=headers)
        assert response.status_code == 200
