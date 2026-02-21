"""
Evaluations API 인증 테스트

TDD 방식: 먼저 테스트 작성 후 인증 구현
Evaluations API 엔드포인트에 X-API-Key 인증이 적용되었는지 검증합니다.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


class TestEvaluationsRouterAuth:
    """Evaluations 라우터에 인증 의존성이 적용되었는지 검증"""

    def test_evaluations_router_has_auth_dependency(self):
        """라우터에 get_api_key 의존성이 설정되어 있는지 확인"""
        from app.api.evaluations import router

        # 라우터 레벨 dependencies 확인
        dependency_callables = [dep.dependency for dep in router.dependencies]

        from app.lib.auth import get_api_key

        assert get_api_key in dependency_callables, (
            "Evaluations 라우터에 get_api_key 의존성이 없습니다. "
            "router = APIRouter(dependencies=[Depends(get_api_key)]) 형식으로 설정해야 합니다."
        )

    def test_evaluations_router_matches_admin_auth_pattern(self):
        """다른 보호된 라우터(admin)와 동일한 인증 패턴을 사용하는지 확인"""
        from app.api.evaluations import router as eval_router
        from app.api.routers.admin_router import router as admin_router

        # 두 라우터 모두 동일한 인증 의존성을 가져야 함
        eval_deps = {dep.dependency for dep in eval_router.dependencies}
        admin_deps = {dep.dependency for dep in admin_router.dependencies}

        from app.lib.auth import get_api_key

        assert get_api_key in eval_deps, "Evaluations 라우터에 get_api_key 의존성 필요"
        assert get_api_key in admin_deps, "Admin 라우터에 get_api_key 의존성 필요"


class TestEvaluationsEndpointAuth:
    """Evaluations API 엔드포인트에 인증이 실제 동작하는지 검증"""

    @pytest.fixture
    def mock_evaluation_module(self):
        """평가 모듈 Mock 생성"""
        mock = MagicMock()
        mock.create_evaluation = AsyncMock()
        mock.get_evaluation = AsyncMock(return_value=None)
        mock.get_session_evaluations = AsyncMock(return_value=[])
        mock.get_statistics = AsyncMock()
        mock.export_evaluations = AsyncMock(return_value="[]")
        return mock

    @pytest.fixture
    def app_with_auth(self, mock_evaluation_module):
        """인증이 활성화된 테스트 앱 생성"""
        from app.api.evaluations import init_evaluation_router, router

        init_evaluation_router(mock_evaluation_module)

        app = FastAPI()
        app.include_router(router, prefix="/api/evaluations")
        return app

    @pytest.fixture
    def client(self, app_with_auth):
        """테스트 클라이언트"""
        return TestClient(app_with_auth, raise_server_exceptions=False)

    @pytest.fixture(autouse=True)
    def set_api_key(self):
        """테스트용 API Key 설정"""
        with patch.dict(os.environ, {"FASTAPI_AUTH_KEY": "test-api-key-12345"}):
            # auth 모듈의 싱글톤 인스턴스 리셋
            import app.lib.auth as auth_module

            auth_module._auth_instance = None
            yield
            auth_module._auth_instance = None

    def test_health_endpoint_requires_auth(self, client):
        """GET /api/evaluations/health - 인증 없이 접근 시 401"""
        response = client.get("/api/evaluations/health")
        assert response.status_code == 401, (
            f"/health 엔드포인트가 인증 없이 접근 가능합니다. 실제: {response.status_code}"
        )

    def test_create_evaluation_requires_auth(self, client):
        """POST /api/evaluations - 인증 없이 접근 시 401"""
        response = client.post(
            "/api/evaluations",
            json={
                "session_id": "test",
                "message_id": "msg-1",
                "query": "테스트",
                "response": "응답",
                "overall_score": 4,
            },
        )
        assert response.status_code == 401, (
            f"POST / 엔드포인트가 인증 없이 접근 가능합니다. 실제: {response.status_code}"
        )

    def test_get_evaluation_requires_auth(self, client):
        """GET /api/evaluations/{id} - 인증 없이 접근 시 401"""
        response = client.get("/api/evaluations/test-id-123")
        assert response.status_code == 401

    def test_stats_endpoint_requires_auth(self, client):
        """GET /api/evaluations/stats/summary - 인증 없이 접근 시 401"""
        response = client.get("/api/evaluations/stats/summary")
        assert response.status_code == 401

    def test_export_endpoint_requires_auth(self, client):
        """GET /api/evaluations/export/json - 인증 없이 접근 시 401"""
        response = client.get("/api/evaluations/export/json")
        assert response.status_code == 401

    def test_batch_endpoint_requires_auth(self, client):
        """POST /api/evaluations/batch - 인증 없이 접근 시 401"""
        response = client.post("/api/evaluations/batch", json=[])
        assert response.status_code == 401

    def test_delete_endpoint_requires_auth(self, client):
        """DELETE /api/evaluations/{id} - 인증 없이 접근 시 401"""
        response = client.delete("/api/evaluations/test-id-123")
        assert response.status_code == 401

    def test_endpoint_accessible_with_valid_api_key(self, client, mock_evaluation_module):
        """유효한 API Key로 접근 시 정상 동작"""
        mock_evaluation_module.get_evaluation = AsyncMock(return_value=None)
        response = client.get(
            "/api/evaluations/test-id",
            headers={"X-API-Key": "test-api-key-12345"},
        )
        # 404 (평가 없음)이 반환되면 인증은 통과한 것
        assert response.status_code == 404, (
            f"유효한 API Key로 접근 시 인증을 통과해야 합니다. 실제: {response.status_code}"
        )
