"""MemoryService ↔ ChatStore 영속화 배선 테스트 (TDD).

검증 범위:
- chat_store 미주입(기본/인메모리) 시 기존 동작 보존 + 영속화 호출 없음
- chat_store 주입 시 add_conversation이 save_exchange를 호출(원자 저장 위임)
- chat_store 저장 실패가 채팅(인메모리)을 절대 깨뜨리지 않음(graceful)
- 세션 소멸(인메모리 미스) 후 get_chat_history가 PG(chat_store)에서 복원
- PG가 비었으면 인메모리 경로로 폴백
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from app.modules.core.session.services.memory_service import MemoryService


class _FakeChatStore:
    """ChatStore Protocol을 만족하는 인메모리 Fake (테스트 전용)."""

    def __init__(self, restored: list[dict[str, Any]] | None = None) -> None:
        self.save_exchange = AsyncMock()
        self._restored = restored or []
        self.save_message = AsyncMock()

    async def get_session_messages(
        self,
        session_id: str,
        limit: int | None = None,
        company_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return list(self._restored)


# ── 기본(인메모리) 경로: chat_store 미주입 ──
async def test_in_memory_default_does_not_persist() -> None:
    """chat_store가 없으면 영속화 없이 인메모리만 사용해야 한다(0-dep 기본)."""
    service = MemoryService(max_exchanges=5)
    service._save_message_to_mongodb = AsyncMock()
    service.create_memory("s1")
    session: dict[str, Any] = {"messages_metadata": [], "topics": [], "facts": {}}

    await service.add_conversation("s1", session, "질문", "답변", {"timestamp": 1.0})

    history = await service.get_chat_history("s1", session)
    assert history["message_count"] == 2
    assert history["messages"][0]["content"] == "질문"


# ── 선택(Postgres) 경로: chat_store 주입 ──
async def test_add_conversation_persists_via_chat_store() -> None:
    chat_store = _FakeChatStore()
    service = MemoryService(max_exchanges=5, chat_store=chat_store)
    service._save_message_to_mongodb = AsyncMock()
    service.create_memory("s1")
    session: dict[str, Any] = {"messages_metadata": [], "topics": [], "facts": {}}

    await service.add_conversation(
        "s1", session, "질문", "답변", {"timestamp": 1.0, "tokens_used": 3}
    )

    chat_store.save_exchange.assert_awaited_once()
    kwargs = chat_store.save_exchange.call_args.kwargs
    assert kwargs["session_id"] == "s1"
    assert kwargs["user_message"] == "질문"
    assert kwargs["assistant_response"] == "답변"


async def test_chat_store_failure_does_not_break_chat() -> None:
    """chat_store 저장이 예외를 던져도 인메모리 채팅은 보존되어야 한다(graceful)."""
    chat_store = _FakeChatStore()
    chat_store.save_exchange = AsyncMock(side_effect=RuntimeError("DB 다운"))
    service = MemoryService(max_exchanges=5, chat_store=chat_store)
    service._save_message_to_mongodb = AsyncMock()
    service.create_memory("s1")
    session: dict[str, Any] = {"messages_metadata": [], "topics": [], "facts": {}}

    # 예외 전파되면 테스트 실패
    await service.add_conversation("s1", session, "질문", "답변", {"timestamp": 1.0})

    history = await service.get_chat_history("s1", session)
    assert history["message_count"] == 2


# ── 세션 소멸 후 복원 ──
async def test_get_chat_history_restores_from_postgres_after_session_loss() -> None:
    """인메모리 메모리가 없어도(서버 재시작/TTL 만료) PG에서 복원해야 한다."""
    restored = [
        {"role": "user", "content": "이전 질문", "metadata": {}, "created_at": "2026-01-01T00:00:00"},
        {
            "role": "assistant",
            "content": "이전 답변",
            "metadata": {"tokens_used": 7, "sources": ["doc1"]},
            "created_at": "2026-01-01T00:00:01",
        },
    ]
    chat_store = _FakeChatStore(restored=restored)
    service = MemoryService(max_exchanges=5, chat_store=chat_store)
    # 메모리를 생성하지 않음(세션 소멸 상황)
    session: dict[str, Any] = {"messages_metadata": [], "topics": [], "facts": {}}

    history = await service.get_chat_history("s-lost", session)

    assert history["message_count"] == 2
    assert history["messages"][0]["content"] == "이전 질문"
    assert history["messages"][1]["content"] == "이전 답변"
    assert history["messages"][1]["tokens_used"] == 7
    assert history["messages"][1]["sources"] == ["doc1"]


async def test_get_chat_history_falls_back_to_memory_when_pg_empty() -> None:
    """PG가 비어 있으면 인메모리 경로로 폴백해야 한다."""
    chat_store = _FakeChatStore(restored=[])
    service = MemoryService(max_exchanges=5, chat_store=chat_store)
    service._save_message_to_mongodb = AsyncMock()
    service.create_memory("s1")
    session: dict[str, Any] = {"messages_metadata": [], "topics": [], "facts": {}}
    await service.add_conversation("s1", session, "질문", "답변", {"timestamp": 1.0})

    history = await service.get_chat_history("s1", session)
    assert history["message_count"] == 2
    assert history["messages"][0]["content"] == "질문"
