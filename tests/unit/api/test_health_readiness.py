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
