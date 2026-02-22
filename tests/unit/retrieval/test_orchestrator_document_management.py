"""
RetrievalOrchestrator 문서 관리 위임 메서드 테스트

테스트 범위:
1. get_document_chunks — Retriever로 위임, 미구현 시 NotImplementedError
2. delete_document — Retriever로 위임, 미구현 시 NotImplementedError
3. list_documents — Retriever로 위임, 미구현 시 NotImplementedError
4. get_document_details — Retriever로 위임, 미구현 시 NotImplementedError
5. get_document_stats — Retriever로 위임, 미구현 시 NotImplementedError
6. get_collection_info — Retriever로 위임, 미구현 시 NotImplementedError
7. delete_all_documents — Retriever로 위임, 미구현 시 NotImplementedError
8. recreate_collection — Retriever로 위임, 미구현 시 NotImplementedError
9. backup_metadata — Retriever로 위임, 미구현 시 NotImplementedError

위임 패턴: 기존 add_documents()와 동일한 hasattr() 기반 Duck Typing
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator


@pytest.mark.unit
class TestOrchestratorDocumentManagement:
    """문서 관리 위임 메서드 테스트"""

    @pytest.fixture
    def retriever_with_doc_management(self):
        """문서 관리 메서드를 가진 Mock Retriever"""
        retriever = AsyncMock()
        # 문서 관리 메서드 모킹
        retriever.get_document_chunks = AsyncMock(return_value=[
            {"id": "chunk-1", "content": "청크 1 내용", "metadata": {"document_id": "doc-1", "chunk_index": 0}},
            {"id": "chunk-2", "content": "청크 2 내용", "metadata": {"document_id": "doc-1", "chunk_index": 1}},
        ])
        retriever.delete_document = AsyncMock(return_value=True)
        retriever.list_documents = AsyncMock(return_value={
            "documents": [
                {"id": "doc-1", "filename": "test.pdf", "file_type": "PDF", "file_size": 1024, "upload_date": 1700000000, "chunk_count": 5},
            ],
            "total_count": 1,
        })
        retriever.get_document_details = AsyncMock(return_value={
            "id": "doc-1",
            "filename": "test.pdf",
            "file_type": "PDF",
            "file_size": 1024,
            "upload_date": 1700000000,
            "actual_chunk_count": 5,
            "chunk_previews": ["청크 1 미리보기..."],
            "metadata": {},
        })
        retriever.get_document_stats = AsyncMock(return_value={
            "total_documents": 10,
            "vector_count": 150,
        })
        retriever.get_collection_info = AsyncMock(return_value={
            "size_mb": 25.5,
            "oldest_document": "2024-01-01T00:00:00",
            "newest_document": "2024-12-01T00:00:00",
        })
        retriever.delete_all_documents = AsyncMock(return_value=True)
        retriever.recreate_collection = AsyncMock(return_value=True)
        retriever.backup_metadata = AsyncMock(return_value=[
            {"id": "doc-1", "filename": "test.pdf", "chunk_count": 5},
        ])
        return retriever

    @pytest.fixture
    def retriever_without_doc_management(self):
        """문서 관리 메서드가 없는 최소 Mock Retriever"""
        retriever = AsyncMock(spec=["search", "health_check"])
        retriever.search = AsyncMock(return_value=[])
        retriever.health_check = AsyncMock(return_value=True)
        return retriever

    @pytest.fixture
    def orchestrator_with(self, retriever_with_doc_management):
        """문서 관리 지원 Orchestrator"""
        return RetrievalOrchestrator(
            retriever=retriever_with_doc_management,
            reranker=None,
            cache=None,
            config={},
        )

    @pytest.fixture
    def orchestrator_without(self, retriever_without_doc_management):
        """문서 관리 미지원 Orchestrator"""
        return RetrievalOrchestrator(
            retriever=retriever_without_doc_management,
            reranker=None,
            cache=None,
            config={},
        )

    # ========== get_document_chunks ==========

    @pytest.mark.asyncio
    async def test_get_document_chunks_delegates_to_retriever(self, orchestrator_with, retriever_with_doc_management):
        """
        get_document_chunks가 Retriever로 위임되는지 검증

        Given: 문서 관리를 지원하는 Retriever
        When: orchestrator.get_document_chunks("doc-1") 호출
        Then: retriever.get_document_chunks("doc-1")이 호출되고 결과 반환
        """
        result = await orchestrator_with.get_document_chunks("doc-1")

        retriever_with_doc_management.get_document_chunks.assert_called_once_with("doc-1")
        assert len(result) == 2
        assert result[0]["content"] == "청크 1 내용"

    @pytest.mark.asyncio
    async def test_get_document_chunks_raises_not_implemented(self, orchestrator_without):
        """
        Retriever에 get_document_chunks가 없으면 NotImplementedError 발생

        Given: 문서 관리를 지원하지 않는 Retriever
        When: orchestrator.get_document_chunks("doc-1") 호출
        Then: NotImplementedError 발생
        """
        with pytest.raises(NotImplementedError, match="get_document_chunks"):
            await orchestrator_without.get_document_chunks("doc-1")

    # ========== delete_document ==========

    @pytest.mark.asyncio
    async def test_delete_document_delegates_to_retriever(self, orchestrator_with, retriever_with_doc_management):
        """delete_document가 Retriever로 위임되는지 검증"""
        result = await orchestrator_with.delete_document("doc-1")

        retriever_with_doc_management.delete_document.assert_called_once_with("doc-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_document_raises_not_implemented(self, orchestrator_without):
        """Retriever에 delete_document가 없으면 NotImplementedError 발생"""
        with pytest.raises(NotImplementedError, match="delete_document"):
            await orchestrator_without.delete_document("doc-1")

    # ========== list_documents ==========

    @pytest.mark.asyncio
    async def test_list_documents_delegates_to_retriever(self, orchestrator_with, retriever_with_doc_management):
        """list_documents가 Retriever로 위임되는지 검증"""
        result = await orchestrator_with.list_documents(page=1, page_size=20)

        retriever_with_doc_management.list_documents.assert_called_once_with(page=1, page_size=20)
        assert result["total_count"] == 1
        assert len(result["documents"]) == 1

    @pytest.mark.asyncio
    async def test_list_documents_raises_not_implemented(self, orchestrator_without):
        """Retriever에 list_documents가 없으면 NotImplementedError 발생"""
        with pytest.raises(NotImplementedError, match="list_documents"):
            await orchestrator_without.list_documents()

    # ========== get_document_details ==========

    @pytest.mark.asyncio
    async def test_get_document_details_delegates_to_retriever(self, orchestrator_with, retriever_with_doc_management):
        """get_document_details가 Retriever로 위임되는지 검증"""
        result = await orchestrator_with.get_document_details("doc-1")

        retriever_with_doc_management.get_document_details.assert_called_once_with("doc-1")
        assert result is not None
        assert result["filename"] == "test.pdf"

    @pytest.mark.asyncio
    async def test_get_document_details_raises_not_implemented(self, orchestrator_without):
        """Retriever에 get_document_details가 없으면 NotImplementedError 발생"""
        with pytest.raises(NotImplementedError, match="get_document_details"):
            await orchestrator_without.get_document_details("doc-1")

    # ========== get_document_stats ==========

    @pytest.mark.asyncio
    async def test_get_document_stats_delegates_to_retriever(self, orchestrator_with, retriever_with_doc_management):
        """get_document_stats가 Retriever로 위임되는지 검증"""
        result = await orchestrator_with.get_document_stats()

        retriever_with_doc_management.get_document_stats.assert_called_once()
        assert result["total_documents"] == 10
        assert result["vector_count"] == 150

    @pytest.mark.asyncio
    async def test_get_document_stats_raises_not_implemented(self, orchestrator_without):
        """Retriever에 get_document_stats가 없으면 NotImplementedError 발생"""
        with pytest.raises(NotImplementedError, match="get_document_stats"):
            await orchestrator_without.get_document_stats()

    # ========== get_collection_info ==========

    @pytest.mark.asyncio
    async def test_get_collection_info_delegates_to_retriever(self, orchestrator_with, retriever_with_doc_management):
        """get_collection_info가 Retriever로 위임되는지 검증"""
        result = await orchestrator_with.get_collection_info()

        retriever_with_doc_management.get_collection_info.assert_called_once()
        assert result["size_mb"] == 25.5

    @pytest.mark.asyncio
    async def test_get_collection_info_raises_not_implemented(self, orchestrator_without):
        """Retriever에 get_collection_info가 없으면 NotImplementedError 발생"""
        with pytest.raises(NotImplementedError, match="get_collection_info"):
            await orchestrator_without.get_collection_info()

    # ========== delete_all_documents ==========

    @pytest.mark.asyncio
    async def test_delete_all_documents_delegates_to_retriever(self, orchestrator_with, retriever_with_doc_management):
        """delete_all_documents가 Retriever로 위임되는지 검증"""
        result = await orchestrator_with.delete_all_documents()

        retriever_with_doc_management.delete_all_documents.assert_called_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_all_documents_raises_not_implemented(self, orchestrator_without):
        """Retriever에 delete_all_documents가 없으면 NotImplementedError 발생"""
        with pytest.raises(NotImplementedError, match="delete_all_documents"):
            await orchestrator_without.delete_all_documents()

    # ========== recreate_collection ==========

    @pytest.mark.asyncio
    async def test_recreate_collection_delegates_to_retriever(self, orchestrator_with, retriever_with_doc_management):
        """recreate_collection이 Retriever로 위임되는지 검증"""
        result = await orchestrator_with.recreate_collection()

        retriever_with_doc_management.recreate_collection.assert_called_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_recreate_collection_raises_not_implemented(self, orchestrator_without):
        """Retriever에 recreate_collection이 없으면 NotImplementedError 발생"""
        with pytest.raises(NotImplementedError, match="recreate_collection"):
            await orchestrator_without.recreate_collection()

    # ========== backup_metadata ==========

    @pytest.mark.asyncio
    async def test_backup_metadata_delegates_to_retriever(self, orchestrator_with, retriever_with_doc_management):
        """backup_metadata가 Retriever로 위임되는지 검증"""
        result = await orchestrator_with.backup_metadata()

        retriever_with_doc_management.backup_metadata.assert_called_once()
        assert len(result) == 1
        assert result[0]["filename"] == "test.pdf"

    @pytest.mark.asyncio
    async def test_backup_metadata_raises_not_implemented(self, orchestrator_without):
        """Retriever에 backup_metadata가 없으면 NotImplementedError 발생"""
        with pytest.raises(NotImplementedError, match="backup_metadata"):
            await orchestrator_without.backup_metadata()
