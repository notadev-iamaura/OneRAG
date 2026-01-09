"""
PgVectorRetriever 단위 테스트

테스트 항목:
1. 초기화 및 속성 확인
2. Dense 검색
3. 에러 처리
4. health_check
5. 결과 변환

Note:
    PostgreSQL + pgvector가 필요하지 않은 단위 테스트입니다.
    Mock을 사용하여 pgvector 동작을 시뮬레이션합니다.
    pgvector는 기본적으로 Dense 전용 검색 (하이브리드 미지원)
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ============================================================
# Mock 클래스 정의
# ============================================================


class MockEmbedder:
    """Mock 임베딩 모델"""

    def embed_query(self, text: str) -> list[float]:
        """쿼리를 1024차원 벡터로 변환"""
        return [0.1] * 1024


class MockVectorStore:
    """Mock pgvector Store"""

    def __init__(self) -> None:
        self.search_results: list[dict[str, Any]] = [
            {
                "_id": "doc-1",
                "_score": 0.95,
                "content": "테스트 문서 1",
                "source": "test.pdf",
            },
            {
                "_id": "doc-2",
                "_score": 0.85,
                "content": "테스트 문서 2",
                "source": "manual.json",
            },
        ]

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Mock 검색"""
        return self.search_results[:top_k]


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_embedder() -> MockEmbedder:
    """Mock 임베딩 모델 fixture"""
    return MockEmbedder()


@pytest.fixture
def mock_store() -> MockVectorStore:
    """Mock Vector Store fixture"""
    return MockVectorStore()


# ============================================================
# 초기화 테스트
# ============================================================


