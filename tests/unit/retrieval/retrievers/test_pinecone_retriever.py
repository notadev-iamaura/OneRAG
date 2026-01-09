"""
PineconeRetriever 단위 테스트

테스트 항목:
1. 기본 초기화 및 속성 확인
2. Dense 검색 (하이브리드 비활성화)
3. 하이브리드 검색 (Sparse Vector 포함)
4. BM25 전처리 모듈 통합
5. 에러 처리
6. health_check 기능

Note:
    Pinecone 클라이언트가 필요하지 않은 단위 테스트입니다.
    Mock을 사용하여 PineconeVectorStore 동작을 시뮬레이션합니다.
"""

import pytest

# Pinecone 선택적 의존성 - 미설치 환경에서 스킵
pinecone = pytest.importorskip("pinecone", reason="pinecone이 설치되지 않았습니다")


from unittest.mock import AsyncMock, MagicMock

from app.modules.core.retrieval.interfaces import SearchResult

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_embedder():
    """Mock 임베딩 모델"""
    embedder = MagicMock()
    embedder.embed_query.return_value = [0.1] * 1024  # 기본 1024 차원 벡터
    return embedder


@pytest.fixture
def mock_store():
    """Mock PineconeVectorStore"""
    store = AsyncMock()
    store.search.return_value = [
        {
            "_id": "doc-1",
            "_score": 0.95,
            "content": "테스트 문서 1",
            "source": "test.pdf",
            "file_type": "PDF",
        },
        {
            "_id": "doc-2",
            "_score": 0.85,
            "content": "테스트 문서 2",
            "source": "manual.json",
            "file_type": "JSON",
        },
    ]
    return store


@pytest.fixture
def mock_synonym_manager():
    """Mock 동의어 관리자"""
    manager = MagicMock()
    manager.expand_query.return_value = "확장된 검색어"
    return manager


@pytest.fixture
def mock_stopword_filter():
    """Mock 불용어 필터"""
    filter_ = MagicMock()
    filter_.filter_text.return_value = "필터링된 텍스트"
    return filter_


@pytest.fixture
def mock_user_dictionary():
    """Mock 사용자 사전"""
    dict_ = MagicMock()
    dict_.protect_entries.return_value = ("보호된 텍스트", {"__TOKEN__": "원본단어"})
    dict_.restore_entries.return_value = "복원된 텍스트"
    return dict_


# ============================================================
# 초기화 테스트
# ============================================================


class TestPineconeRetrieverInit:
    """PineconeRetriever 초기화 테스트"""

    def test_basic_initialization(self, mock_embedder, mock_store):
        """기본 초기화 성공 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
            namespace="documents",
            top_k=10,
        )

        assert retriever.embedder == mock_embedder
        assert retriever.store == mock_store
        assert retriever.namespace == "documents"
        assert retriever.top_k == 10

    def test_initialization_with_defaults(self, mock_embedder, mock_store):
        """기본값으로 초기화 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        assert retriever.namespace == "default"
        assert retriever.top_k == 10
        assert retriever.hybrid_alpha == 0.6

    def test_initialization_with_bm25_modules(
        self,
        mock_embedder,
        mock_store,
        mock_synonym_manager,
        mock_stopword_filter,
        mock_user_dictionary,
    ):
        """BM25 전처리 모듈과 함께 초기화 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
            synonym_manager=mock_synonym_manager,
            stopword_filter=mock_stopword_filter,
            user_dictionary=mock_user_dictionary,
        )

        assert retriever.synonym_manager == mock_synonym_manager
        assert retriever.stopword_filter == mock_stopword_filter
        assert retriever.user_dictionary == mock_user_dictionary
        assert retriever._bm25_preprocessing_enabled is True

    def test_stats_initialized(self, mock_embedder, mock_store):
        """통계 초기화 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        assert "total_searches" in retriever.stats
        assert "hybrid_searches" in retriever.stats
        assert "errors" in retriever.stats
        assert retriever.stats["total_searches"] == 0


