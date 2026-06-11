"""
프롬프트 내용 TTL 캐시 테스트 (보류③ 개선)

목적:
    get_prompt_content가 TTL 캐시로 DB 조회를 줄이되, 쓰기(create/update/
    delete/import) 시 즉시 무효화되어 최신 프롬프트가 반영되는지 검증한다.
"""

from __future__ import annotations

import asyncio
import tempfile
from typing import Any

import pytest

from app.models.prompts import PromptCreate
from app.modules.core.generation.prompt_manager import PromptManager


class _FakePrompt:
    def __init__(self, content: str) -> None:
        self.content = content
        self.is_active = True


def _make_manager(cache_ttl: float | None = 60.0) -> PromptManager:
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


def test_cache_ttl_none_defaults_to_60() -> None:
    """cache_ttl=None 전달 시 기본 60초가 적용된다 (dependency-injector None 방어).

    DI 컨테이너는 config.prompts.cache_ttl을 그대로 넘기는데, dependency-injector는
    config에 키가 누락되면 None을 반환한다. 이때 TypeError 없이 기본 TTL로
    동작해야 한다.
    """
    mgr = _make_manager(cache_ttl=None)
    assert mgr._cache_ttl == 60.0


@pytest.mark.asyncio
async def test_read_during_write_does_not_recache_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """읽기 중 쓰기(커밋+무효화)가 끼어들어도 stale 내용을 재캐시하지 않는다.

    시나리오 (asyncio.Event로 결정적 재현):
        1) 읽기 task가 get_prompt_content("system") 진입 → DB 읽기(await)에서
           이벤트 루프에 양보 (이 시점의 DB 스냅샷은 옛 내용 v1)
        2) 양보된 사이 쓰기(create_prompt)가 커밋 + 캐시 무효화 수행 (내용 v2)
        3) 읽기 task 재개 → 옛 스냅샷 v1 반환 (결과 반환 자체는 허용)
        4) 핵심: v1이 새 TTL로 캐시에 재기록되면 최대 cache_ttl초 stale 응답
           → 캐시 미기록이어야 하고, 다음 조회는 최신 v2를 가져와야 한다
    """
    mgr = _make_manager(cache_ttl=60.0)

    db_read_started = asyncio.Event()
    write_done = asyncio.Event()
    state = {"content": "내용 v1"}

    async def fake_get_prompt(name: str) -> Any:
        # DB 스냅샷: await 진입 시점의 내용을 캡처 (쓰기 커밋 전 옛 값)
        snapshot = state["content"]
        db_read_started.set()
        await write_done.wait()  # 쓰기가 끝날 때까지 이벤트 루프에 양보
        return _FakePrompt(snapshot)

    monkeypatch.setattr(mgr, "get_prompt", fake_get_prompt)

    # 1) 읽기 task 시작 → DB await 지점에서 양보됨
    reader = asyncio.create_task(mgr.get_prompt_content("system"))
    await db_read_started.wait()

    # 2) 읽기가 양보된 사이 쓰기 발생: 커밋(내용 v2) + 캐시 무효화(finally)
    state["content"] = "내용 v2"
    try:
        await mgr.create_prompt(
            PromptCreate(name="other", content="x", category="system")
        )
    except Exception:
        pass  # JSON 모드 create의 별개 이슈와 무관하게 무효화는 보장돼야 함
    write_done.set()

    # 3) 재개된 읽기는 옛 스냅샷 v1을 반환 (이 자체는 허용되는 동작)
    assert await reader == "내용 v1"

    # 4) 핵심 검증: stale(v1)이 캐시에 재기록되면 안 되고, 다음 조회는 최신 v2
    assert "system" not in mgr._content_cache, "무효화 이후 stale 내용이 재캐시됨"
    assert await mgr.get_prompt_content("system") == "내용 v2"


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
