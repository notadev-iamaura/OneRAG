"""
로컬 CrossEncoder 리랭커 단위 테스트

선택적 의존성: uv sync --extra local-reranker

TDD RED 단계:
- LocalReranker 구현 전 테스트 작성
- sentence-transformers CrossEncoder 기반
- 현재 커버리지: 0% (구현 전)
- 목표 커버리지: 75-85%
"""

from typing import Any

import pytest

from app.modules.core.retrieval.interfaces import SearchResult


# 선택적 의존성 체크 (sentence-transformers가 설치되어 있는지 확인)
try:
    from sentence_transformers import CrossEncoder  # noqa: F401

    HAS_LOCAL_RERANKER = True
except ImportError:
    HAS_LOCAL_RERANKER = False


@pytest.mark.skipif(not HAS_LOCAL_RERANKER, reason="local-reranker 의존성 미설치")
class TestLocalRerankerInitialization:
    """LocalReranker 초기화 테스트"""

    def test_init_with_default_model(self) -> None:
        """
        기본 모델로 초기화 테스트

        Given: 모델명 미지정
        When: LocalReranker 초기화
        Then: 기본 모델 'cross-encoder/ms-marco-MiniLM-L-12-v2' 설정됨
        """
        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        reranker = LocalReranker()
        assert reranker.model_name == "cross-encoder/ms-marco-MiniLM-L-12-v2"

    def test_init_with_custom_model(self) -> None:
        """
        커스텀 모델로 초기화 테스트

        Given: 커스텀 모델명 지정
        When: LocalReranker 초기화
        Then: 지정된 모델명으로 설정됨
        """
        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        custom_model = "cross-encoder/ms-marco-MiniLM-L-12-v2"
        reranker = LocalReranker(model_name=custom_model)
        assert reranker.model_name == custom_model

    def test_init_with_custom_device(self) -> None:
        """
        커스텀 디바이스 설정 테스트

        Given: 특정 디바이스(cpu/cuda) 지정
        When: LocalReranker 초기화
        Then: 지정된 디바이스로 설정됨
        """
        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        reranker = LocalReranker(device="cpu")
        assert reranker.device == "cpu"

    @pytest.mark.asyncio
    async def test_initialize_method(self) -> None:
        """
        initialize() 메서드 테스트

        Given: LocalReranker 인스턴스
        When: initialize() 호출
        Then: 모델 로드 완료
        """
        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        reranker = LocalReranker()
        await reranker.initialize()

        # 에러 없이 완료되면 성공
        assert True

    @pytest.mark.asyncio
    async def test_close_method(self) -> None:
        """
        close() 메서드 테스트

        Given: LocalReranker 인스턴스
        When: close() 호출
        Then: 정상 완료 (리소스 정리)
        """
        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        reranker = LocalReranker()
        await reranker.close()

        # 에러 없이 완료되면 성공
        assert True


@pytest.mark.skipif(not HAS_LOCAL_RERANKER, reason="local-reranker 의존성 미설치")
class TestLocalRerankerRerank:
    """LocalReranker.rerank() 테스트"""

    @pytest.fixture
    def sample_results(self) -> list[SearchResult]:
        """테스트용 검색 결과"""
        return [
            SearchResult(
                id="1",
                content="Python is a programming language.",
                score=0.8,
                metadata={"source": "doc1.txt"},
            ),
            SearchResult(
                id="2",
                content="Java is an object-oriented language.",
                score=0.7,
                metadata={"source": "doc2.txt"},
            ),
            SearchResult(
                id="3",
                content="Python is great for data analysis.",
                score=0.6,
                metadata={"source": "doc3.txt"},
            ),
        ]

    @pytest.mark.asyncio
    async def test_rerank_success(self, sample_results: list[SearchResult]) -> None:
        """
        리랭킹 성공 테스트

        Given: 쿼리와 문서 리스트
        When: CrossEncoder 리랭킹 수행
        Then: 재정렬된 문서 반환, 점수 0-1 범위
        """
        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        reranker = LocalReranker()
        results = await reranker.rerank("What is Python?", sample_results)

        assert len(results) == 3
        # 점수가 재계산되었는지 확인 (0-1 범위 정규화)
        assert all(0 <= r.score <= 1 for r in results)

    @pytest.mark.asyncio
    async def test_rerank_empty_results(self) -> None:
        """
        빈 결과 리랭킹 테스트

        Given: 빈 결과 리스트
        When: 리랭킹 수행
        Then: 빈 리스트 반환
        """
        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        reranker = LocalReranker()
        results = await reranker.rerank("test query", [])

        assert results == []

    @pytest.mark.asyncio
    async def test_rerank_with_top_n(self, sample_results: list[SearchResult]) -> None:
        """
        top_n 적용 테스트

        Given: top_n=2 설정
        When: 리랭킹 수행
        Then: 상위 2개만 반환
        """
        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        reranker = LocalReranker()
        results = await reranker.rerank("Python", sample_results, top_n=2)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_rerank_preserves_metadata(
        self, sample_results: list[SearchResult]
    ) -> None:
        """
        메타데이터 보존 테스트

        Given: 메타데이터가 있는 검색 결과
        When: 리랭킹 수행
        Then: 메타데이터가 유지됨
        """
        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        reranker = LocalReranker()
        results = await reranker.rerank("Python", sample_results)

        # 모든 결과에 source 메타데이터가 유지되어야 함
        for result in results:
            assert "source" in result.metadata

    @pytest.mark.asyncio
    async def test_rerank_single_result(self) -> None:
        """
        단일 결과 리랭킹 테스트

        Given: 결과 1개
        When: 리랭킹 수행
        Then: 단일 결과 반환
        """
        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        single_result = [
            SearchResult(
                id="single",
                content="Single document content.",
                score=0.5,
                metadata={"source": "single.txt"},
            )
        ]

        reranker = LocalReranker()
        results = await reranker.rerank("document", single_result)

        assert len(results) == 1
        assert results[0].id == "single"


