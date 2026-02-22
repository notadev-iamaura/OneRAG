"""
MongoDBAtlasRetriever 문서 관리 메서드 단위 테스트

테스트 범위:
1. get_document_chunks — document_id로 모든 청크 조회
2. delete_document — document_id의 모든 청크 삭제
3. list_documents — 고유 문서 목록 페이지네이션 조회
4. get_document_details — 문서 상세 정보 조회
5. get_document_stats — 문서/벡터 수량 통계
6. get_collection_info — 컬렉션 메타정보
7. delete_all_documents — 전체 문서 삭제
8. recreate_collection — 컬렉션 재생성
9. backup_metadata — 메타데이터 백업

Note: MongoDBAtlasRetriever는 self._store, self._collection_name 사용
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.core.retrieval.retrievers.mongodb_atlas_retriever import MongoDBAtlasRetriever


@pytest.mark.unit
class TestMongoDBAtlasDocumentManagement:
    """MongoDBAtlasRetriever 문서 관리 테스트"""

    @pytest.fixture
    def mock_store(self):
        """문서 관리 메서드가 있는 Mock Store"""
        store = AsyncMock()
        store.search = AsyncMock(return_value=[])
        store.fetch_objects = AsyncMock(return_value=[])
        store.delete_objects = AsyncMock(return_value=True)
        store.count_objects = AsyncMock(return_value=0)
        return store

    @pytest.fixture
    def retriever(self, mock_store):
        """MongoDBAtlasRetriever 인스턴스"""
        embedder = MagicMock()
        embedder.embed_query = MagicMock(return_value=[0.1] * 768)

        return MongoDBAtlasRetriever(
            embedder=embedder,
            store=mock_store,
            collection_name="TestDocuments",
        )

    # ========== get_document_chunks ==========

    @pytest.mark.asyncio
    async def test_get_document_chunks(self, retriever, mock_store):
        """document_id로 모든 청크를 조회"""
        mock_store.fetch_objects.return_value = [
            {"_id": "id-1", "content": "첫 번째 청크", "document_id": "doc-1", "chunk_index": 0},
            {"_id": "id-2", "content": "두 번째 청크", "document_id": "doc-1", "chunk_index": 1},
        ]

        result = await retriever.get_document_chunks("doc-1")

        assert len(result) == 2
        assert result[0]["content"] == "첫 번째 청크"

    @pytest.mark.asyncio
    async def test_get_document_chunks_empty(self, retriever, mock_store):
        """존재하지 않는 문서"""
        mock_store.fetch_objects.return_value = []
        result = await retriever.get_document_chunks("nonexistent")
        assert result == []

    # ========== delete_document ==========

    @pytest.mark.asyncio
    async def test_delete_document(self, retriever, mock_store):
        """문서 삭제"""
        mock_store.fetch_objects.return_value = [
            {"_id": "id-1", "content": "a", "document_id": "doc-1"},
        ]

        result = await retriever.delete_document("doc-1")
        assert result is True
        mock_store.delete_objects.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_document_nonexistent(self, retriever, mock_store):
        """존재하지 않는 문서 삭제"""
        mock_store.fetch_objects.return_value = []
        result = await retriever.delete_document("nonexistent")
        assert result is False

    # ========== list_documents ==========

    @pytest.mark.asyncio
    async def test_list_documents(self, retriever, mock_store):
        """문서 목록 조회"""
        mock_store.fetch_objects.return_value = [
            {"_id": "id-1", "content": "a", "document_id": "doc-1", "source_file": "a.pdf", "file_type": "PDF", "created_at": "2024-01-01"},
            {"_id": "id-2", "content": "b", "document_id": "doc-2", "source_file": "b.txt", "file_type": "TXT", "created_at": "2024-06-01"},
        ]

        result = await retriever.list_documents(page=1, page_size=20)
        assert result["total_count"] == 2

    @pytest.mark.asyncio
    async def test_list_documents_empty(self, retriever, mock_store):
        """빈 컬렉션"""
        mock_store.fetch_objects.return_value = []
        result = await retriever.list_documents()
        assert result["total_count"] == 0

    # ========== get_document_details ==========

    @pytest.mark.asyncio
    async def test_get_document_details(self, retriever, mock_store):
        """문서 상세"""
        mock_store.fetch_objects.return_value = [
            {"_id": "id-1", "content": "내용", "document_id": "doc-1", "source_file": "r.pdf", "file_type": "PDF", "chunk_index": 0, "created_at": "2024-01-15"},
        ]

        result = await retriever.get_document_details("doc-1")
        assert result is not None
        assert result["id"] == "doc-1"

    @pytest.mark.asyncio
    async def test_get_document_details_nonexistent(self, retriever, mock_store):
        """존재하지 않는 문서"""
        mock_store.fetch_objects.return_value = []
        result = await retriever.get_document_details("nonexistent")
        assert result is None

    # ========== get_document_stats ==========

    @pytest.mark.asyncio
    async def test_get_document_stats(self, retriever, mock_store):
        """통계"""
        mock_store.fetch_objects.return_value = [
            {"_id": "id-1", "document_id": "doc-1", "content": "a"},
            {"_id": "id-2", "document_id": "doc-1", "content": "b"},
            {"_id": "id-3", "document_id": "doc-2", "content": "c"},
        ]

        result = await retriever.get_document_stats()
        assert result["total_documents"] == 2
        assert result["vector_count"] == 3

    # ========== get_collection_info ==========

    @pytest.mark.asyncio
    async def test_get_collection_info(self, retriever, mock_store):
        """컬렉션 메타정보"""
        mock_store.fetch_objects.return_value = [
            {"_id": "id-1", "document_id": "doc-1", "content": "a", "created_at": "2024-01-01"},
        ]

        result = await retriever.get_collection_info()
        assert result["collection_name"] == "TestDocuments"

    # ========== delete_all_documents ==========

    @pytest.mark.asyncio
    async def test_delete_all_documents(self, retriever, mock_store):
        """전체 삭제"""
        mock_store.fetch_objects.return_value = [
            {"_id": "id-1", "document_id": "doc-1", "content": "a"},
        ]

        result = await retriever.delete_all_documents()
        assert result is True

    # ========== recreate_collection ==========

    @pytest.mark.asyncio
    async def test_recreate_collection(self, retriever, mock_store):
        """컬렉션 재생성"""
        mock_store.fetch_objects.return_value = []
        result = await retriever.recreate_collection()
        assert result is True

    # ========== backup_metadata ==========

    @pytest.mark.asyncio
    async def test_backup_metadata(self, retriever, mock_store):
        """메타데이터 백업"""
        mock_store.fetch_objects.return_value = [
            {"_id": "id-1", "content": "a", "document_id": "doc-1", "source_file": "a.pdf", "file_type": "PDF", "chunk_index": 0, "created_at": "2024-01-01"},
        ]

        result = await retriever.backup_metadata()
        assert len(result) == 1
