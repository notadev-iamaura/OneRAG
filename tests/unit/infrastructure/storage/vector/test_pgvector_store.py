"""
PgVectorStore 단위 테스트

테스트 항목:
1. 기본 초기화 및 속성 확인
2. 문서 저장 (add_documents)
3. 벡터 검색 (search)
4. 문서 삭제 (delete)
5. 에러 처리

Note:
    PostgreSQL + pgvector 확장이 필요하지 않은 단위 테스트입니다.
    Mock을 사용하여 pgvector 동작을 시뮬레이션합니다.
"""

import pytest

# pgvector 선택적 의존성 - 미설치 환경에서 스킵
psycopg = pytest.importorskip(
    "psycopg", reason="psycopg[binary]가 설치되지 않았습니다"
)

from unittest.mock import MagicMock

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_connection():
    """Mock PostgreSQL 연결"""
    conn = MagicMock()
    cursor = MagicMock()

    # execute 결과 설정
    cursor.fetchall.return_value = [
        (12345, "테스트 문서 1", 0.95, {"source": "test.pdf"}),
        (67890, "테스트 문서 2", 0.85, {"source": "manual.json"}),
    ]
    cursor.fetchone.return_value = (2,)  # row count
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)

    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    return conn


# ============================================================
# 초기화 테스트
# ============================================================


class TestPgVectorStoreInit:
    """PgVectorStore 초기화 테스트"""

    def test_basic_initialization(self, mock_connection):
        """기본 초기화 테스트"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        store = PgVectorStore(
            host="localhost",
            port=5432,
            database="vectors",
            user="postgres",
            password="password",
            table_name="documents",
            _connection=mock_connection,
        )

        assert store.host == "localhost"
        assert store.port == 5432
        assert store.database == "vectors"
        assert store.table_name == "documents"

    def test_initialization_with_dsn(self, mock_connection):
        """DSN으로 초기화 테스트"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        store = PgVectorStore(
            dsn="postgresql://postgres:password@localhost:5432/vectors",
            table_name="embeddings",
            _connection=mock_connection,
        )

        assert store.dsn is not None
        assert store.table_name == "embeddings"

    def test_default_values(self, mock_connection):
        """기본값 테스트"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        store = PgVectorStore(_connection=mock_connection)

        assert store.host == "localhost"
        assert store.port == 5432
        assert store.database == "vectors"
        assert store.table_name == "documents"


# ============================================================
# 문서 저장 테스트
# ============================================================


class TestPgVectorStoreAddDocuments:
    """문서 저장 테스트"""

    @pytest.mark.asyncio
    async def test_add_documents_success(self, mock_connection):
        """문서 저장 성공 테스트"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        store = PgVectorStore(_connection=mock_connection)

        documents = [
            {
                "id": "doc-1",
                "embedding": [0.1] * 1024,
                "content": "테스트 내용",
                "metadata": {"source": "test.pdf"},
            }
        ]

        count = await store.add_documents("documents", documents)

        assert count == 1

    @pytest.mark.asyncio
    async def test_add_documents_empty_list(self, mock_connection):
        """빈 문서 리스트 처리 테스트"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        store = PgVectorStore(_connection=mock_connection)

        count = await store.add_documents("documents", [])

        assert count == 0

    @pytest.mark.asyncio
    async def test_add_documents_auto_id(self, mock_connection):
        """ID 자동 생성 테스트"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        store = PgVectorStore(_connection=mock_connection)

        documents = [
            {
                # id 없음 - 자동 생성
                "embedding": [0.1] * 1024,
                "content": "테스트 내용",
            }
        ]

        count = await store.add_documents("documents", documents)

        assert count == 1

    @pytest.mark.asyncio
    async def test_add_documents_skip_no_embedding(self, mock_connection):
        """embedding 없는 문서 스킵 테스트"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        store = PgVectorStore(_connection=mock_connection)

        documents = [
            {"id": "doc-1", "content": "임베딩 없음"},  # embedding 누락
            {"id": "doc-2", "embedding": [0.1] * 1024, "content": "정상 문서"},
        ]

        count = await store.add_documents("documents", documents)

        # embedding이 있는 문서만 저장
        assert count == 1


# ============================================================
# 검색 테스트
# ============================================================


class TestPgVectorStoreSearch:
    """벡터 검색 테스트"""

    @pytest.mark.asyncio
    async def test_search_success(self, mock_connection):
        """검색 성공 테스트"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        store = PgVectorStore(_connection=mock_connection)

        query_vector = [0.1] * 1024
        results = await store.search("documents", query_vector, top_k=5)

        assert len(results) == 2
        assert results[0]["_score"] == 0.95
        assert results[0]["content"] == "테스트 문서 1"

    @pytest.mark.asyncio
    async def test_search_with_filters(self, mock_connection):
        """필터 적용 검색 테스트"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        store = PgVectorStore(_connection=mock_connection)

        query_vector = [0.1] * 1024
        filters = {"file_type": "PDF"}

        results = await store.search("documents", query_vector, filters=filters)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_search_updates_stats(self, mock_connection):
        """검색 통계 업데이트 테스트"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        store = PgVectorStore(_connection=mock_connection)

        await store.search("documents", [0.1] * 1024)

        assert store.stats["searches"] == 1


