"""
DI 컨테이너 배선 통합 테스트 (Phase 2.2 / Phase 0.3)

목적:
    1) ingest 라우터의 Provide[] 마커가 wire()로 해소되어 500 대신 202를
       반환하는지 검증한다 (wire 미호출 시 Provide 객체가 그대로 주입되어 500).
    2) monitoring/prompts가 새 AppContainer()가 아닌 주입된 공유 컨테이너를
       사용하는지 검증한다 (비용/설정이 실행 중 파이프라인과 분리되는 것 방지).
"""

from __future__ import annotations

import pytest
from dependency_injector import providers
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.di_container import AppContainer
from app.lib.config_loader import load_config

# integration 마커: 기본 CI test 잡은 tests/integration을 ignore하므로
# 별도 P0 회귀 스텝(ci.yml) 또는 `-m integration`으로 실행된다.
pytestmark = pytest.mark.integration


class FakeConnector:
    pass


class FakeConnectorFactory:
    def create(self, cfg: dict) -> FakeConnector:
        return FakeConnector()


class FakeIngestionService:
    def __init__(self) -> None:
        self.called = False

    async def ingest_from_connector(self, connector: object, category_name: str) -> None:
        self.called = True


def test_ingest_web_wired_returns_202_not_500() -> None:
    """wire() 후 ingest API가 의존성을 정상 주입받아 202를 반환해야 한다."""
    from app.api import ingest
    from app.lib.auth import get_api_key

    container = AppContainer()
    container.config.from_dict(load_config(validate=False))
    container.connector_factory.override(providers.Object(FakeConnectorFactory()))
    container.ingestion_service.override(providers.Object(FakeIngestionService()))
    container.wire(modules=["app.api.ingest"])

    app = FastAPI()
    app.include_router(ingest.router, prefix="/api")
    app.dependency_overrides[get_api_key] = lambda: "test-key"

    try:
        client = TestClient(app)
        resp = client.post(
            "/api/ingest/web",
            json={
                "sitemap_url": "https://example.com/sitemap.xml",
                "category_name": "test",
            },
        )
        assert resp.status_code == 202, resp.text
    finally:
        container.unwire()


def test_monitoring_uses_injected_shared_container() -> None:
    """monitoring._get_container가 주입된 공유 컨테이너를 반환해야 한다."""
    from app.api import monitoring

    original = monitoring._shared_container
    try:
        sentinel = object()
        monitoring.set_container(sentinel)  # type: ignore[arg-type]
        assert monitoring._get_container() is sentinel
    finally:
        monitoring._shared_container = original


def test_prompts_uses_injected_shared_container() -> None:
    """prompts._get_container가 주입된 공유 컨테이너를 반환해야 한다."""
    from app.api import prompts

    original = prompts._shared_container
    try:
        sentinel = object()
        prompts.set_container(sentinel)  # type: ignore[arg-type]
        assert prompts._get_container() is sentinel
    finally:
        prompts._shared_container = original