class TestPgVectorRetrieverInit:
    """PgVectorRetriever 초기화 테스트"""

    def test_basic_initialization(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """기본 초기화 테스트"""
        from app.modules.core.retrieval.retrievers.pgvector_retriever import (
            PgVectorRetriever,
        )

        retriever = PgVectorRetriever(
            embedder=mock_embedder,
            store=mock_store,
            table_name="documents",
            top_k=10,
        )

        assert retriever.table_name == "documents"
        assert retriever.top_k == 10

    def test_initialization_with_custom_values(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """커스텀 값으로 초기화 테스트"""
        from app.modules.core.retrieval.retrievers.pgvector_retriever import (
            PgVectorRetriever,
        )

        retriever = PgVectorRetriever(
            embedder=mock_embedder,
            store=mock_store,
            table_name="custom_docs",
            top_k=20,
        )

        assert retriever.table_name == "custom_docs"
        assert retriever.top_k == 20

    def test_stats_property(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """통계 속성 테스트"""
        from app.modules.core.retrieval.retrievers.pgvector_retriever import (
            PgVectorRetriever,
        )

        retriever = PgVectorRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        stats = retriever.stats
        assert "total_searches" in stats
        assert "errors" in stats
        assert stats["total_searches"] == 0


# ============================================================
# Dense 검색 테스트
# ============================================================


class TestPgVectorRetrieverDenseSearch:
    """Dense 검색 테스트"""

    @pytest.mark.asyncio
    async def test_dense_search_basic(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """기본 Dense 검색 테스트"""
        from app.modules.core.retrieval.retrievers.pgvector_retriever import (
            PgVectorRetriever,
        )

        retriever = PgVectorRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        results = await retriever.search("테스트 쿼리")

        assert len(results) == 2
        assert results[0].score == 0.95
        assert results[0].content == "테스트 문서 1"

    @pytest.mark.asyncio
    async def test_dense_search_with_top_k(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """top_k 파라미터 테스트"""
        from app.modules.core.retrieval.retrievers.pgvector_retriever import (
            PgVectorRetriever,
        )

        retriever = PgVectorRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        results = await retriever.search("테스트 쿼리", top_k=1)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_dense_search_with_filters(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """필터와 함께 검색 테스트"""
        from app.modules.core.retrieval.retrievers.pgvector_retriever import (
            PgVectorRetriever,
        )

        retriever = PgVectorRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        filters = {"file_type": "PDF"}
        results = await retriever.search("테스트 쿼리", filters=filters)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_dense_search_updates_stats(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """검색 후 통계 업데이트 테스트"""
        from app.modules.core.retrieval.retrievers.pgvector_retriever import (
            PgVectorRetriever,
        )

        retriever = PgVectorRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        await retriever.search("테스트 쿼리")

        assert retriever.stats["total_searches"] == 1


# ============================================================
# 에러 처리 테스트
# ============================================================


class TestPgVectorRetrieverErrorHandling:
    """에러 처리 테스트"""

    @pytest.mark.asyncio
    async def test_search_error_updates_stats(
        self, mock_embedder: MockEmbedder
    ) -> None:
        """검색 에러 시 통계 업데이트 테스트"""
        from app.modules.core.retrieval.retrievers.pgvector_retriever import (
            PgVectorRetriever,
        )

        # 에러를 발생시키는 Mock Store
        error_store = MagicMock()
        error_store.search = AsyncMock(side_effect=Exception("검색 실패"))

        retriever = PgVectorRetriever(
            embedder=mock_embedder,
            store=error_store,
        )

        with pytest.raises(Exception, match="검색 실패"):
            await retriever.search("테스트 쿼리")

        assert retriever.stats["errors"] == 1

    @pytest.mark.asyncio
    async def test_embedding_error_handling(self, mock_store: MockVectorStore) -> None:
        """임베딩 에러 처리 테스트"""
        from app.modules.core.retrieval.retrievers.pgvector_retriever import (
            PgVectorRetriever,
        )

        # 에러를 발생시키는 Mock Embedder
        error_embedder = MagicMock()
        error_embedder.embed_query = MagicMock(side_effect=Exception("임베딩 실패"))

        retriever = PgVectorRetriever(
            embedder=error_embedder,
            store=mock_store,
        )

        with pytest.raises(Exception, match="임베딩 실패"):
            await retriever.search("테스트 쿼리")


# ============================================================
# health_check 테스트
# ============================================================


class TestPgVectorRetrieverHealthCheck:
    """health_check 테스트"""

    @pytest.mark.asyncio
    async def test_health_check_success(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """health_check 성공 테스트"""
        from app.modules.core.retrieval.retrievers.pgvector_retriever import (
            PgVectorRetriever,
        )

        retriever = PgVectorRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        result = await retriever.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, mock_embedder: MockEmbedder) -> None:
        """health_check 실패 테스트"""
        from app.modules.core.retrieval.retrievers.pgvector_retriever import (
            PgVectorRetriever,
        )

        # 에러를 발생시키는 Mock Store
        error_store = MagicMock()
        error_store.search = AsyncMock(side_effect=Exception("연결 실패"))

        retriever = PgVectorRetriever(
            embedder=mock_embedder,
            store=error_store,
        )

        result = await retriever.health_check()

        assert result is False


# ============================================================
# 결과 변환 테스트
# ============================================================


class TestPgVectorRetrieverResultConversion:
    """검색 결과 변환 테스트"""

    def test_convert_to_search_results(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """검색 결과 변환 테스트"""
        from app.modules.core.retrieval.retrievers.pgvector_retriever import (
            PgVectorRetriever,
        )

        retriever = PgVectorRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        raw_results = [
            {
                "_id": "doc-1",
                "_score": 0.95,
                "content": "테스트 내용",
                "source": "test.pdf",
            }
        ]

        results = retriever._convert_to_search_results(raw_results)

        assert len(results) == 1
        assert results[0].id == "doc-1"
        assert results[0].score == 0.95
        assert results[0].content == "테스트 내용"
        assert results[0].metadata["source"] == "test.pdf"

    def test_convert_empty_results(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """빈 결과 변환 테스트"""
        from app.modules.core.retrieval.retrievers.pgvector_retriever import (
            PgVectorRetriever,
        )

        retriever = PgVectorRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        results = retriever._convert_to_search_results([])

        assert len(results) == 0
