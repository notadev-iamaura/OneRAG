"""
QdrantVectorStore 단위 테스트

테스트 항목:
1. 기본 초기화 및 속성 확인
2. 문서 저장 (add_documents)
3. 벡터 검색 (search)
4. 문서 삭제 (delete)
5. 에러 처리

Note:
    Qdrant 클라이언트가 필요하지 않은 단위 테스트입니다.
    Mock을 사용하여 Qdrant 동작을 시뮬레이션합니다.
"""

import pytest

# Qdrant 선택적 의존성 - 미설치 환경에서 스킵
qdrant_client = pytest.importorskip(
    "qdrant_client", reason="qdrant-client가 설치되지 않았습니다"
)


from unittest.mock import MagicMock

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_qdrant_client():
    """Mock Qdrant 클라이언트"""
    client = MagicMock()

    # search 결과 설정
    mock_hit1 = MagicMock()
    mock_hit1.id = 12345
    mock_hit1.score = 0.95
    mock_hit1.payload = {"content": "테스트 문서 1", "source": "test.pdf"}

    mock_hit2 = MagicMock()
    mock_hit2.id = 67890
    mock_hit2.score = 0.85
    mock_hit2.payload = {"content": "테스트 문서 2", "source": "manual.json"}

    client.search.return_value = [mock_hit1, mock_hit2]
    client.upsert.return_value = None
    client.delete.return_value = None

    return client


# ============================================================
# 초기화 테스트
# ============================================================


class TestQdrantVectorStoreInit:
    """QdrantVectorStore 초기화 테스트"""

    def test_local_initialization(self, mock_qdrant_client):
        """로컬 모드 초기화 테스트"""
        from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(
            host="localhost",
            port=6333,
            collection_name="documents",
            _client=mock_qdrant_client,
        )

        assert store.host == "localhost"
        assert store.port == 6333
        assert store.collection_name == "documents"

    def test_cloud_initialization(self, mock_qdrant_client):
        """클라우드 모드 초기화 테스트"""
        from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(
            url="https://xxx.qdrant.io",
            api_key="test-api-key",
            collection_name="cloud-docs",
            _client=mock_qdrant_client,
        )

        assert store.url == "https://xxx.qdrant.io"
        assert store.api_key == "test-api-key"
        assert store.collection_name == "cloud-docs"

    def test_default_values(self, mock_qdrant_client):
        """기본값 테스트"""
        from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(_client=mock_qdrant_client)

        assert store.host == "localhost"
        assert store.port == 6333
        assert store.collection_name == "documents"


# ============================================================
# 문서 저장 테스트
# ============================================================


class TestQdrantVectorStoreAddDocuments:
    """문서 저장 테스트"""

    @pytest.mark.asyncio
    async def test_add_documents_success(self, mock_qdrant_client):
        """문서 저장 성공 테스트"""
        from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(_client=mock_qdrant_client)

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
        mock_qdrant_client.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_documents_empty_list(self, mock_qdrant_client):
        """빈 문서 리스트 처리 테스트"""
        from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(_client=mock_qdrant_client)

        count = await store.add_documents("documents", [])

        assert count == 0
        mock_qdrant_client.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_documents_auto_id(self, mock_qdrant_client):
        """ID 자동 생성 테스트"""
        from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(_client=mock_qdrant_client)

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
    async def test_add_documents_skip_no_embedding(self, mock_qdrant_client):
        """embedding 없는 문서 스킵 테스트"""
        from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(_client=mock_qdrant_client)

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


class TestQdrantVectorStoreSearch:
    """벡터 검색 테스트"""

    @pytest.mark.asyncio
    async def test_search_success(self, mock_qdrant_client):
        """검색 성공 테스트"""
        from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(_client=mock_qdrant_client)

        query_vector = [0.1] * 1024
        results = await store.search("documents", query_vector, top_k=5)

        assert len(results) == 2
        assert results[0]["_score"] == 0.95
        assert results[0]["content"] == "테스트 문서 1"

        mock_qdrant_client.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_with_filters(self, mock_qdrant_client):
        """필터 적용 검색 테스트"""
        from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(_client=mock_qdrant_client)

        query_vector = [0.1] * 1024
        filters = {"file_type": "PDF"}

        await store.search("documents", query_vector, filters=filters)

        # search가 filter와 함께 호출되었는지 확인
        call_args = mock_qdrant_client.search.call_args
        assert call_args.kwargs.get("query_filter") is not None

    @pytest.mark.asyncio
    async def test_search_updates_stats(self, mock_qdrant_client):
        """검색 통계 업데이트 테스트"""
        from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(_client=mock_qdrant_client)

        await store.search("documents", [0.1] * 1024)

        assert store.stats["searches"] == 1


# ============================================================
# 삭제 테스트
# ============================================================


class TestQdrantVectorStoreDelete:
    """문서 삭제 테스트"""

    @pytest.mark.asyncio
    async def test_delete_by_ids(self, mock_qdrant_client):
        """ID로 삭제 테스트"""
        from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(_client=mock_qdrant_client)

        count = await store.delete("documents", {"ids": ["doc-1", "doc-2"]})

        assert count == 2
        mock_qdrant_client.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_empty_ids(self, mock_qdrant_client):
        """빈 ID 리스트 삭제 테스트"""
        from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(_client=mock_qdrant_client)

        count = await store.delete("documents", {"ids": []})

        assert count == 0
        mock_qdrant_client.delete.assert_not_called()


# ============================================================
# 에러 처리 테스트
# ============================================================


class TestQdrantVectorStoreErrorHandling:
    """에러 처리 테스트"""

    @pytest.mark.asyncio
    async def test_search_error_handling(self, mock_qdrant_client):
        """검색 에러 처리 테스트"""
        from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore

        mock_qdrant_client.search.side_effect = Exception("연결 실패")

        store = QdrantVectorStore(_client=mock_qdrant_client)

        with pytest.raises(RuntimeError, match="Qdrant 검색 중 오류"):
            await store.search("documents", [0.1] * 1024)

    @pytest.mark.asyncio
    async def test_add_documents_error_handling(self, mock_qdrant_client):
        """저장 에러 처리 테스트"""
        from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore

        mock_qdrant_client.upsert.side_effect = Exception("저장 실패")

        store = QdrantVectorStore(_client=mock_qdrant_client)

        with pytest.raises(RuntimeError, match="Qdrant 문서 저장 중 오류"):
            await store.add_documents(
                "documents",
                [{"id": "doc-1", "embedding": [0.1] * 1024, "content": "test"}],
            )


# ============================================================
# 통계 테스트
# ============================================================


class TestQdrantVectorStoreStats:
    """통계 테스트"""

    def test_initial_stats(self, mock_qdrant_client):
        """초기 통계 값 테스트"""
        from app.infrastructure.storage.vector.qdrant_store import QdrantVectorStore

        store = QdrantVectorStore(_client=mock_qdrant_client)

        stats = store.stats
        assert stats["documents_added"] == 0
        assert stats["searches"] == 0
        assert stats["deletions"] == 0
