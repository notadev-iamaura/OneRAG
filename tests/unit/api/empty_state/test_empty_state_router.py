"""빈 화면(Empty State) 설정 라우터 테스트 (TDD).

검증 범위:
- GET /api/chat-empty-state: 공개(인증 불필요), 저장값 없으면 기본값 폴백
- PUT/DELETE /api/admin/chat-empty-state/{locale}: 관리자 인증(X-API-Key) 필수
- Pydantic 검증(빈 메시지/길이 초과/중복/개수)
- 지원하지 않는 로케일 400
- DB 미연결 시 upsert/delete가 503
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def set_api_key() -> Any:
    """테스트용 관리자 API Key 설정 + auth 싱글톤 리셋."""
    with patch.dict(os.environ, {"FASTAPI_AUTH_KEY": "test-admin-key"}):
        import app.lib.auth as auth_module

        auth_module._auth_instance = None
        yield
        auth_module._auth_instance = None


def _make_app(store: Any) -> FastAPI:
    from app.api.routers import empty_state_router

    empty_state_router.set_store(store)
    app = FastAPI()
    app.include_router(empty_state_router.router, prefix="/api")
    return app


def _make_store(
    *,
    get_all_return: dict[str, Any] | None = None,
    upsert_return: dict[str, Any] | None = None,
    delete_return: bool = True,
) -> Any:
    store = AsyncMock()
    store.get_all = AsyncMock(return_value=get_all_return or {})
    store.upsert = AsyncMock(return_value=upsert_return)
    store.delete = AsyncMock(return_value=delete_return)
    return store


# ── GET 공개 ──
def test_get_empty_state_public_no_auth() -> None:
    app = _make_app(_make_store())
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/chat-empty-state")
    assert resp.status_code == 200
    body = resp.json()
    # 기본 로케일(ko, en)이 기본값으로 폴백되어야 한다.
    assert "ko" in body and "en" in body
    assert "mainMessage" in body["ko"]
    assert isinstance(body["ko"]["suggestions"], list)


def test_get_empty_state_uses_stored_value_over_default() -> None:
    stored = {
        "ko": {
            "mainMessage": "저장된 메인",
            "subMessage": "저장된 보조",
            "suggestions": ["저장된 질문"],
            "updatedAt": "2026-01-01T00:00:00",
        }
    }
    app = _make_app(_make_store(get_all_return=stored))
    client = TestClient(app, raise_server_exceptions=False)

    body = client.get("/api/chat-empty-state").json()
    assert body["ko"]["mainMessage"] == "저장된 메인"


# ── PUT 인증 ──
def test_put_requires_auth() -> None:
    app = _make_app(_make_store(upsert_return={"mainMessage": "m", "subMessage": "s", "suggestions": ["q"]}))
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.put(
        "/api/admin/chat-empty-state/ko",
        json={"mainMessage": "m", "subMessage": "s", "suggestions": ["q"]},
    )
    assert resp.status_code == 401


def test_put_succeeds_with_auth() -> None:
    saved = {"mainMessage": "메인", "subMessage": "보조", "suggestions": ["q1"]}
    app = _make_app(_make_store(upsert_return=saved))
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.put(
        "/api/admin/chat-empty-state/ko",
        json={"mainMessage": "메인", "subMessage": "보조", "suggestions": ["q1"]},
        headers={"X-API-Key": "test-admin-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["mainMessage"] == "메인"


def test_put_unsupported_locale_returns_400() -> None:
    app = _make_app(_make_store(upsert_return={"mainMessage": "m", "subMessage": "s", "suggestions": ["q"]}))
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.put(
        "/api/admin/chat-empty-state/zz",
        json={"mainMessage": "m", "subMessage": "s", "suggestions": ["q"]},
        headers={"X-API-Key": "test-admin-key"},
    )
    assert resp.status_code == 400


def test_put_validation_rejects_empty_main() -> None:
    app = _make_app(_make_store())
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.put(
        "/api/admin/chat-empty-state/ko",
        json={"mainMessage": "   ", "subMessage": "s", "suggestions": ["q"]},
        headers={"X-API-Key": "test-admin-key"},
    )
    assert resp.status_code == 422


def test_put_validation_rejects_duplicate_suggestions() -> None:
    app = _make_app(_make_store())
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.put(
        "/api/admin/chat-empty-state/ko",
        json={"mainMessage": "m", "subMessage": "s", "suggestions": ["같음", "같음"]},
        headers={"X-API-Key": "test-admin-key"},
    )
    assert resp.status_code == 422


def test_put_503_when_db_unavailable() -> None:
    """store.upsert가 None(DB 미연결)이면 503."""
    app = _make_app(_make_store(upsert_return=None))
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.put(
        "/api/admin/chat-empty-state/ko",
        json={"mainMessage": "m", "subMessage": "s", "suggestions": ["q"]},
        headers={"X-API-Key": "test-admin-key"},
    )
    assert resp.status_code == 503


# ── DELETE 인증/리셋 ──
def test_delete_requires_auth() -> None:
    app = _make_app(_make_store())
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.delete("/api/admin/chat-empty-state/ko")
    assert resp.status_code == 401


def test_delete_resets_to_default_with_auth() -> None:
    app = _make_app(_make_store(delete_return=True))
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.delete(
        "/api/admin/chat-empty-state/ko", headers={"X-API-Key": "test-admin-key"}
    )
    assert resp.status_code == 200
    assert "mainMessage" in resp.json()


def test_delete_503_when_db_unavailable() -> None:
    app = _make_app(_make_store(delete_return=False))
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.delete(
        "/api/admin/chat-empty-state/ko", headers={"X-API-Key": "test-admin-key"}
    )
    assert resp.status_code == 503
