"""Prompt API route registration regression tests."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_prompt_by_name_route_is_reachable(monkeypatch) -> None:
    """GET /api/prompts/by-name/{name} must not fall through to /{prompt_id}."""
    from app.api import prompts as prompts_api

    manager = _FakePromptManager()
    monkeypatch.setattr(prompts_api, "_get_container", lambda: _FakeContainer(manager))

    client = TestClient(_make_app(prompts_api.router))
    response = client.get("/api/prompts/by-name/system")

    assert response.status_code == 200
    assert response.json()["name"] == "system"
    manager.get_prompt.assert_awaited_once_with(name="system")


def test_prompt_export_route_is_reachable(monkeypatch) -> None:
    """GET /api/prompts/export/all must stay explicitly reachable."""
    from app.api import prompts as prompts_api

    manager = _FakePromptManager()
    monkeypatch.setattr(prompts_api, "_get_container", lambda: _FakeContainer(manager))

    client = TestClient(_make_app(prompts_api.router))
    response = client.get("/api/prompts/export/all")

    assert response.status_code == 200
    assert response.json() == {"prompts": []}
    manager.export_prompts.assert_awaited_once_with()


def _make_app(router) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


class _FakeContainer:
    def __init__(self, manager: "_FakePromptManager") -> None:
        self._manager = manager

    def prompt_manager(self) -> "_FakePromptManager":
        return self._manager


class _FakePromptManager:
    def __init__(self) -> None:
        self.get_prompt = AsyncMock(return_value=_prompt_payload())
        self.export_prompts = AsyncMock(return_value={"prompts": []})


def _prompt_payload() -> dict:
    now = datetime(2026, 5, 11, tzinfo=UTC)
    return {
        "id": "prompt-system",
        "name": "system",
        "content": "You are OneRAG.",
        "description": "Default system prompt",
        "is_active": True,
        "category": "system",
        "metadata": {},
        "created_at": now,
        "updated_at": now,
    }
