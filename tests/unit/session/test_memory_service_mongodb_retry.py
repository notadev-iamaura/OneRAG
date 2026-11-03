"""MemoryService._save_message_to_mongodb 재시도 동작 테스트.

공용 ``app.lib.retry.RetryPolicy``(선형 백오프)로 교체한 뒤에도 기존 동작이 유지되는지 검증한다:
- 일시 오류 후 성공: 재시도해 저장
- 중복 키 오류: 재시도 없이 무시(이미 저장됨)
- 타임아웃 소진: 예외 전파 없이 오류 로그만
- 일반 오류 소진: 예외 전파 없음(Fail-Safe, 채팅 중단 없음)
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.modules.core.session.services.memory_service import MemoryService


def _config(retries: int = 3, timeout: float = 1.0) -> dict[str, Any]:
    return {
        "session": {
            "save_chat_to_mongodb": True,
            "mongodb_save_retry": retries,
            "mongodb_save_timeout": timeout,
        }
    }


def _service(collection: MagicMock) -> MemoryService:
    client = MagicMock()
    client.get_chat_history_collection.return_value = collection
    return MemoryService(max_exchanges=5, mongodb_client=client)


@pytest.mark.asyncio
async def test_transient_error_is_retried_then_succeeds() -> None:
    collection = MagicMock()
    collection.insert_one.side_effect = [RuntimeError("connection reset"), None]
    service = _service(collection)

    with patch("app.lib.config_loader.load_config", return_value=_config()):
        await service._save_message_to_mongodb("s1", "질문", "답변", {"message_id": "m1"})

    assert collection.insert_one.call_count == 2


@pytest.mark.asyncio
async def test_duplicate_key_error_is_ignored_without_retry() -> None:
    collection = MagicMock()
    collection.insert_one.side_effect = RuntimeError("E11000 duplicate key error collection")
    service = _service(collection)

    with patch("app.lib.config_loader.load_config", return_value=_config()):
        await service._save_message_to_mongodb("s1", "질문", "답변", {"message_id": "m1"})

    assert collection.insert_one.call_count == 1


@pytest.mark.asyncio
async def test_persistent_error_exhausts_retries_without_raising() -> None:
    collection = MagicMock()
    collection.insert_one.side_effect = RuntimeError("still failing")
    service = _service(collection)

    with patch("app.lib.config_loader.load_config", return_value=_config(retries=2)):
        await service._save_message_to_mongodb("s1", "질문", "답변", {"message_id": "m1"})

    assert collection.insert_one.call_count == 2


@pytest.mark.asyncio
async def test_timeout_exhausts_retries_without_raising() -> None:
    collection = MagicMock()
    collection.insert_one.side_effect = lambda _doc: time.sleep(0.05)
    service = _service(collection)

    with patch(
        "app.lib.config_loader.load_config",
        return_value=_config(retries=2, timeout=0.001),
    ):
        await service._save_message_to_mongodb("s1", "질문", "답변", {"message_id": "m1"})

    assert collection.insert_one.call_count == 2
