"""PostgresChatStore 단위 테스트 (TDD).

검증 범위:
- graceful no-op: DB 미연결(async_session_maker=None) 시 저장/복원이 예외 없이 동작
- save_exchange 원자성: 단일 트랜잭션에서 user+assistant 2건을 함께 add
- save_exchange graceful: DB 오류가 채팅을 실패시키지 않음(예외 전파 금지)
- get_session_messages: 시간순 정렬 복원 + 예외 시 빈 리스트 폴백
- ChatStore Protocol 구조적 만족 여부

실제 PostgreSQL 없이 동작하도록 SQLAlchemy 세션은 Fake로 대체합니다.
(aiosqlite 미설치로 인메모리 SQLite 비동기 엔진을 쓸 수 없어, 운영에서 검증된
EvaluationDataManager 테스트와 동일한 Fake 세션 패턴을 사용합니다.)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.interfaces.chat import ChatStore
from app.infrastructure.storage.chat.postgres_chat_store import PostgresChatStore


# ── Fake DB 인프라 (운영 검증된 evaluation 테스트와 동일 패턴) ──
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
    """add된 객체를 기록하고, execute는 미리 지정한 rows를 반환하는 Fake 세션."""

    def __init__(self, query_rows: list[Any] | None = None) -> None:
        self.added: list[Any] = []
        self._query_rows = query_rows or []
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, _statement: Any) -> _FakeResult:
        return _FakeResult(self._query_rows)


class _FakeSessionContext:
    def __init__(self, session: _FakeSession, raise_on_exit: Exception | None = None) -> None:
        self._session = session
        self._raise_on_exit = raise_on_exit

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if self._raise_on_exit is not None and exc_type is None:
            # 컨텍스트 종료(commit) 시점에 DB 오류가 발생하는 상황 모사
            raise self._raise_on_exit
        return False


class _FakeDbManager:
    """async_session_maker가 존재하므로 _is_ready()가 True가 되는 Fake 매니저."""

    def __init__(
        self, session: _FakeSession, raise_on_exit: Exception | None = None
    ) -> None:
        self._session = session
        self._raise_on_exit = raise_on_exit
        # _is_ready()가 True를 반환하도록 None이 아닌 값을 둔다.
        self.async_session_maker = object()

    def get_session(self) -> _FakeSessionContext:
        return _FakeSessionContext(self._session, self._raise_on_exit)


class _NotReadyDbManager:
    """DB 미연결 환경(async_session_maker=None)."""

    def __init__(self) -> None:
        self.async_session_maker = None


# ── Protocol 구조적 만족 ──
def test_postgres_chat_store_satisfies_chat_store_protocol() -> None:
    store = PostgresChatStore(db_manager=_NotReadyDbManager())
    assert isinstance(store, ChatStore)


# ── graceful no-op (DB 미연결) ──
async def test_save_exchange_no_op_when_db_unavailable() -> None:
    store = PostgresChatStore(db_manager=_NotReadyDbManager())
    # 예외 없이 조용히 건너뛰어야 한다.
    await store.save_exchange("sess-1", "질문", "답변")


async def test_get_session_messages_returns_empty_when_db_unavailable() -> None:
    store = PostgresChatStore(db_manager=_NotReadyDbManager())
    result = await store.get_session_messages("sess-1")
    assert result == []


# ── save_exchange 원자성 ──
async def test_save_exchange_adds_two_rows_in_single_transaction() -> None:
    session = _FakeSession()
    store = PostgresChatStore(db_manager=_FakeDbManager(session))

    await store.save_exchange(
        "sess-1",
        "질문",
        "답변",
        assistant_metadata={"tokens_used": 5},
    )

    # 단일 트랜잭션(get_session 1회)에서 user/assistant 2건이 함께 add 되어야 한다.
    assert len(session.added) == 2
    roles = [obj.role for obj in session.added]
    assert roles == ["user", "assistant"]
    contents = [obj.content for obj in session.added]
    assert contents == ["질문", "답변"]
    # assistant created_at이 user보다 미세하게 뒤여야 정렬이 안정적이다.
    assert session.added[1].created_at > session.added[0].created_at


async def test_save_exchange_graceful_on_db_error() -> None:
    """DB 오류가 발생해도 예외를 전파하지 않아야 한다(채팅 절대 실패 금지)."""
    session = _FakeSession()
    db = _FakeDbManager(session, raise_on_exit=RuntimeError("commit 실패"))
    store = PostgresChatStore(db_manager=db)

    # 예외가 새어나오면 테스트 실패
    await store.save_exchange("sess-1", "질문", "답변")


# ── get_session_messages 복원 ──
async def test_get_session_messages_returns_to_dict_rows() -> None:
    class _Row:
        def to_dict(self) -> dict[str, Any]:
            return {"role": "user", "content": "질문", "metadata": {}}

    session = _FakeSession(query_rows=[_Row(), _Row()])
    store = PostgresChatStore(db_manager=_FakeDbManager(session))

    rows = await store.get_session_messages("sess-1")
    assert len(rows) == 2
    assert rows[0]["content"] == "질문"


async def test_get_session_messages_graceful_on_db_error() -> None:
    """조회 중 DB 오류가 발생하면 빈 리스트로 폴백해야 한다."""

    class _BoomSession(_FakeSession):
        async def execute(self, _statement: Any) -> _FakeResult:
            raise RuntimeError("조회 실패")

    store = PostgresChatStore(db_manager=_FakeDbManager(_BoomSession()))
    result = await store.get_session_messages("sess-1")
    assert result == []


async def test_save_message_single_row() -> None:
    session = _FakeSession()
    store = PostgresChatStore(db_manager=_FakeDbManager(session))

    await store.save_message("sess-1", "user", "단건 메시지")

    assert len(session.added) == 1
    assert session.added[0].role == "user"
    assert session.added[0].content == "단건 메시지"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
