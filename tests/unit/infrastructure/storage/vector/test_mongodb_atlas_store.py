"""
MongoDBAtlasStore 단위 테스트

테스트 항목:
1. 기본 초기화 및 속성 확인
2. 문서 저장 (add_documents)
3. 벡터 검색 (search)
4. 문서 삭제 (delete)
5. 에러 처리

Note:
    MongoDB가 필요하지 않은 단위 테스트입니다.
    Mock을 사용하여 MongoDB Atlas 동작을 시뮬레이션합니다.
"""

import pytest

# pymongo 선택적 의존성 - 미설치 환경에서 스킵
pymongo = pytest.importorskip(
    "pymongo", reason="pymongo가 설치되지 않았습니다"
)

from unittest.mock import MagicMock

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_collection():
    """Mock MongoDB 컬렉션"""
    collection = MagicMock()

    # aggregate 결과 설정 (벡터 검색용)
    mock_cursor = MagicMock()
    mock_cursor.__iter__ = MagicMock(
        return_value=iter(
            [
                {
                    "_id": "doc-1",
                    "content": "테스트 문서 1",
                    "score": 0.95,
                    "metadata": {"source": "test.pdf"},
                },
                {
                    "_id": "doc-2",
                    "content": "테스트 문서 2",
                    "score": 0.85,
                    "metadata": {"source": "manual.json"},
                },
            ]
        )
    )
    collection.aggregate.return_value = mock_cursor

    # insert_many 결과 설정
    insert_result = MagicMock()
    insert_result.inserted_ids = ["doc-1"]
    collection.insert_many.return_value = insert_result

    # update_one 결과 설정
    collection.update_one.return_value = MagicMock(upserted_id=None)

    # delete_many 결과 설정
    delete_result = MagicMock()
    delete_result.deleted_count = 2
    collection.delete_many.return_value = delete_result

    return collection


@pytest.fixture
def mock_client(mock_collection):
    """Mock MongoDB 클라이언트"""
    client = MagicMock()
    database = MagicMock()
    database.__getitem__ = MagicMock(return_value=mock_collection)
    client.__getitem__ = MagicMock(return_value=database)
    return client


# ============================================================
# 초기화 테스트
# ============================================================


class TestMongoDBAtlasStoreInit:
    """MongoDBAtlasStore 초기화 테스트"""

    def test_basic_initialization(self, mock_client):
        """기본 초기화 테스트"""
        from app.infrastructure.storage.vector.mongodb_atlas_store import (
            MongoDBAtlasStore,
        )

        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            database_name="rag_db",
            collection_name="documents",
            _client=mock_client,
        )

        assert store.database_name == "rag_db"
        assert store.collection_name == "documents"

    def test_initialization_with_index_name(self, mock_client):
        """인덱스 이름으로 초기화 테스트"""
        from app.infrastructure.storage.vector.mongodb_atlas_store import (
            MongoDBAtlasStore,
        )

        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            database_name="rag_db",
            collection_name="embeddings",
            index_name="vector_index",
            _client=mock_client,
        )

        assert store.collection_name == "embeddings"
        assert store.index_name == "vector_index"

    def test_default_values(self, mock_client):
        """기본값 테스트"""
        from app.infrastructure.storage.vector.mongodb_atlas_store import (
            MongoDBAtlasStore,
        )

        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            _client=mock_client,
        )

        assert store.database_name == "rag_vectors"
        assert store.collection_name == "documents"
        assert store.index_name == "vector_index"


# ============================================================
# 문서 저장 테스트
# ============================================================


class TestMongoDBAtlasStoreAddDocuments:
    """문서 저장 테스트"""

    @pytest.mark.asyncio
    async def test_add_documents_success(self, mock_client, mock_collection):
        """문서 저장 성공 테스트"""
        from app.infrastructure.storage.vector.mongodb_atlas_store import (
            MongoDBAtlasStore,
        )

        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            _client=mock_client,
        )

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
    async def test_add_documents_empty_list(self, mock_client):
        """빈 문서 리스트 처리 테스트"""
        from app.infrastructure.storage.vector.mongodb_atlas_store import (
            MongoDBAtlasStore,
        )

        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            _client=mock_client,
        )

        count = await store.add_documents("documents", [])

        assert count == 0

    @pytest.mark.asyncio
    async def test_add_documents_auto_id(self, mock_client):
        """ID 자동 생성 테스트"""
        from app.infrastructure.storage.vector.mongodb_atlas_store import (
            MongoDBAtlasStore,
        )

        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            _client=mock_client,
        )

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
    async def test_add_documents_skip_no_embedding(self, mock_client):
        """embedding 없는 문서 스킵 테스트"""
        from app.infrastructure.storage.vector.mongodb_atlas_store import (
            MongoDBAtlasStore,
        )

        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            _client=mock_client,
        )

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


