"""
PgVectorStore 필터 안전성 및 이벤트 루프 비블로킹 단위 테스트

테스트 항목:
1. _build_metadata_filter_clauses 순수 헬퍼 - 키 파라미터화(SQL 주입 방어)
2. search() / fetch_objects() - 실행 SQL에 필터 키가 보간되지 않음
3. fetch_objects() - 동기 psycopg 호출이 워커 스레드에서 실행됨(이벤트 루프 비블로킹)

Note:
    psycopg가 필요 없는 단위 테스트입니다.
    pgvector_store 모듈은 psycopg를 지연 로딩하므로 import 자체는 드라이버 없이 가능하며,
    _connection 파라미터로 Mock 연결을 주입해 실제 DB 없이 검증합니다.
"""

import threading
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.infrastructure.storage.vector.pgvector_store import (
    PgVectorStore,
    _build_metadata_filter_clauses,
)

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_cursor() -> MagicMock:
    """Mock PostgreSQL 커서"""
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    return cursor


@pytest.fixture
def mock_connection(mock_cursor: MagicMock) -> MagicMock:
    """Mock PostgreSQL 연결 (psycopg 불필요)"""
    conn = MagicMock()
    conn.cursor.return_value = mock_cursor
    return conn


# ============================================================
# _build_metadata_filter_clauses 순수 헬퍼 테스트
# ============================================================


class TestBuildMetadataFilterClauses:
    """필터 절 구성 헬퍼의 SQL 주입 방어 테스트"""

    def test_key_is_parameterized_not_interpolated(self) -> None:
        """필터 키가 SQL 절에 보간되지 않고 placeholder(%s)로만 등장한다"""
        clauses, params = _build_metadata_filter_clauses({"source": "test.pdf"})

        assert clauses == ["metadata->>%s = %s"]
        # 키와 값 모두 params로 전달 (키, 값 순서)
        assert params == ["source", "test.pdf"]
        # 키 문자열이 SQL 절 자체에 포함되지 않음
        assert "source" not in clauses[0]

    def test_malicious_key_not_in_sql(self) -> None:
        """SQL 주입 시도 키가 절(clause)에 포함되지 않고 파라미터로만 전달된다"""
        malicious_key = "a' = '' OR '1'='1"
        clauses, params = _build_metadata_filter_clauses({malicious_key: "x"})

        # 주입 페이로드가 SQL 텍스트에 등장하지 않음
        assert all(malicious_key not in clause for clause in clauses)
        assert clauses == ["metadata->>%s = %s"]
        # 키는 파라미터로 안전하게 전달됨
        assert params == [malicious_key, "x"]

    def test_multiple_filters_param_order(self) -> None:
        """여러 필터 시 (키, 값) 쌍 순서대로 파라미터가 구성된다"""
        clauses, params = _build_metadata_filter_clauses(
            {"source": "a.pdf", "category": "faq"}
        )

        assert clauses == ["metadata->>%s = %s", "metadata->>%s = %s"]
        assert params == ["source", "a.pdf", "category", "faq"]

    def test_exclude_keys_skipped(self) -> None:
        """exclude_keys로 지정된 키(id/ids 등)는 절 구성에서 제외된다"""
        clauses, params = _build_metadata_filter_clauses(
            {"ids": ["1", "2"], "source": "a.pdf"},
            exclude_keys=frozenset({"id", "ids"}),
        )

        assert clauses == ["metadata->>%s = %s"]
        assert params == ["source", "a.pdf"]

    def test_non_str_key_raises_value_error(self) -> None:
        """문자열이 아닌 필터 키는 ValueError를 발생시킨다 (추가 방어)"""
        with pytest.raises(ValueError, match="문자열"):
            _build_metadata_filter_clauses({123: "value"})  # type: ignore[dict-item]

    def test_value_coerced_to_str(self) -> None:
        """값은 JSONB ->> 텍스트 비교를 위해 문자열로 변환된다"""
        clauses, params = _build_metadata_filter_clauses({"page": 3})

        assert clauses == ["metadata->>%s = %s"]
        assert params == ["page", "3"]


# ============================================================
# search() 경로 - 키 파라미터화 검증
# ============================================================