# ============================================================
# 삭제 테스트
# ============================================================


class TestPgVectorStoreDelete:
    """문서 삭제 테스트"""

    @pytest.mark.asyncio
    async def test_delete_by_ids(self, mock_connection):
        """ID로 삭제 테스트"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        store = PgVectorStore(_connection=mock_connection)

        count = await store.delete("documents", {"ids": ["doc-1", "doc-2"]})

        assert count == 2

    @pytest.mark.asyncio
    async def test_delete_empty_ids(self, mock_connection):
        """빈 ID 리스트 삭제 테스트"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        store = PgVectorStore(_connection=mock_connection)

        count = await store.delete("documents", {"ids": []})

        assert count == 0


# ============================================================
# 에러 처리 테스트
# ============================================================


class TestPgVectorStoreErrorHandling:
    """에러 처리 테스트"""

    @pytest.mark.asyncio
    async def test_search_error_handling(self, mock_connection):
        """검색 에러 처리 테스트"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        # 에러를 발생시키도록 설정
        cursor = mock_connection.cursor.return_value
        cursor.fetchall.side_effect = Exception("쿼리 실행 실패")

        store = PgVectorStore(_connection=mock_connection)

        with pytest.raises(RuntimeError, match="pgvector 검색 중 오류"):
            await store.search("documents", [0.1] * 1024)

    @pytest.mark.asyncio
    async def test_add_documents_error_handling(self, mock_connection):
        """저장 에러 처리 테스트"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        # 에러를 발생시키도록 설정
        cursor = mock_connection.cursor.return_value
        cursor.execute.side_effect = Exception("INSERT 실패")

        store = PgVectorStore(_connection=mock_connection)

        with pytest.raises(RuntimeError, match="pgvector 문서 저장 중 오류"):
            await store.add_documents(
                "documents",
                [{"id": "doc-1", "embedding": [0.1] * 1024, "content": "test"}],
            )


# ============================================================
# 통계 테스트
# ============================================================


