"""
Retrieval Orchestrator 실패 처리 테스트

테스트 범위:
1. Weaviate 실패 시 MongoDB 폴백
2. 리랭커 실패 시 원본 점수 유지
3. GraphRAG 실패 시 벡터 검색만 사용
4. 캐시 실패 시 직접 검색
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.lib.errors import SearchUnavailableError
from app.modules.core.retrieval.interfaces import SearchResult
from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator


@pytest.mark.unit
class TestOrchestratorFailures:
    """실패 처리 테스트"""

    @pytest.fixture
    def orchestrator(self):
        """Orchestrator 인스턴스"""
        retriever = AsyncMock()
        reranker = AsyncMock()

        return RetrievalOrchestrator(
            retriever=retriever,
            reranker=reranker,
            cache=None,  # 캐시 비활성화 (테스트 단순화)
            config={},
        )

    @pytest.mark.asyncio
    async def test_retriever_failure_propagates_search_unavailable(self, orchestrator):
        """
        Retriever 전면 실패 시 전용 예외 전파 (Phase 2.7)

        Given: Retriever에서 에러 발생 (단일 쿼리 = 모든 쿼리 실패와 동치)
        When: search_and_rerank() 호출
        Then: SearchUnavailableError 전파 — 빈 결과로 위장하면 상위
              CircuitBreaker가 장애를 감지하지 못한다. degradation(빈 결과)은
              호출자(rag_pipeline의 CB fallback 등)가 담당한다.
        """
        # Mock: Retriever 실패
        orchestrator.retriever.search.side_effect = Exception("Weaviate connection lost")

        with pytest.raises(SearchUnavailableError) as exc_info:
            await orchestrator.search_and_rerank(
                query="테스트 쿼리",
                top_k=10,
            )

        # 검증: 원인 예외가 체이닝으로 보존된다
        assert "Weaviate connection lost" in str(exc_info.value.__cause__)
        orchestrator.retriever.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_reranker_failure_uses_original_scores(self, orchestrator):
        """
        Reranker 실패 시 원본 점수 사용

        Given: Reranker에서 에러 발생
        When: search_and_rerank() 호출
        Then: 리랭킹 없이 검색 결과 반환
        """
        # Mock: 검색 성공
        search_results = [
            SearchResult(id="1", content="문서1", score=0.9, metadata={}),
            SearchResult(id="2", content="문서2", score=0.8, metadata={}),
        ]
        orchestrator.retriever.search.return_value = search_results

        # Mock: Reranker 실패
        orchestrator.reranker.rerank.side_effect = Exception("Gemini API error")

        result = await orchestrator.search_and_rerank(
            query="테스트 쿼리",
            top_k=10,
            rerank_enabled=True,
        )

        # 검증: 원본 결과 반환
        assert len(result) == 2
        assert result[0].content == "문서1"
        assert result[0].score == 0.9  # 원본 점수 유지

    @pytest.mark.asyncio
    async def test_cache_failure_bypasses_cache(self):
        """
        캐시 실패 시 직접 검색

        Given: 캐시 조회 실패
        When: search_and_rerank() 호출
        Then: 캐시 우회하고 직접 검색
        """
        # 캐시가 있는 Orchestrator 생성
        retriever = AsyncMock()
        reranker = AsyncMock()
        cache = MagicMock()  # AsyncMock 대신 MagicMock 사용

        orchestrator = RetrievalOrchestrator(
            retriever=retriever,
            reranker=reranker,
            cache=cache,
            config={},
        )

        # Mock: 캐시 키 생성은 성공
        cache.generate_cache_key.return_value = "test_cache_key"

        # Mock: 캐시 조회 실패 (async)
        async def cache_get_error(*args, **kwargs):
            raise Exception("Redis connection lost")

        cache.get = AsyncMock(side_effect=cache_get_error)

        # Mock: 캐시 저장도 AsyncMock
        cache.set = AsyncMock()

        # Mock: 검색 성공
        search_results = [
            SearchResult(id="1", content="문서1", score=0.9, metadata={}),
        ]
        retriever.search.return_value = search_results

        # Mock: 리랭커도 동일한 결과 반환 (리랭킹 없이 통과)
        reranker.rerank.return_value = search_results

        result = await orchestrator.search_and_rerank(
            query="테스트 쿼리",
            top_k=10,
        )

        # 검증: 검색 성공 (캐시 우회)
        assert len(result) == 1
        retriever.search.assert_called_once()