class TestSearchFilterSafety:
    """search() 실행 SQL에 사용자 필터 키가 보간되지 않음을 검증"""

    @pytest.mark.asyncio
    async def test_search_filter_key_parameterized(
        self, mock_connection: MagicMock, mock_cursor: MagicMock
    ) -> None:
        """search() 필터 키가 placeholder로만 SQL에 등장하고 params에 포함된다"""
        store = PgVectorStore(_connection=mock_connection)
        malicious_key = "x' = '' OR 1=1 --"

        await store.search(
            "documents",
            query_vector=[0.1, 0.2],
            top_k=5,
            filters={malicious_key: "value", "ids": ["skip-me"]},
        )

        executed_sql, executed_params = mock_cursor.execute.call_args.args
        # 키가 SQL 텍스트에 직접 보간되지 않음
        assert malicious_key not in executed_sql
        assert "metadata->>%s = %s" in executed_sql
        # 키와 값이 파라미터로 전달됨 (벡터 파라미터 뒤)
        assert malicious_key in executed_params
        assert "value" in executed_params

    @pytest.mark.asyncio
    async def test_search_non_str_filter_key_raises(
        self, mock_connection: MagicMock
    ) -> None:
        """search() 필터에 비문자열 키가 오면 ValueError (RuntimeError로 감싸지지 않음)"""
        store = PgVectorStore(_connection=mock_connection)

        with pytest.raises(ValueError, match="문자열"):
            await store.search(
                "documents",
                query_vector=[0.1],
                filters={1: "v"},  # type: ignore[dict-item]
            )


# ============================================================
# fetch_objects() 경로 - 키 파라미터화 + 비블로킹 검증
# ============================================================


class TestFetchObjectsSafety:
    """fetch_objects() 키 파라미터화 및 이벤트 루프 비블로킹 검증"""

    @pytest.mark.asyncio
    async def test_fetch_objects_filter_key_parameterized(
        self, mock_connection: MagicMock, mock_cursor: MagicMock
    ) -> None:
        """fetch_objects() 메타데이터 필터 키가 SQL에 보간되지 않는다"""
        store = PgVectorStore(_connection=mock_connection)
        malicious_key = "k' = '' OR '1'='1"

        await store.fetch_objects(
            collection="documents",
            filters={malicious_key: "doc-1"},
        )

        executed_sql, executed_params = mock_cursor.execute.call_args.args
        assert malicious_key not in executed_sql
        assert "metadata->>%s = %s" in executed_sql
        assert list(executed_params) == [malicious_key, "doc-1"]

    @pytest.mark.asyncio
    async def test_fetch_objects_non_str_filter_key_raises(
        self, mock_connection: MagicMock
    ) -> None:
        """fetch_objects() 필터에 비문자열 키가 오면 ValueError"""
        store = PgVectorStore(_connection=mock_connection)

        with pytest.raises(ValueError, match="문자열"):
            await store.fetch_objects(
                collection="documents",
                filters={(1, 2): "v"},  # type: ignore[dict-item]
            )

    @pytest.mark.asyncio
    async def test_fetch_objects_runs_in_worker_thread(
        self, mock_connection: MagicMock, mock_cursor: MagicMock
    ) -> None:
        """동기 cursor.execute가 메인(이벤트 루프) 스레드 밖에서 실행된다"""
        calling_threads: list[threading.Thread] = []

        def _record_thread(*args: Any, **kwargs: Any) -> None:
            # 실제 호출 시점의 스레드를 기록해 to_thread 위임 여부를 검증한다
            calling_threads.append(threading.current_thread())

        mock_cursor.execute.side_effect = _record_thread
        mock_cursor.fetchall.return_value = [
            ("id-1", "본문", {"document_id": "doc-1"}),
        ]
        store = PgVectorStore(_connection=mock_connection)

        results = await store.fetch_objects(collection="documents")

        assert len(results) == 1
        assert results[0]["_id"] == "id-1"
        assert calling_threads, "cursor.execute가 호출되지 않았습니다"
        # 이벤트 루프(메인 스레드) 블로킹 방지: 워커 스레드에서 실행되어야 한다
        assert calling_threads[0] is not threading.main_thread()
