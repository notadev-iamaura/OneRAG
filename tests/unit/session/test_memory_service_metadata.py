from unittest.mock import AsyncMock

import pytest

from app.modules.core.session.services.memory_service import MemoryService


@pytest.mark.asyncio
async def test_add_conversation_saves_current_metadata() -> None:
    service = MemoryService(max_exchanges=2)
    service._save_message_to_mongodb = AsyncMock()
    service.create_memory("session-1")
    session = {"messages_metadata": [], "topics": []}

    metadata = {"timestamp": 100.0, "tokens_used": 7, "processing_time": 0.3}

    await service.add_conversation(
        "session-1",
        session,
        "질문",
        "답변",
        metadata,
    )

    service._save_message_to_mongodb.assert_awaited_once()
    assert service._save_message_to_mongodb.call_args.kwargs["metadata"] == metadata


@pytest.mark.asyncio
async def test_window_trim_keeps_metadata_aligned_with_messages() -> None:
    service = MemoryService(max_exchanges=2)
    service._save_message_to_mongodb = AsyncMock()
    service.create_memory("session-1")
    session = {"messages_metadata": [], "topics": []}

    for index in range(3):
        await service.add_conversation(
            "session-1",
            session,
            f"질문 {index}",
            f"답변 {index}",
            {
                "timestamp": float(100 + index),
                "tokens_used": index,
                "processing_time": float(index),
            },
        )

    history = await service.get_chat_history("session-1", session)
    assistant_messages = [
        message for message in history["messages"] if message["type"] == "assistant"
    ]

    # ✅ #13 회귀: messages_metadata는 윈도우(교환 단위)에 맞춰 trim되어 무한 증가하지 않는다.
    assert len(session["messages_metadata"]) == 2
    assert [message["content"] for message in assistant_messages] == ["답변 1", "답변 2"]
    assert [message["tokens_used"] for message in assistant_messages] == [1, 2]


@pytest.mark.asyncio
async def test_mixed_metadata_turns_stay_aligned() -> None:
    """metadata가 없는 턴이 섞여도 각 메시지에 자기 턴의 메타데이터가 매핑된다(#8)."""
    service = MemoryService(max_exchanges=10)  # trim이 일어나지 않도록 충분히 크게
    service._save_message_to_mongodb = AsyncMock()
    service.create_memory("session-1")
    session = {"messages_metadata": [], "topics": []}

    # 턴0: metadata 있음, 턴1: metadata 없음(None), 턴2: metadata 있음
    await service.add_conversation(
        "session-1", session, "q0", "a0", {"timestamp": 100.0, "tokens_used": 10}
    )
    await service.add_conversation("session-1", session, "q1", "a1", None)
    await service.add_conversation(
        "session-1", session, "q2", "a2", {"timestamp": 102.0, "tokens_used": 30}
    )

    # 교환과 metadata가 1:1로 유지된다.
    assert len(session["messages_metadata"]) == 3

    history = await service.get_chat_history("session-1", session)
    assistant_messages = [m for m in history["messages"] if m["type"] == "assistant"]

    assert [m["content"] for m in assistant_messages] == ["a0", "a1", "a2"]
    # 턴1(placeholder)은 0, 턴0/턴2는 자기 토큰을 그대로 보존(엉뚱한 턴으로 새지 않음).
    assert [m["tokens_used"] for m in assistant_messages] == [10, 0, 30]


@pytest.mark.asyncio
async def test_messages_metadata_is_bounded() -> None:
    """긴 세션에서도 messages_metadata가 윈도우 크기를 넘지 않는다(#13)."""
    service = MemoryService(max_exchanges=2)
    service._save_message_to_mongodb = AsyncMock()
    service.create_memory("session-1")
    session = {"messages_metadata": [], "topics": []}

    for index in range(8):
        await service.add_conversation(
            "session-1", session, f"q{index}", f"a{index}", {"tokens_used": index}
        )
        assert len(session["messages_metadata"]) <= service.max_exchanges

    assert len(session["messages_metadata"]) == service.max_exchanges


@pytest.mark.asyncio
async def test_rollback_pops_placeholder_on_save_failure() -> None:
    """MongoDB 저장 실패 시 방금 추가한 metadata/메시지가 롤백된다(metadata=None 포함)."""
    service = MemoryService(max_exchanges=10)
    service._save_message_to_mongodb = AsyncMock()
    service.create_memory("session-1")
    session = {"messages_metadata": [], "topics": []}

    # 첫 턴은 성공적으로 저장
    await service.add_conversation("session-1", session, "q0", "a0", {"tokens_used": 1})
    meta_len_before = len(session["messages_metadata"])
    msg_len_before = len(service.memories["session-1"].messages)

    # 두 번째 턴은 저장 실패 → 롤백되어야 함 (metadata=None placeholder 경로)
    service._save_message_to_mongodb = AsyncMock(side_effect=RuntimeError("mongo down"))
    with pytest.raises(RuntimeError):
        await service.add_conversation("session-1", session, "q1", "a1", None)

    assert len(session["messages_metadata"]) == meta_len_before
    assert len(service.memories["session-1"].messages) == msg_len_before
