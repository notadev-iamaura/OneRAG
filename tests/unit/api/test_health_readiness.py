from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import health


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(health.router)
    return TestClient(app)


class HealthyRetrieval:
    async def health_check(self) -> dict[str, bool]:
        return {"retriever": True, "cache": True}


class UnhealthyRetrieval:
    async def health_check(self) -> dict[str, bool]:
        return {"retriever": False, "cache": True}


def setup_function() -> None:
    health.reset_health_state()


def teardown_function() -> None:
    health.reset_health_state()


def test_health_is_liveness_and_reports_environment(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("NODE_ENV", "production")

    response = _client().get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "OK"
    assert body["environment"] == "staging"


def test_ready_returns_503_before_startup() -> None:
    response = _client().get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_ready_allows_degraded_retrieval_when_policy_degraded(monkeypatch) -> None:
    monkeypatch.setenv("RETRIEVAL_STARTUP_POLICY", "degraded")
    health.set_startup_state(True, "ready", {"modules": "initialized"})
    health.set_retrieval_module(UnhealthyRetrieval())

    response = _client().get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_ready_blocks_unhealthy_retrieval_when_policy_required(monkeypatch) -> None:
    monkeypatch.setenv("RETRIEVAL_STARTUP_POLICY", "required")
    health.set_startup_state(True, "ready", {"modules": "initialized"})
    health.set_retrieval_module(UnhealthyRetrieval())

    response = _client().get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_ready_passes_when_required_retrieval_is_healthy(monkeypatch) -> None:
    monkeypatch.setenv("RETRIEVAL_STARTUP_POLICY", "required")
    health.set_startup_state(True, "ready", {"modules": "initialized"})
    health.set_retrieval_module(HealthyRetrieval())

    response = _client().get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


async def _async_retrieval_provider() -> HealthyRetrieval:
    """DI가 retrieval을 코루틴으로 지연 제공하는 상황을 모사."""
    return HealthyRetrieval()


def test_ready_resolves_coroutine_provided_retrieval(monkeypatch) -> None:
    # 회귀 방지: retrieval이 코루틴/Future로 제공돼도 해소 후 health_check를 호출해야 한다.
    # (해소하지 않으면 "unknown"으로 오보고되어 required 정책에서 영구 503이 된다)
    monkeypatch.setenv("RETRIEVAL_STARTUP_POLICY", "required")
    health.set_startup_state(True, "ready", {"modules": "initialized"})
    health.set_retrieval_module(_async_retrieval_provider())

    response = _client().get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["retrieval"]["status"] == "checked"


def test_ready_coroutine_provider_not_reawaited(monkeypatch) -> None:
    # 해소된 코루틴을 글로벌에 되써서 두 번째 프로브가 재-await로 실패하지 않아야 한다.
    monkeypatch.setenv("RETRIEVAL_STARTUP_POLICY", "required")
    health.set_startup_state(True, "ready", {"modules": "initialized"})
    health.set_retrieval_module(_async_retrieval_provider())

    client = _client()
    first = client.get("/ready")
    second = client.get("/ready")

    assert first.status_code == 200
    assert second.status_code == 200
    assert type(health._retrieval_module).__name__ == "HealthyRetrieval"