class TestPgVectorStoreStats:
    """통계 테스트"""

    def test_initial_stats(self, mock_connection):
        """초기 통계 값 테스트"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        store = PgVectorStore(_connection=mock_connection)

        stats = store.stats
        assert stats["documents_added"] == 0
        assert stats["searches"] == 0
        assert stats["deletions"] == 0


# ============================================================
# 문서 관리 테스트 (fetch_objects / delete_objects)
# ============================================================


class TestPgVectorStoreDocumentManagement:
    """fetch_objects / delete_objects 테스트 (문서관리 위임 대상)"""

    @pytest.mark.asyncio
    async def test_fetch_objects_all(self, mock_connection):
        """필터 없이 전체 조회 시 WHERE 없는 SELECT가 실행되고 파리티 형태로 반환된다"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        cursor = mock_connection.cursor.return_value
        # fetch_objects는 (id, content, metadata) 3컬럼을 SELECT
        cursor.fetchall.return_value = [
            ("id-1", "본문1", {"document_id": "doc-1"}),
            ("id-2", "본문2", {"document_id": "doc-2"}),
        ]
        store = PgVectorStore(_connection=mock_connection, table_name="documents")

        results = await store.fetch_objects(collection="documents")

        # WHERE 절 없이 SELECT 실행 확인
        sql = cursor.execute.call_args.args[0]
        assert "WHERE" not in sql
        assert "SELECT id, content, metadata" in sql
        assert len(results) == 2
        assert results[0]["_id"] == "id-1"
        assert results[0]["content"] == "본문1"
        assert results[0]["document_id"] == "doc-1"

    @pytest.mark.asyncio
    async def test_fetch_objects_by_ids(self, mock_connection):
        """ids 필터는 id IN (...) 절과 파라미터로 변환된다"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        cursor = mock_connection.cursor.return_value
        cursor.fetchall.return_value = [("id-1", "a", {})]
        store = PgVectorStore(_connection=mock_connection, table_name="documents")

        await store.fetch_objects(
            collection="documents", filters={"ids": ["id-1", "id-2"]}
        )

        sql, params = cursor.execute.call_args.args
        assert "id IN (%s,%s)" in sql
        assert params == ["id-1", "id-2"]

    @pytest.mark.asyncio
    async def test_fetch_objects_metadata_filter(self, mock_connection):
        """메타데이터 필터는 metadata->>'key' = %s 조건으로 변환된다"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        cursor = mock_connection.cursor.return_value
        cursor.fetchall.return_value = []
        store = PgVectorStore(_connection=mock_connection, table_name="documents")

        await store.fetch_objects(
            collection="documents", filters={"document_id": "doc-1"}
        )

        sql, params = cursor.execute.call_args.args
        assert "metadata->>'document_id' = %s" in sql
        assert params == ["doc-1"]

    @pytest.mark.asyncio
    async def test_fetch_objects_handles_json_string_metadata(self, mock_connection):
        """metadata가 JSON 문자열로 와도 역직렬화한다"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        cursor = mock_connection.cursor.return_value
        cursor.fetchall.return_value = [
            ("id-1", "본문", '{"document_id": "doc-1"}'),
        ]
        store = PgVectorStore(_connection=mock_connection, table_name="documents")

        results = await store.fetch_objects(collection="documents")

        assert results[0]["document_id"] == "doc-1"

    @pytest.mark.asyncio
    async def test_delete_objects(self, mock_connection):
        """delete_objects는 id IN (...) DELETE를 실행하고 개수를 반환한다"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        cursor = mock_connection.cursor.return_value
        store = PgVectorStore(_connection=mock_connection, table_name="documents")

        deleted = await store.delete_objects(
            collection="documents", object_ids=["id-1", "id-2"]
        )

        assert deleted == 2
        sql = cursor.execute.call_args.args[0]
        assert "DELETE FROM documents WHERE id IN (%s,%s)" in sql

    @pytest.mark.asyncio
    async def test_delete_objects_empty(self, mock_connection):
        """빈 ID 목록은 DELETE 없이 0을 반환한다"""
        from app.infrastructure.storage.vector.pgvector_store import PgVectorStore

        cursor = mock_connection.cursor.return_value
        cursor.execute.reset_mock()
        store = PgVectorStore(_connection=mock_connection, table_name="documents")

        deleted = await store.delete_objects(collection="documents", object_ids=[])

        assert deleted == 0
        cursor.execute.assert_not_called()
