"""
WeaviateRetriever 문서 관리 메서드 단위 테스트

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
"""

from unittest.mock import MagicMock

import pytest

from app.modules.core.retrieval.retrievers.weaviate_retriever import WeaviateRetriever


def _make_weaviate_object(uuid: str, properties: dict, score: float = 0.9) -> MagicMock:
    """Weaviate 검색 결과 객체를 Mock으로 생성하는 헬퍼"""
    obj = MagicMock()
    obj.uuid = uuid
    obj.properties = properties
    obj.metadata = MagicMock()
    obj.metadata.score = score
    return obj


@pytest.mark.unit
class TestWeaviateDocumentManagement:
    """WeaviateRetriever 문서 관리 테스트"""

    @pytest.fixture
    def mock_collection(self):
        """Mock Weaviate Collection"""
        collection = MagicMock()
        # query.fetch_objects 모킹
        collection.query = MagicMock()
        collection.query.fetch_objects = MagicMock()
        # data 모킹
        collection.data = MagicMock()
        collection.data.delete_by_id = MagicMock()
        # aggregate 모킹
        collection.aggregate = MagicMock()
        return collection

    @pytest.fixture
    def retriever(self, mock_collection):
        """문서 관리 테스트용 WeaviateRetriever"""
        embedder = MagicMock()
        embedder.embed_query = MagicMock(return_value=[0.1] * 3072)

        client = MagicMock()
        client.is_ready = MagicMock(return_value=True)
        client.get_collection = MagicMock(return_value=mock_collection)

        retriever = WeaviateRetriever(
            embedder=embedder,
            weaviate_client=client,
            collection_name="Documents",
        )
        # 초기화 없이 컬렉션 직접 설정
        retriever.collection = mock_collection
        return retriever

    # ========== get_document_chunks ==========

    @pytest.mark.asyncio
    async def test_get_document_chunks_returns_all_chunks(self, retriever, mock_collection):
        """
        document_id로 모든 청크를 조회

        Given: "doc-1" 문서에 2개 청크가 저장됨
        When: get_document_chunks("doc-1") 호출
        Then: 2개 청크의 content, metadata가 포함된 리스트 반환
        """
        # Mock: fetch_objects 결과
        mock_objects = [
            _make_weaviate_object("uuid-1", {
                "content": "첫 번째 청크",
                "document_id": "doc-1",
                "source_file": "test.pdf",
                "chunk_index": 0,
                "page": 1,
            }),
            _make_weaviate_object("uuid-2", {
                "content": "두 번째 청크",
                "document_id": "doc-1",
                "source_file": "test.pdf",
                "chunk_index": 1,
                "page": 1,
            }),
        ]
        mock_response = MagicMock()
        mock_response.objects = mock_objects
        mock_collection.query.fetch_objects.return_value = mock_response

        result = await retriever.get_document_chunks("doc-1")

        assert len(result) == 2
        assert result[0]["content"] == "첫 번째 청크"
        assert result[0]["metadata"]["document_id"] == "doc-1"
        assert result[1]["metadata"]["chunk_index"] == 1

    @pytest.mark.asyncio
    async def test_get_document_chunks_returns_empty_for_nonexistent(self, retriever, mock_collection):
        """존재하지 않는 문서 ID에 대해 빈 리스트 반환"""
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query.fetch_objects.return_value = mock_response

        result = await retriever.get_document_chunks("nonexistent-doc")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_document_chunks_collection_not_initialized(self, retriever):
        """컬렉션 미초기화 시 RuntimeError 발생"""
        retriever.collection = None

        with pytest.raises(RuntimeError, match="컬렉션"):
            await retriever.get_document_chunks("doc-1")

    # ========== delete_document ==========

    @pytest.mark.asyncio
    async def test_delete_document_removes_all_chunks(self, retriever, mock_collection):
        """
        문서의 모든 청크를 삭제

        Given: "doc-1"에 2개 청크가 존재
        When: delete_document("doc-1") 호출
        Then: 2개 청크 모두 삭제, True 반환
        """
        mock_objects = [
            _make_weaviate_object("uuid-1", {"document_id": "doc-1", "content": "청크1"}),
            _make_weaviate_object("uuid-2", {"document_id": "doc-1", "content": "청크2"}),
        ]
        mock_response = MagicMock()
        mock_response.objects = mock_objects
        mock_collection.query.fetch_objects.return_value = mock_response

        result = await retriever.delete_document("doc-1")

        assert result is True
        assert mock_collection.data.delete_by_id.call_count == 2

    @pytest.mark.asyncio
    async def test_delete_document_nonexistent_returns_false(self, retriever, mock_collection):
        """존재하지 않는 문서 삭제 시 False 반환"""
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query.fetch_objects.return_value = mock_response

        result = await retriever.delete_document("nonexistent")
        assert result is False

    # ========== list_documents ==========

    @pytest.mark.asyncio
    async def test_list_documents_with_pagination(self, retriever, mock_collection):
        """
        문서 목록을 페이지네이션으로 조회

        Given: 3개 청크가 2개 문서(doc-1: 2청크, doc-2: 1청크)에 속함
        When: list_documents(page=1, page_size=20) 호출
        Then: 2개 문서 정보 반환 (고유 document_id 기준)
        """
        mock_objects = [
            _make_weaviate_object("uuid-1", {
                "content": "청크1", "document_id": "doc-1",
                "source_file": "a.pdf", "file_type": "PDF",
                "created_at": "2024-01-01T00:00:00",
            }),
            _make_weaviate_object("uuid-2", {
                "content": "청크2", "document_id": "doc-1",
                "source_file": "a.pdf", "file_type": "PDF",
                "created_at": "2024-01-01T00:00:00",
            }),
            _make_weaviate_object("uuid-3", {
                "content": "청크3", "document_id": "doc-2",
                "source_file": "b.txt", "file_type": "TXT",
                "created_at": "2024-06-01T00:00:00",
            }),
        ]
        mock_response = MagicMock()
        mock_response.objects = mock_objects
        mock_collection.query.fetch_objects.return_value = mock_response

        result = await retriever.list_documents(page=1, page_size=20)

        assert result["total_count"] == 2
        assert len(result["documents"]) == 2
        # doc-1은 2개 청크
        doc1 = next(d for d in result["documents"] if d["id"] == "doc-1")
        assert doc1["chunk_count"] == 2
        assert doc1["filename"] == "a.pdf"

    @pytest.mark.asyncio
    async def test_list_documents_empty_collection(self, retriever, mock_collection):
        """빈 컬렉션에서 목록 조회 시 빈 결과 반환"""
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query.fetch_objects.return_value = mock_response

        result = await retriever.list_documents()

        assert result["total_count"] == 0
        assert result["documents"] == []

    # ========== get_document_details ==========

    @pytest.mark.asyncio
    async def test_get_document_details_returns_aggregated_info(self, retriever, mock_collection):
        """문서 상세 정보를 청크 메타데이터에서 집계하여 반환"""
        mock_objects = [
            _make_weaviate_object("uuid-1", {
                "content": "첫 번째 청크 내용입니다",
                "document_id": "doc-1",
                "source_file": "report.pdf",
                "file_type": "PDF",
                "chunk_index": 0,
                "created_at": "2024-01-15T10:00:00",
            }),
            _make_weaviate_object("uuid-2", {
                "content": "두 번째 청크 내용입니다",
                "document_id": "doc-1",
                "source_file": "report.pdf",
                "file_type": "PDF",
                "chunk_index": 1,
                "created_at": "2024-01-15T10:00:00",
            }),
        ]
        mock_response = MagicMock()
        mock_response.objects = mock_objects
        mock_collection.query.fetch_objects.return_value = mock_response

        result = await retriever.get_document_details("doc-1")

        assert result is not None
        assert result["id"] == "doc-1"
        assert result["filename"] == "report.pdf"
        assert result["file_type"] == "PDF"
        assert result["actual_chunk_count"] == 2
        assert len(result["chunk_previews"]) == 2

    @pytest.mark.asyncio
    async def test_get_document_details_nonexistent_returns_none(self, retriever, mock_collection):
        """존재하지 않는 문서에 대해 None 반환"""
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query.fetch_objects.return_value = mock_response

        result = await retriever.get_document_details("nonexistent")
        assert result is None

    # ========== get_document_stats ==========

    @pytest.mark.asyncio
    async def test_get_document_stats_returns_counts(self, retriever, mock_collection):
        """문서/벡터 수량 통계 반환"""
        # 3개 객체, 2개 고유 문서
        mock_objects = [
            _make_weaviate_object("uuid-1", {"document_id": "doc-1", "content": "a"}),
            _make_weaviate_object("uuid-2", {"document_id": "doc-1", "content": "b"}),
            _make_weaviate_object("uuid-3", {"document_id": "doc-2", "content": "c"}),
        ]
        mock_response = MagicMock()
        mock_response.objects = mock_objects
        mock_collection.query.fetch_objects.return_value = mock_response

        result = await retriever.get_document_stats()

        assert result["total_documents"] == 2  # 고유 document_id 수
        assert result["vector_count"] == 3  # 전체 청크(벡터) 수

    # ========== get_collection_info ==========

    @pytest.mark.asyncio
    async def test_get_collection_info_returns_metadata(self, retriever, mock_collection):
        """컬렉션 메타정보 반환"""
        mock_objects = [
            _make_weaviate_object("uuid-1", {
                "document_id": "doc-1", "content": "a",
                "created_at": "2024-01-01T00:00:00",
            }),
            _make_weaviate_object("uuid-2", {
                "document_id": "doc-2", "content": "b",
                "created_at": "2024-12-01T00:00:00",
            }),
        ]
        mock_response = MagicMock()
        mock_response.objects = mock_objects
        mock_collection.query.fetch_objects.return_value = mock_response

        result = await retriever.get_collection_info()

        assert "oldest_document" in result
        assert "newest_document" in result
        assert result["collection_name"] == "Documents"

    # ========== delete_all_documents ==========

    @pytest.mark.asyncio
    async def test_delete_all_documents_clears_collection(self, retriever, mock_collection):
        """전체 문서 삭제"""
        mock_objects = [
            _make_weaviate_object("uuid-1", {"document_id": "doc-1", "content": "a"}),
            _make_weaviate_object("uuid-2", {"document_id": "doc-2", "content": "b"}),
        ]
        mock_response = MagicMock()
        mock_response.objects = mock_objects
        mock_collection.query.fetch_objects.return_value = mock_response

        result = await retriever.delete_all_documents()

        assert result is True
        assert mock_collection.data.delete_by_id.call_count == 2

    # ========== recreate_collection ==========

    @pytest.mark.asyncio
    async def test_recreate_collection(self, retriever, mock_collection):
        """컬렉션 재생성 (삭제 후 재초기화)"""
        # delete_all_documents 모킹 (내부에서 호출됨)
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query.fetch_objects.return_value = mock_response

        result = await retriever.recreate_collection()

        assert result is True

    # ========== backup_metadata ==========

    @pytest.mark.asyncio
    async def test_backup_metadata_returns_all_documents(self, retriever, mock_collection):
        """모든 문서의 메타데이터를 백업"""
        mock_objects = [
            _make_weaviate_object("uuid-1", {
                "content": "내용1", "document_id": "doc-1",
                "source_file": "a.pdf", "file_type": "PDF",
                "chunk_index": 0, "created_at": "2024-01-01T00:00:00",
            }),
            _make_weaviate_object("uuid-2", {
                "content": "내용2", "document_id": "doc-2",
                "source_file": "b.txt", "file_type": "TXT",
                "chunk_index": 0, "created_at": "2024-06-01T00:00:00",
            }),
        ]
        mock_response = MagicMock()
        mock_response.objects = mock_objects
        mock_collection.query.fetch_objects.return_value = mock_response

        result = await retriever.backup_metadata()

        assert len(result) == 2
        assert result[0]["id"] in ("doc-1", "doc-2")