class TestMongoDBAtlasStoreSearch:
    """벡터 검색 테스트"""

    @pytest.mark.asyncio
    async def test_search_success(self, mock_client):
        """검색 성공 테스트"""
        from app.infrastructure.storage.vector.mongodb_atlas_store import (
            MongoDBAtlasStore,
        )

        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            _client=mock_client,
        )

        query_vector = [0.1] * 1024
        results = await store.search("documents", query_vector, top_k=5)

        assert len(results) == 2
        assert results[0]["_score"] == 0.95
        assert results[0]["content"] == "테스트 문서 1"

    @pytest.mark.asyncio
    async def test_search_with_filters(self, mock_client):
        """필터 적용 검색 테스트"""
        from app.infrastructure.storage.vector.mongodb_atlas_store import (
            MongoDBAtlasStore,
        )

        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            _client=mock_client,
        )

        query_vector = [0.1] * 1024
        filters = {"file_type": "PDF"}

        results = await store.search("documents", query_vector, filters=filters)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_search_updates_stats(self, mock_client):
        """검색 통계 업데이트 테스트"""
        from app.infrastructure.storage.vector.mongodb_atlas_store import (
            MongoDBAtlasStore,
        )

        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            _client=mock_client,
        )

        await store.search("documents", [0.1] * 1024)

        assert store.stats["searches"] == 1


# ============================================================
# 삭제 테스트
# ============================================================


class TestMongoDBAtlasStoreDelete:
    """문서 삭제 테스트"""

    @pytest.mark.asyncio
    async def test_delete_by_ids(self, mock_client):
        """ID로 삭제 테스트"""
        from app.infrastructure.storage.vector.mongodb_atlas_store import (
            MongoDBAtlasStore,
        )

        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            _client=mock_client,
        )

        count = await store.delete("documents", {"ids": ["doc-1", "doc-2"]})

        assert count == 2

    @pytest.mark.asyncio
    async def test_delete_empty_ids(self, mock_client):
        """빈 ID 리스트 삭제 테스트"""
        from app.infrastructure.storage.vector.mongodb_atlas_store import (
            MongoDBAtlasStore,
        )

        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            _client=mock_client,
        )

        count = await store.delete("documents", {"ids": []})

        assert count == 0


# ============================================================
# 에러 처리 테스트
# ============================================================


class TestMongoDBAtlasStoreErrorHandling:
    """에러 처리 테스트"""

    @pytest.mark.asyncio
    async def test_search_error_handling(self, mock_client, mock_collection):
        """검색 에러 처리 테스트"""
        from app.infrastructure.storage.vector.mongodb_atlas_store import (
            MongoDBAtlasStore,
        )

        # 에러를 발생시키도록 설정
        mock_collection.aggregate.side_effect = Exception("쿼리 실행 실패")

        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            _client=mock_client,
        )

        with pytest.raises(RuntimeError, match="MongoDB Atlas 검색 중 오류"):
            await store.search("documents", [0.1] * 1024)

    @pytest.mark.asyncio
    async def test_add_documents_error_handling(self, mock_client, mock_collection):
        """저장 에러 처리 테스트"""
        from app.infrastructure.storage.vector.mongodb_atlas_store import (
            MongoDBAtlasStore,
        )

        # 에러를 발생시키도록 설정
        mock_collection.update_one.side_effect = Exception("INSERT 실패")

        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            _client=mock_client,
        )

        with pytest.raises(RuntimeError, match="MongoDB Atlas 문서 저장 중 오류"):
            await store.add_documents(
                "documents",
                [{"id": "doc-1", "embedding": [0.1] * 1024, "content": "test"}],
            )


# ============================================================
# 통계 테스트
# ============================================================


class TestMongoDBAtlasStoreStats:
    """통계 테스트"""

    def test_initial_stats(self, mock_client):
        """초기 통계 값 테스트"""
        from app.infrastructure.storage.vector.mongodb_atlas_store import (
            MongoDBAtlasStore,
        )

        store = MongoDBAtlasStore(
            connection_string="mongodb+srv://user:pass@cluster.mongodb.net",
            _client=mock_client,
        )

        stats = store.stats
        assert stats["documents_added"] == 0
        assert stats["searches"] == 0
        assert stats["deletions"] == 0
