"""
프롬프트 내용 TTL 캐시 테스트 (보류③ 개선)

목적:
    get_prompt_content가 TTL 캐시로 DB 조회를 줄이되, 쓰기(create/update/
    delete/import) 시 즉시 무효화되어 최신 프롬프트가 반영되는지 검증한다.
"""

from __future__ import annotations

import tempfile
from typing import Any

import pytest

from app.models.prompts import PromptCreate
from app.modules.core.generation.prompt_manager import PromptManager


class _FakePrompt:
    def __init__(self, content: str) -> None:
        self.content = content
        self.is_active = True


def _make_manager(cache_ttl: float = 60.0) -> PromptManager:
    # use_database=False로 JSON 모드 사용 (실DB 불필요), 임시 디렉터리에 격리
    tmp = tempfile.mkdtemp()
    return PromptManager(storage_path=tmp, use_database=False, cache_ttl=cache_ttl)


@pytest.mark.asyncio
async def test_cache_hit_skips_repeated_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """동일 name 반복 조회 시 두 번째부터는 캐시 히트로 get_prompt를 호출하지 않는다."""
    mgr = _make_manager(cache_ttl=60.0)

    calls = {"count": 0}

    async def fake_get_prompt(name: str) -> Any:
        calls["count"] += 1
        return _FakePrompt("내용 v1")

    monkeypatch.setattr(mgr, "get_prompt", fake_get_prompt)

    assert await mgr.get_prompt_content("system") == "내용 v1"
    assert await mgr.get_prompt_content("system") == "내용 v1"
    assert calls["count"] == 1, "두 번째 조회가 캐시를 안 쓰고 DB를 또 조회함"


@pytest.mark.asyncio
async def test_write_invalidates_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """쓰기(create_prompt) 후 캐시가 무효화되어 다음 조회가 최신값을 가져온다."""
    mgr = _make_manager(cache_ttl=60.0)

    state = {"content": "내용 v1"}

    async def fake_get_prompt(name: str) -> Any:
        return _FakePrompt(state["content"])

    monkeypatch.setattr(mgr, "get_prompt", fake_get_prompt)

    assert await mgr.get_prompt_content("system") == "내용 v1"  # 캐시에 v1 저장

    # 프롬프트 수정. create_prompt는 @_invalidates_content_cache로 감싸져 있어
    # 성공/실패(예외) 어느 경로든 finally에서 캐시를 무효화한다.
    state["content"] = "내용 v2"
    try:
        await mgr.create_prompt(
            PromptCreate(name="other", content="x", category="system")
        )
    except Exception:
        pass  # JSON 모드 create의 별개 이슈와 무관하게 무효화는 보장돼야 함

    assert await mgr.get_prompt_content("system") == "내용 v2", "쓰기 후 옛 캐시가 남음"


@pytest.mark.asyncio
async def test_cache_disabled_when_ttl_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """cache_ttl=0이면 캐시를 쓰지 않고 매번 조회한다."""
    mgr = _make_manager(cache_ttl=0.0)

    calls = {"count": 0}

    async def fake_get_prompt(name: str) -> Any:
        calls["count"] += 1
        return _FakePrompt("내용")

    monkeypatch.setattr(mgr, "get_prompt", fake_get_prompt)

    await mgr.get_prompt_content("system")
    await mgr.get_prompt_content("system")
    assert calls["count"] == 2, "TTL=0인데 캐시가 동작함"
