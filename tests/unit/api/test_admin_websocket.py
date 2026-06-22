"""관리자 WebSocket 인증 라우터 회귀 테스트."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import admin
from app.lib.auth import get_api_key_auth


@pytest.fixture()
def admin_ws_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    auth = get_api_key_auth()
    monkeypatch.setattr(auth, "api_key", "admin-secret")

    app = FastAPI()
    app.include_router(admin.websocket_router)
    return TestClient(app)


def test_admin_websocket_accepts_valid_query_api_key(admin_ws_client: TestClient) -> None:
    with admin_ws_client.websocket_connect(
        "/api/admin/ws?api_key=admin-secret"
    ) as websocket:
        websocket.send_text("ping")
        assert websocket.receive_text() == "pong"


def test_admin_websocket_rejects_missing_api_key(admin_ws_client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with admin_ws_client.websocket_connect("/api/admin/ws"):
            pass

    assert exc_info.value.code == 4001