@pytest.mark.skipif(not HAS_LOCAL_RERANKER, reason="local-reranker 의존성 미설치")
class TestLocalRerankerHelpers:
    """LocalReranker 헬퍼 메서드 테스트"""

    def test_supports_caching(self) -> None:
        """
        캐싱 지원 확인 테스트

        Given: LocalReranker 인스턴스
        When: supports_caching() 호출
        Then: True 반환 (로컬 모델은 결정론적)
        """
        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        reranker = LocalReranker()
        assert reranker.supports_caching() is True

    def test_get_stats_initial(self) -> None:
        """
        초기 통계 반환 테스트

        Given: 새로 생성된 LocalReranker
        When: get_stats() 호출
        Then: 초기 통계 반환 (요청 0건, 모델명 포함)
        """
        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        reranker = LocalReranker()
        stats = reranker.get_stats()

        assert "total_requests" in stats
        assert "model_name" in stats
        assert stats["total_requests"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_after_rerank(self) -> None:
        """
        리랭킹 후 통계 업데이트 테스트

        Given: 리랭킹 성공 후
        When: get_stats() 호출
        Then: 요청 수 증가
        """
        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        sample_results = [
            SearchResult(id="test", content="test content", score=0.5, metadata={}),
        ]

        reranker = LocalReranker()
        await reranker.rerank("test", sample_results)

        stats = reranker.get_stats()
        assert stats["total_requests"] == 1
        assert stats["successful_requests"] == 1


@pytest.mark.skipif(not HAS_LOCAL_RERANKER, reason="local-reranker 의존성 미설치")
class TestLocalRerankerErrorHandling:
    """LocalReranker 에러 핸들링 테스트"""

    @pytest.fixture
    def sample_results(self) -> list[SearchResult]:
        """샘플 검색 결과"""
        return [
            SearchResult(
                id="doc1",
                content="Python programming",
                score=0.7,
                metadata={"source": "doc1.txt"},
            ),
            SearchResult(
                id="doc2",
                content="Java programming",
                score=0.6,
                metadata={"source": "doc2.txt"},
            ),
        ]

    @pytest.mark.asyncio
    async def test_graceful_fallback_on_error(
        self, sample_results: list[SearchResult]
    ) -> None:
        """
        에러 시 원본 반환 테스트

        Given: CrossEncoder 내부 예외 발생
        When: 리랭킹 수행
        Then: 원본 결과 반환 (graceful degradation)
        """
        from unittest.mock import MagicMock, patch

        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        reranker = LocalReranker()

        # CrossEncoder.predict가 예외를 발생시키도록 모킹
        with patch.object(reranker, "_model", MagicMock()) as mock_model:
            mock_model.predict.side_effect = RuntimeError("Model error")

            results = await reranker.rerank("test", sample_results)

            # 실패 시 원본 반환
            assert len(results) == 2
            assert results[0].id == "doc1"

    @pytest.mark.asyncio
    async def test_stats_track_failures(
        self, sample_results: list[SearchResult]
    ) -> None:
        """
        실패 통계 추적 테스트

        Given: 리랭킹 실패 발생
        When: get_stats() 호출
        Then: 실패 통계 업데이트됨
        """
        from unittest.mock import MagicMock, patch

        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        reranker = LocalReranker()

        # 예외 발생 시뮬레이션
        with patch.object(reranker, "_model", MagicMock()) as mock_model:
            mock_model.predict.side_effect = RuntimeError("Model error")

            await reranker.rerank("test", sample_results)

            stats = reranker.get_stats()
            assert stats["total_requests"] == 1
            assert stats["failed_requests"] == 1


@pytest.mark.skipif(not HAS_LOCAL_RERANKER, reason="local-reranker 의존성 미설치")
class TestLocalRerankerScoreNormalization:
    """LocalReranker 점수 정규화 테스트"""

    @pytest.fixture
    def sample_results(self) -> list[SearchResult]:
        """테스트용 검색 결과"""
        return [
            SearchResult(id="1", content="High relevance doc", score=0.9, metadata={}),
            SearchResult(id="2", content="Medium relevance doc", score=0.5, metadata={}),
            SearchResult(id="3", content="Low relevance doc", score=0.1, metadata={}),
        ]

    @pytest.mark.asyncio
    async def test_scores_normalized_to_0_1_range(
        self, sample_results: list[SearchResult]
    ) -> None:
        """
        점수 정규화 테스트 (0-1 범위)

        Given: CrossEncoder의 원시 점수 (-∞ ~ +∞)
        When: 리랭킹 수행
        Then: 모든 점수가 0-1 범위로 정규화됨
        """
        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        reranker = LocalReranker()
        results = await reranker.rerank("relevance query", sample_results)

        # 모든 점수가 0-1 범위인지 확인
        for result in results:
            assert 0.0 <= result.score <= 1.0, f"점수가 범위를 벗어남: {result.score}"

    @pytest.mark.asyncio
    async def test_results_sorted_by_score_descending(
        self, sample_results: list[SearchResult]
    ) -> None:
        """
        점수 내림차순 정렬 테스트

        Given: 여러 검색 결과
        When: 리랭킹 수행
        Then: 점수 내림차순으로 정렬됨
        """
        from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

        reranker = LocalReranker()
        results = await reranker.rerank("test query", sample_results)

        # 점수가 내림차순인지 확인
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score, (
                f"정렬 오류: {results[i].score} < {results[i + 1].score}"
            )