# ============================================================
# Dense 검색 테스트
# ============================================================


class TestPineconeRetrieverDenseSearch:
    """PineconeRetriever Dense 검색 테스트"""

    @pytest.mark.asyncio
    async def test_dense_search_success(self, mock_embedder, mock_store):
        """Dense 검색 성공 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
            hybrid_alpha=1.0,  # Dense only
        )

        results = await retriever.search("테스트 쿼리", top_k=5)

        # 검색 결과 검증
        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)
        assert results[0].id == "doc-1"
        assert results[0].content == "테스트 문서 1"
        assert results[0].score == 0.95

        # store.search 호출 검증
        mock_store.search.assert_called_once()
        call_args = mock_store.search.call_args
        assert call_args.kwargs["top_k"] == 5

    @pytest.mark.asyncio
    async def test_dense_search_updates_stats(self, mock_embedder, mock_store):
        """검색 후 통계 업데이트 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        await retriever.search("테스트")

        assert retriever.stats["total_searches"] == 1

    @pytest.mark.asyncio
    async def test_search_with_filters(self, mock_embedder, mock_store):
        """필터 적용 검색 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        filters = {"file_type": "PDF"}
        await retriever.search("테스트", filters=filters)

        # filters가 store.search에 전달되었는지 확인
        call_args = mock_store.search.call_args
        assert call_args.kwargs.get("filters") == filters


# ============================================================
# 하이브리드 검색 테스트
# ============================================================


class TestPineconeRetrieverHybridSearch:
    """PineconeRetriever 하이브리드 검색 테스트"""

    @pytest.mark.asyncio
    async def test_hybrid_search_with_sparse_vector(self, mock_embedder, mock_store):
        """하이브리드 검색 (Sparse Vector) 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
            hybrid_alpha=0.6,  # Hybrid mode
        )

        # sparse_encoder mock 설정
        retriever._sparse_encoder = MagicMock()
        retriever._sparse_encoder.encode.return_value = {
            "indices": [1, 5, 10],
            "values": [0.5, 0.3, 0.2],
        }

        await retriever.search("테스트 쿼리")

        # sparse_vector가 store.search에 전달되었는지 확인
        call_args = mock_store.search.call_args
        assert "sparse_vector" in call_args.kwargs

    @pytest.mark.asyncio
    async def test_hybrid_alpha_affects_search(self, mock_embedder, mock_store):
        """hybrid_alpha 값에 따른 검색 동작 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        # Dense only (alpha=1.0)
        retriever_dense = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
            hybrid_alpha=1.0,
        )

        await retriever_dense.search("테스트")

        # alpha=1.0이면 sparse_vector 없이 검색
        call_args = mock_store.search.call_args
        sparse_vector = call_args.kwargs.get("sparse_vector")
        # Dense only일 때는 sparse_vector가 None이거나 전달되지 않음
        assert sparse_vector is None


# ============================================================
# BM25 전처리 테스트
# ============================================================


class TestPineconeRetrieverBM25Preprocessing:
    """PineconeRetriever BM25 전처리 테스트"""

    @pytest.mark.asyncio
    async def test_bm25_preprocessing_applied(
        self,
        mock_embedder,
        mock_store,
        mock_synonym_manager,
        mock_stopword_filter,
    ):
        """BM25 전처리가 적용되는지 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
            synonym_manager=mock_synonym_manager,
            stopword_filter=mock_stopword_filter,
        )

        # sparse encoder 설정
        retriever._sparse_encoder = MagicMock()
        retriever._sparse_encoder.encode.return_value = {
            "indices": [1],
            "values": [0.5],
        }

        await retriever.search("원본 쿼리")

        # 동의어 확장 호출 확인
        mock_synonym_manager.expand_query.assert_called()

    def test_preprocess_query_pipeline(
        self,
        mock_embedder,
        mock_store,
        mock_synonym_manager,
        mock_stopword_filter,
        mock_user_dictionary,
    ):
        """전처리 파이프라인 순서 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
            synonym_manager=mock_synonym_manager,
            stopword_filter=mock_stopword_filter,
            user_dictionary=mock_user_dictionary,
        )

        retriever._preprocess_query("테스트 쿼리")

        # 파이프라인 순서 확인
        # 1. protect_entries 먼저
        mock_user_dictionary.protect_entries.assert_called_once()
        # 2. expand_query
        mock_synonym_manager.expand_query.assert_called_once()
        # 3. filter_text
        mock_stopword_filter.filter_text.assert_called_once()
        # 4. restore_entries 마지막
        mock_user_dictionary.restore_entries.assert_called_once()

    def test_preprocess_query_without_modules(self, mock_embedder, mock_store):
        """BM25 모듈 없이 전처리 테스트 (원본 반환)"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        result = retriever._preprocess_query("원본 쿼리")

        assert result == "원본 쿼리"


