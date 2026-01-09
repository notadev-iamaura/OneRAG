"""
QdrantRetriever 단위 테스트

테스트 항목:
1. 초기화 및 속성 확인
2. Dense 검색 (hybrid_alpha=1.0)
3. 하이브리드 검색 (Dense + Sparse)
4. BM25 전처리 모듈 통합
5. 에러 처리
6. health_check
7. 결과 변환

Note:
    Qdrant 클라이언트가 필요하지 않은 단위 테스트입니다.
    Mock을 사용하여 Qdrant 동작을 시뮬레이션합니다.
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
        """쿼리를 768차원 벡터로 변환"""
        return [0.1] * 768


class MockVectorStore:
    """Mock Qdrant Vector Store"""

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
        sparse_vector: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Mock 검색"""
        return self.search_results[:top_k]


class MockSynonymManager:
    """Mock 동의어 관리자"""

    def expand_query(self, query: str) -> str:
        """동의어 확장 - AI를 인공지능으로 확장"""
        return query.replace("AI", "AI 인공지능")


class MockStopwordFilter:
    """Mock 불용어 필터"""

    def filter_text(self, text: str) -> str:
        """불용어 제거 - '은/는/이/가' 제거"""
        for word in ["은", "는", "이", "가"]:
            text = text.replace(f" {word} ", " ")
        return text


class MockUserDictionary:
    """Mock 사용자 사전"""

    def protect_entries(self, text: str) -> tuple[str, dict[str, str]]:
        """합성어 보호"""
        restore_map = {}
        if "머신러닝" in text:
            restore_map["__TERM_0__"] = "머신러닝"
            text = text.replace("머신러닝", "__TERM_0__")
        return text, restore_map

    def restore_entries(self, text: str, restore_map: dict[str, str]) -> str:
        """합성어 복원"""
        for placeholder, original in restore_map.items():
            text = text.replace(placeholder, original)
        return text


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


@pytest.fixture
def mock_synonym_manager() -> MockSynonymManager:
    """Mock 동의어 관리자 fixture"""
    return MockSynonymManager()


@pytest.fixture
def mock_stopword_filter() -> MockStopwordFilter:
    """Mock 불용어 필터 fixture"""
    return MockStopwordFilter()


@pytest.fixture
def mock_user_dictionary() -> MockUserDictionary:
    """Mock 사용자 사전 fixture"""
    return MockUserDictionary()


# ============================================================
# 초기화 테스트
# ============================================================


class TestQdrantRetrieverInit:
    """QdrantRetriever 초기화 테스트"""

    def test_basic_initialization(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """기본 초기화 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=mock_store,
            collection_name="documents",
            top_k=10,
        )

        assert retriever.collection_name == "documents"
        assert retriever.top_k == 10
        assert retriever.hybrid_alpha == 0.6  # 기본값

    def test_initialization_with_hybrid_alpha(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """hybrid_alpha 설정 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=mock_store,
            hybrid_alpha=0.8,
        )

        assert retriever.hybrid_alpha == 0.8

    def test_initialization_with_bm25_modules(
        self,
        mock_embedder: MockEmbedder,
        mock_store: MockVectorStore,
        mock_synonym_manager: MockSynonymManager,
        mock_stopword_filter: MockStopwordFilter,
        mock_user_dictionary: MockUserDictionary,
    ) -> None:
        """BM25 전처리 모듈과 함께 초기화 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=mock_store,
            synonym_manager=mock_synonym_manager,
            stopword_filter=mock_stopword_filter,
            user_dictionary=mock_user_dictionary,
        )

        assert retriever.synonym_manager is not None
        assert retriever.stopword_filter is not None
        assert retriever.user_dictionary is not None
        assert retriever._bm25_preprocessing_enabled is True

    def test_stats_property(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """통계 속성 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        stats = retriever.stats
        assert "total_searches" in stats
        assert "hybrid_searches" in stats
        assert "errors" in stats
        assert stats["total_searches"] == 0


# ============================================================
# Dense 검색 테스트
# ============================================================


class TestQdrantRetrieverDenseSearch:
    """Dense 검색 테스트 (hybrid_alpha=1.0)"""

    @pytest.mark.asyncio
    async def test_dense_search_basic(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """기본 Dense 검색 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=mock_store,
            hybrid_alpha=1.0,  # Dense만 사용
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
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=mock_store,
            hybrid_alpha=1.0,
        )

        results = await retriever.search("테스트 쿼리", top_k=1)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_dense_search_updates_stats(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """검색 후 통계 업데이트 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=mock_store,
            hybrid_alpha=1.0,
        )

        await retriever.search("테스트 쿼리")

        assert retriever.stats["total_searches"] == 1
        assert retriever.stats["hybrid_searches"] == 0  # Dense만 사용


