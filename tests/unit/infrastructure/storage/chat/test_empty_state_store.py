"""ChatEmptyStateSettingsStore 단위 테스트 (TDD).

검증 범위:
- 공개 조회(get_all/get): DB 미연결 시 graceful(빈 dict / None)
- 저장(upsert): DB 미연결 시 None 반환(라우터가 503), 정상 시 dict 반환
- 삭제(delete): DB 미연결 시 False, 정상 시 True
- 신규 행 생성 / 기존 행 갱신 분기
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from app.infrastructure.storage.chat.empty_state_settings_store import (
    ChatEmptyStateSettingsStore,
)


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, query_rows: list[Any] | None = None) -> None:
        self.added: list[Any] = []
        self._query_rows = query_rows or []
        self.commit = AsyncMock()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, _statement: Any) -> _FakeResult:
        return _FakeResult(self._query_rows)


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


class _FakeDbManager:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session
        self.async_session_maker = object()

    def get_session(self) -> _FakeSessionContext:
        return _FakeSessionContext(self._session)


class _NotReadyDbManager:
    def __init__(self) -> None:
        self.async_session_maker = None


# ── graceful 조회 ──
async def test_get_all_empty_when_db_unavailable() -> None:
    store = ChatEmptyStateSettingsStore(db_manager=_NotReadyDbManager())
    assert await store.get_all() == {}


async def test_get_none_when_db_unavailable() -> None:
    store = ChatEmptyStateSettingsStore(db_manager=_NotReadyDbManager())
    assert await store.get("ko") is None


# ── upsert / delete graceful 미연결 ──
async def test_upsert_returns_none_when_db_unavailable() -> None:
    store = ChatEmptyStateSettingsStore(db_manager=_NotReadyDbManager())
    result = await store.upsert("ko", "메인", "보조", ["q1"])
    assert result is None


async def test_delete_returns_false_when_db_unavailable() -> None:
    store = ChatEmptyStateSettingsStore(db_manager=_NotReadyDbManager())
    assert await store.delete("ko") is False


# ── 정상 동작 ──
async def test_upsert_creates_new_row() -> None:
    session = _FakeSession(query_rows=[])  # 기존 행 없음
    store = ChatEmptyStateSettingsStore(db_manager=_FakeDbManager(session))

    result = await store.upsert("ko", "메인", "보조", ["q1", "q2"])

    assert result == {"mainMessage": "메인", "subMessage": "보조", "suggestions": ["q1", "q2"]}
    assert len(session.added) == 1  # 신규 행 추가


async def test_upsert_updates_existing_row() -> None:
    class _Row:
        def __init__(self) -> None:
            self.main_message = "old"
            self.sub_message = "old"
            self.suggestions = ["old"]

    row = _Row()
    session = _FakeSession(query_rows=[row])  # 기존 행 존재
    store = ChatEmptyStateSettingsStore(db_manager=_FakeDbManager(session))

    result = await store.upsert("ko", "새메인", "새보조", ["new"])

    assert row.main_message == "새메인"
    assert row.sub_message == "새보조"
    assert row.suggestions == ["new"]
    assert len(session.added) == 0  # 갱신이므로 add 없음
    assert result is not None and result["mainMessage"] == "새메인"


async def test_get_all_returns_to_dict_map() -> None:
    class _Row:
        def __init__(self, locale: str) -> None:
            self.locale = locale

        def to_dict(self) -> dict[str, Any]:
            return {"mainMessage": f"m-{self.locale}", "subMessage": "s", "suggestions": []}

    session = _FakeSession(query_rows=[_Row("ko"), _Row("en")])
    store = ChatEmptyStateSettingsStore(db_manager=_FakeDbManager(session))

    result = await store.get_all()
    assert set(result.keys()) == {"ko", "en"}
    assert result["ko"]["mainMessage"] == "m-ko"


async def test_delete_returns_true_when_db_available() -> None:
    session = _FakeSession()
    store = ChatEmptyStateSettingsStore(db_manager=_FakeDbManager(session))
    assert await store.delete("ko") is True