# ============================================================
# 에러 처리 테스트
# ============================================================


class TestPineconeRetrieverErrorHandling:
    """PineconeRetriever 에러 처리 테스트"""

    @pytest.mark.asyncio
    async def test_search_error_updates_stats(self, mock_embedder, mock_store):
        """검색 에러 시 통계 업데이트 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        mock_store.search.side_effect = Exception("Pinecone 연결 오류")

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        with pytest.raises(Exception, match="Pinecone 연결 오류"):
            await retriever.search("테스트")

        assert retriever.stats["errors"] == 1

    @pytest.mark.asyncio
    async def test_embedder_error_handling(self, mock_embedder, mock_store):
        """임베더 에러 처리 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        mock_embedder.embed_query.side_effect = ValueError("임베딩 실패")

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        with pytest.raises(ValueError, match="임베딩 실패"):
            await retriever.search("테스트")


# ============================================================
# Health Check 테스트
# ============================================================


class TestPineconeRetrieverHealthCheck:
    """PineconeRetriever health_check 테스트"""

    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_embedder, mock_store):
        """health_check 성공 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        # describe_index_stats mock
        mock_store.describe_index_stats = AsyncMock(return_value={"total_vector_count": 100})

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        result = await retriever.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, mock_embedder, mock_store):
        """health_check 실패 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        mock_store.describe_index_stats = AsyncMock(side_effect=Exception("연결 실패"))

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        result = await retriever.health_check()

        assert result is False


# ============================================================
# 결과 변환 테스트
# ============================================================


class TestPineconeRetrieverResultConversion:
    """검색 결과 변환 테스트"""

    def test_convert_to_search_results(self, mock_embedder, mock_store):
        """Pinecone 결과를 SearchResult로 변환 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        raw_results = [
            {
                "_id": "vec-123",
                "_score": 0.92,
                "content": "문서 내용",
                "source": "doc.pdf",
                "category": "정보",
            }
        ]

        results = retriever._convert_to_search_results(raw_results)

        assert len(results) == 1
        assert results[0].id == "vec-123"
        assert results[0].score == 0.92
        assert results[0].content == "문서 내용"
        assert results[0].metadata["source"] == "doc.pdf"
        assert results[0].metadata["category"] == "정보"

    def test_convert_handles_missing_fields(self, mock_embedder, mock_store):
        """누락된 필드 처리 테스트"""
        from app.modules.core.retrieval.retrievers.pinecone_retriever import (
            PineconeRetriever,
        )

        retriever = PineconeRetriever(
            embedder=mock_embedder,
            store=mock_store,
        )

        raw_results = [
            {
                "_id": "vec-456",
                # _score 누락
                # content 누락
            }
        ]

        results = retriever._convert_to_search_results(raw_results)

        assert len(results) == 1
        assert results[0].id == "vec-456"
        assert results[0].score == 0.0
        assert results[0].content == ""