# ============================================================
# 하이브리드 검색 테스트
# ============================================================


class TestQdrantRetrieverHybridSearch:
    """하이브리드 검색 테스트 (Dense + Sparse)"""

    @pytest.mark.asyncio
    async def test_hybrid_search_alpha_setting(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """hybrid_alpha 설정에 따른 검색 모드 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        # 하이브리드 모드 (alpha < 1.0)
        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=mock_store,
            hybrid_alpha=0.6,  # 60% Dense + 40% Sparse
        )

        results = await retriever.search("테스트 쿼리")

        assert len(results) == 2
        # Sparse 인코더가 없으므로 실제로는 Dense만 사용됨
        # 하지만 alpha < 1.0이면 하이브리드 모드로 간주

    @pytest.mark.asyncio
    async def test_hybrid_search_with_filters(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """필터와 함께 하이브리드 검색 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=mock_store,
            hybrid_alpha=0.6,
        )

        filters = {"file_type": "PDF"}
        results = await retriever.search("테스트 쿼리", filters=filters)

        assert len(results) == 2


# ============================================================
# BM25 전처리 테스트
# ============================================================


class TestQdrantRetrieverBM25Preprocessing:
    """BM25 전처리 테스트"""

    def test_preprocess_query_with_synonym(
        self,
        mock_embedder: MockEmbedder,
        mock_store: MockVectorStore,
        mock_synonym_manager: MockSynonymManager,
    ) -> None:
        """동의어 확장 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=mock_store,
            synonym_manager=mock_synonym_manager,
        )

        processed = retriever._preprocess_query("AI 기술")

        assert "인공지능" in processed

    def test_preprocess_query_with_user_dictionary(
        self,
        mock_embedder: MockEmbedder,
        mock_store: MockVectorStore,
        mock_user_dictionary: MockUserDictionary,
    ) -> None:
        """사용자 사전 (합성어 보호/복원) 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=mock_store,
            user_dictionary=mock_user_dictionary,
        )

        processed = retriever._preprocess_query("머신러닝 기술")

        assert "머신러닝" in processed

    def test_preprocess_query_disabled(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """BM25 전처리 비활성화 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=mock_store,
            # BM25 모듈 없음
        )

        query = "원본 쿼리"
        processed = retriever._preprocess_query(query)

        assert processed == query  # 변경 없음


# ============================================================
# 에러 처리 테스트
# ============================================================


class TestQdrantRetrieverErrorHandling:
    """에러 처리 테스트"""

    @pytest.mark.asyncio
    async def test_search_error_updates_stats(
        self, mock_embedder: MockEmbedder
    ) -> None:
        """검색 에러 시 통계 업데이트 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        # 에러를 발생시키는 Mock Store
        error_store = MagicMock()
        error_store.search = AsyncMock(side_effect=Exception("검색 실패"))

        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=error_store,
        )

        with pytest.raises(Exception, match="검색 실패"):
            await retriever.search("테스트 쿼리")

        assert retriever.stats["errors"] == 1

    @pytest.mark.asyncio
    async def test_embedding_error_handling(self, mock_store: MockVectorStore) -> None:
        """임베딩 에러 처리 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        # 에러를 발생시키는 Mock Embedder
        error_embedder = MagicMock()
        error_embedder.embed_query = MagicMock(side_effect=Exception("임베딩 실패"))

        retriever = QdrantRetriever(
            embedder=error_embedder,
            store=mock_store,
        )

        with pytest.raises(Exception, match="임베딩 실패"):
            await retriever.search("테스트 쿼리")


# ============================================================
# health_check 테스트
# ============================================================


class TestQdrantRetrieverHealthCheck:
    """health_check 테스트"""

    @pytest.mark.asyncio
    async def test_health_check_success(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """health_check 성공 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        result = await retriever.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, mock_embedder: MockEmbedder) -> None:
        """health_check 실패 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        # 에러를 발생시키는 Mock Store
        error_store = MagicMock()
        error_store.search = AsyncMock(side_effect=Exception("연결 실패"))

        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=error_store,
        )

        result = await retriever.health_check()

        assert result is False


# ============================================================
# 결과 변환 테스트
# ============================================================


class TestQdrantRetrieverResultConversion:
    """검색 결과 변환 테스트"""

    def test_convert_to_search_results(
        self, mock_embedder: MockEmbedder, mock_store: MockVectorStore
    ) -> None:
        """검색 결과 변환 테스트"""
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        retriever = QdrantRetriever(
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
        from app.modules.core.retrieval.retrievers.qdrant_retriever import (
            QdrantRetriever,
        )

        retriever = QdrantRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        results = retriever._convert_to_search_results([])

        assert len(results) == 0
