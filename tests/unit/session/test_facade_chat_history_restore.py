"""EnhancedSessionModule(facade) 채팅 히스토리 PG 복원 배선 테스트 (TDD).

기존 facade.get_chat_history는 세션 무효 시 즉시 빈 결과를 반환했다.
chat_store가 있으면 세션 소멸 후에도 PG에서 복원하도록 변경되어야 한다.
"""

from __future__ import annotations

from typing import Any

from app.modules.core.session.facade import EnhancedSessionModule
from app.modules.core.session.services.memory_service import MemoryService


class _FakeChatStore:
    def __init__(self, restored: list[dict[str, Any]]) -> None:
        self._restored = restored

    async def get_session_messages(
        self,
        session_id: str,
        limit: int | None = None,
        company_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return list(self._restored)


def _build_module(chat_store: Any | None) -> EnhancedSessionModule:
    config: dict[str, Any] = {"session": {"ttl_seconds": 3600, "max_exchanges": 5}}
    memory_service = MemoryService(max_exchanges=5, config=config, chat_store=chat_store)
    return EnhancedSessionModule(config=config, memory_service=memory_service)


async def test_facade_restores_history_for_invalid_session_when_chat_store_present() -> None:
    """세션이 무효(인메모리 미스)여도 chat_store가 있으면 PG에서 복원해야 한다."""
    restored = [
        {"role": "user", "content": "복원 질문", "metadata": {}, "created_at": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "복원 답변", "metadata": {}, "created_at": "2026-01-01T00:00:01"},
    ]
    module = _build_module(_FakeChatStore(restored))

    # create_session 호출 없이 존재하지 않는 세션 ID로 조회
    history = await module.get_chat_history("ghost-session")

    assert history["message_count"] == 2
    assert history["messages"][0]["content"] == "복원 질문"


async def test_facade_returns_empty_for_invalid_session_without_chat_store() -> None:
    """chat_store가 없으면 기존대로 빈 결과를 반환해야 한다(0-dep 기본 보존)."""
    module = _build_module(chat_store=None)

    history = await module.get_chat_history("ghost-session")

    assert history == {"messages": [], "message_count": 0}
