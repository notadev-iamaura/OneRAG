"""
RerankerChain 단위 테스트

다중 리랭커 순차 실행 체인 검증.

테스트 케이스:
1. 순차 실행 (ColBERT → LLM Reranker)
2. 빈 체인 처리
3. 단일 리랭커 체인
4. 중간 리랭커 실패 시 다음 리랭커 계속 실행
5. 모든 리랭커 실패 시 원본 반환
6. 리랭커별 활성화/비활성화
7. 체인 통계 정보

구현일: 2025-12-31
TDD Phase: RED (실패 테스트 작성)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.core.retrieval.interfaces import IReranker, SearchResult

# TDD RED: 아직 존재하지 않는 모듈 임포트 (이 테스트는 실패해야 함)
from app.modules.core.retrieval.rerankers.reranker_chain import (
    RerankerChain,
    RerankerChainConfig,
)

# ========================================
# Mock 리랭커 생성 헬퍼
# ========================================


def create_mock_reranker(
    name: str,
    score_multiplier: float = 1.0,
    should_fail: bool = False,
    enabled: bool = True,
) -> IReranker:
    """
    Mock 리랭커 생성

    Args:
        name: 리랭커 이름
        score_multiplier: 점수에 곱할 배수 (정렬 변경용)
        should_fail: 실패 시뮬레이션 여부
        enabled: 활성화 여부
    """
    mock = MagicMock(spec=IReranker)
    mock.name = name
    mock.enabled = enabled

    if should_fail:
        # 실패 시뮬레이션: side_effect에 예외를 직접 지정하여
        # AsyncMock 내부 코루틴 미소비 RuntimeWarning 방지
        mock.rerank = AsyncMock(side_effect=Exception(f"{name} failed"))
    else:
        async def mock_rerank(
            query: str,
            results: list[SearchResult],
            top_n: int | None = None,
        ) -> list[SearchResult]:
            # 점수 조정 및 정렬
            adjusted_results = []
            for r in results:
                new_score = r.score * score_multiplier
                adjusted_results.append(
                    SearchResult(
                        id=r.id,
                        content=r.content,
                        score=new_score,
                        metadata={**r.metadata, f"{name}_processed": True},
                    )
                )

            # 점수순 정렬
            adjusted_results.sort(key=lambda x: x.score, reverse=True)

            if top_n is not None:
                adjusted_results = adjusted_results[:top_n]

            return adjusted_results

        mock.rerank = AsyncMock(side_effect=mock_rerank)
    mock.supports_caching = MagicMock(return_value=True)

    return mock


# ========================================
# 테스트 픽스처
# ========================================


@pytest.fixture
def sample_search_results() -> list[SearchResult]:
    """테스트용 검색 결과"""
    return [
        SearchResult(
            id="doc_1",
            content="강남 레스토랑 A 정보",
            score=0.85,
            metadata={"name": "레스토랑 A"},
        ),
        SearchResult(
            id="doc_2",
            content="강남 레스토랑 B 정보",
            score=0.80,
            metadata={"name": "레스토랑 B"},
        ),
        SearchResult(
            id="doc_3",
            content="강북 카페 C 정보",
            score=0.75,
            metadata={"name": "카페 C"},
        ),
    ]


@pytest.fixture
def mock_colbert_reranker() -> IReranker:
    """Mock ColBERT 리랭커"""
    return create_mock_reranker("colbert", score_multiplier=1.1)


@pytest.fixture
def mock_llm_reranker() -> IReranker:
    """Mock LLM 리랭커"""
    return create_mock_reranker("llm", score_multiplier=0.95)


@pytest.fixture
def failing_reranker() -> IReranker:
    """실패하는 리랭커"""
    return create_mock_reranker("failing", should_fail=True)


@pytest.fixture
def default_config() -> RerankerChainConfig:
    """기본 체인 설정"""
    return RerankerChainConfig(
        enabled=True,
        continue_on_error=True,  # 오류 시 계속 진행
        log_intermediate_results=False,
    )


# ========================================
# 기본 동작 테스트
# ========================================


class TestRerankerChainBasicOperations:
    """RerankerChain 기본 동작 테스트"""

    @pytest.mark.asyncio
    async def test_sequential_execution_order(
        self,
        sample_search_results: list[SearchResult],
        mock_colbert_reranker: IReranker,
        mock_llm_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """순차 실행 순서 확인 (ColBERT → LLM)"""
        chain = RerankerChain(
            rerankers=[mock_colbert_reranker, mock_llm_reranker],
            config=default_config,
        )

        result = await chain.rerank(
            query="강남 맛집 추천",
            results=sample_search_results,
        )

        # 두 리랭커 모두 호출됨
        mock_colbert_reranker.rerank.assert_called_once()
        mock_llm_reranker.rerank.assert_called_once()

        # 결과에 두 리랭커의 처리 흔적이 있음
        for r in result:
            assert r.metadata.get("colbert_processed") is True
            assert r.metadata.get("llm_processed") is True

    @pytest.mark.asyncio
    async def test_chain_passes_results_between_rerankers(
        self,
        sample_search_results: list[SearchResult],
        mock_colbert_reranker: IReranker,
        mock_llm_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """첫 번째 리랭커 결과가 두 번째에 전달됨"""
        chain = RerankerChain(
            rerankers=[mock_colbert_reranker, mock_llm_reranker],
            config=default_config,
        )

        await chain.rerank(
            query="테스트",
            results=sample_search_results,
        )

        # LLM 리랭커에 전달된 결과 확인
        llm_call_args = mock_llm_reranker.rerank.call_args
        # kwargs 또는 args에서 results 추출 (호출 방식에 따라 다름)
        if "results" in llm_call_args.kwargs:
            passed_results = llm_call_args.kwargs["results"]
        else:
            passed_results = llm_call_args.args[1]

        # ColBERT 처리된 결과가 전달됨
        for r in passed_results:
            assert r.metadata.get("colbert_processed") is True

    @pytest.mark.asyncio
    async def test_final_result_sorted_by_score(
        self,
        sample_search_results: list[SearchResult],
        mock_colbert_reranker: IReranker,
        mock_llm_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """최종 결과는 점수순 정렬"""
        chain = RerankerChain(
            rerankers=[mock_colbert_reranker, mock_llm_reranker],
            config=default_config,
        )

        result = await chain.rerank(
            query="테스트",
            results=sample_search_results,
        )

        # 점수 내림차순 정렬 확인
        for i in range(len(result) - 1):
            assert result[i].score >= result[i + 1].score


# ========================================
# 빈 체인 및 단일 리랭커 테스트
# ========================================


class TestEdgeCases:
    """빈 체인 및 경계 조건 테스트"""

    @pytest.mark.asyncio
    async def test_empty_chain_returns_original(
        self,
        sample_search_results: list[SearchResult],
        default_config: RerankerChainConfig,
    ) -> None:
        """빈 체인은 원본 결과 반환"""
        chain = RerankerChain(
            rerankers=[],
            config=default_config,
        )

        result = await chain.rerank(
            query="테스트",
            results=sample_search_results,
        )

        # 원본 그대로
        assert len(result) == 3
        assert result[0].id == sample_search_results[0].id
        assert result[0].score == sample_search_results[0].score

    @pytest.mark.asyncio
    async def test_single_reranker_chain(
        self,
        sample_search_results: list[SearchResult],
        mock_colbert_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """단일 리랭커 체인 정상 동작"""
        chain = RerankerChain(
            rerankers=[mock_colbert_reranker],
            config=default_config,
        )

        result = await chain.rerank(
            query="테스트",
            results=sample_search_results,
        )

        # 단일 리랭커 처리됨
        mock_colbert_reranker.rerank.assert_called_once()
        for r in result:
            assert r.metadata.get("colbert_processed") is True

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(
        self,
        mock_colbert_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """빈 입력은 빈 결과 반환"""
        chain = RerankerChain(
            rerankers=[mock_colbert_reranker],
            config=default_config,
        )

        result = await chain.rerank(
            query="테스트",
            results=[],
        )

        assert result == []
        # 빈 입력은 리랭커 호출 스킵
        mock_colbert_reranker.rerank.assert_not_called()


# ========================================
# 에러 처리 테스트
# ========================================


class TestErrorHandling:
    """에러 처리 및 복원력 테스트"""

    @pytest.mark.asyncio
    async def test_continue_on_first_reranker_failure(
        self,
        sample_search_results: list[SearchResult],
        failing_reranker: IReranker,
        mock_llm_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """첫 번째 리랭커 실패 시 다음 리랭커 계속 실행"""
        chain = RerankerChain(
            rerankers=[failing_reranker, mock_llm_reranker],
            config=default_config,
        )

        result = await chain.rerank(
            query="테스트",
            results=sample_search_results,
        )

        # 실패한 리랭커 호출됨
        failing_reranker.rerank.assert_called_once()
        # 두 번째 리랭커도 호출됨 (원본으로)
        mock_llm_reranker.rerank.assert_called_once()

        # 결과에 LLM 처리 흔적만 있음
        for r in result:
            assert r.metadata.get("llm_processed") is True

    @pytest.mark.asyncio
    async def test_all_rerankers_fail_returns_original(
        self,
        sample_search_results: list[SearchResult],
        default_config: RerankerChainConfig,
    ) -> None:
        """모든 리랭커 실패 시 원본 반환"""
        failing1 = create_mock_reranker("failing1", should_fail=True)
        failing2 = create_mock_reranker("failing2", should_fail=True)

        chain = RerankerChain(
            rerankers=[failing1, failing2],
            config=default_config,
        )

        result = await chain.rerank(
            query="테스트",
            results=sample_search_results,
        )

        # 원본 결과 반환
        assert len(result) == 3
        assert result[0].id == sample_search_results[0].id

    @pytest.mark.asyncio
    async def test_stop_on_error_mode(
        self,
        sample_search_results: list[SearchResult],
        failing_reranker: IReranker,
        mock_llm_reranker: IReranker,
    ) -> None:
        """continue_on_error=False 시 첫 실패에서 중단"""
        config = RerankerChainConfig(
            enabled=True,
            continue_on_error=False,  # 에러 시 중단
            log_intermediate_results=False,
        )

        chain = RerankerChain(
            rerankers=[failing_reranker, mock_llm_reranker],
            config=config,
        )

        result = await chain.rerank(
            query="테스트",
            results=sample_search_results,
        )

        # 첫 리랭커 호출됨
        failing_reranker.rerank.assert_called_once()
        # 두 번째는 호출 안 됨
        mock_llm_reranker.rerank.assert_not_called()

        # 원본 반환
        assert result[0].id == sample_search_results[0].id


# ========================================
# 활성화/비활성화 테스트
# ========================================


class TestEnableDisable:
    """리랭커별 활성화/비활성화 테스트"""

    @pytest.mark.asyncio
    async def test_disabled_reranker_skipped(
        self,
        sample_search_results: list[SearchResult],
        mock_colbert_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """비활성화된 리랭커는 스킵"""
        disabled_reranker = create_mock_reranker("disabled", enabled=False)

        chain = RerankerChain(
            rerankers=[disabled_reranker, mock_colbert_reranker],
            config=default_config,
        )

        await chain.rerank(
            query="테스트",
            results=sample_search_results,
        )

        # 비활성화 리랭커 호출 안 됨
        disabled_reranker.rerank.assert_not_called()
        # 활성화 리랭커만 호출
        mock_colbert_reranker.rerank.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_disabled_returns_original(
        self,
        sample_search_results: list[SearchResult],
        default_config: RerankerChainConfig,
    ) -> None:
        """모든 리랭커 비활성화 시 원본 반환"""
        disabled1 = create_mock_reranker("disabled1", enabled=False)
        disabled2 = create_mock_reranker("disabled2", enabled=False)

        chain = RerankerChain(
            rerankers=[disabled1, disabled2],
            config=default_config,
        )

        result = await chain.rerank(
            query="테스트",
            results=sample_search_results,
        )

        # 원본 반환
        assert result[0].id == sample_search_results[0].id

    @pytest.mark.asyncio
    async def test_chain_disabled_returns_original(
        self,
        sample_search_results: list[SearchResult],
        mock_colbert_reranker: IReranker,
    ) -> None:
        """체인 자체 비활성화 시 원본 반환"""
        config = RerankerChainConfig(
            enabled=False,  # 체인 비활성화
            continue_on_error=True,
            log_intermediate_results=False,
        )

        chain = RerankerChain(
            rerankers=[mock_colbert_reranker],
            config=config,
        )

        result = await chain.rerank(
            query="테스트",
            results=sample_search_results,
        )

        # 리랭커 호출 안 됨
        mock_colbert_reranker.rerank.assert_not_called()
        # 원본 반환
        assert result[0].id == sample_search_results[0].id


# ========================================
# top_n 제한 테스트
# ========================================


class TestTopNLimit:
    """top_n 결과 제한 테스트"""

    @pytest.mark.asyncio
    async def test_top_n_applied_at_end(
        self,
        sample_search_results: list[SearchResult],
        mock_colbert_reranker: IReranker,
        mock_llm_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """top_n은 체인 끝에서 적용"""
        chain = RerankerChain(
            rerankers=[mock_colbert_reranker, mock_llm_reranker],
            config=default_config,
        )

        result = await chain.rerank(
            query="테스트",
            results=sample_search_results,
            top_n=2,
        )

        # 최종 결과는 2개
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_intermediate_rerankers_receive_full_results(
        self,
        sample_search_results: list[SearchResult],
        mock_colbert_reranker: IReranker,
        mock_llm_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """중간 리랭커는 전체 결과를 받음"""
        chain = RerankerChain(
            rerankers=[mock_colbert_reranker, mock_llm_reranker],
            config=default_config,
        )

        await chain.rerank(
            query="테스트",
            results=sample_search_results,
            top_n=1,  # 최종 1개만
        )

        # ColBERT는 전체 3개 받음
        colbert_call = mock_colbert_reranker.rerank.call_args
        # kwargs 또는 args에서 results 추출 (호출 방식에 따라 다름)
        if "results" in colbert_call.kwargs:
            colbert_results = colbert_call.kwargs["results"]
        else:
            colbert_results = colbert_call.args[1]
        assert len(colbert_results) == 3


# ========================================
# 통계 정보 테스트
# ========================================


class TestChainStatistics:
    """체인 통계 정보 테스트"""

    @pytest.mark.asyncio
    async def test_get_stats_initial(
        self,
        mock_colbert_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """초기 통계 정보"""
        chain = RerankerChain(
            rerankers=[mock_colbert_reranker],
            config=default_config,
        )

        stats = chain.get_stats()

        assert stats["total_calls"] == 0
        assert stats["rerankers_count"] == 1
        assert "per_reranker_stats" in stats

    @pytest.mark.asyncio
    async def test_get_stats_after_calls(
        self,
        sample_search_results: list[SearchResult],
        mock_colbert_reranker: IReranker,
        mock_llm_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """호출 후 통계 정보"""
        chain = RerankerChain(
            rerankers=[mock_colbert_reranker, mock_llm_reranker],
            config=default_config,
        )

        await chain.rerank("쿼리1", sample_search_results)
        await chain.rerank("쿼리2", sample_search_results)

        stats = chain.get_stats()

        assert stats["total_calls"] == 2
        assert stats["successful_calls"] == 2
        assert stats["failed_calls"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_tracks_per_reranker(
        self,
        sample_search_results: list[SearchResult],
        failing_reranker: IReranker,
        mock_llm_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """리랭커별 통계 추적"""
        chain = RerankerChain(
            rerankers=[failing_reranker, mock_llm_reranker],
            config=default_config,
        )

        await chain.rerank("테스트", sample_search_results)

        stats = chain.get_stats()
        per_reranker = stats["per_reranker_stats"]

        # 실패 리랭커 통계
        assert per_reranker["failing"]["calls"] == 1
        assert per_reranker["failing"]["failures"] == 1

        # 성공 리랭커 통계
        assert per_reranker["llm"]["calls"] == 1
        assert per_reranker["llm"]["failures"] == 0


# ========================================
# 캐싱 지원 테스트
# ========================================


class TestCachingSupport:
    """캐싱 지원 여부 테스트"""

    def test_supports_caching_all_support(
        self,
        mock_colbert_reranker: IReranker,
        mock_llm_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """모든 리랭커가 캐싱 지원하면 True"""
        chain = RerankerChain(
            rerankers=[mock_colbert_reranker, mock_llm_reranker],
            config=default_config,
        )

        assert chain.supports_caching() is True

    def test_supports_caching_one_not_support(
        self,
        mock_colbert_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """하나라도 캐싱 미지원이면 False"""
        no_cache_reranker = create_mock_reranker("no_cache")
        no_cache_reranker.supports_caching = MagicMock(return_value=False)

        chain = RerankerChain(
            rerankers=[mock_colbert_reranker, no_cache_reranker],
            config=default_config,
        )

        assert chain.supports_caching() is False

    def test_empty_chain_supports_caching(
        self,
        default_config: RerankerChainConfig,
    ) -> None:
        """빈 체인은 캐싱 지원"""
        chain = RerankerChain(
            rerankers=[],
            config=default_config,
        )

        assert chain.supports_caching() is True


# ========================================
# 리랭커 동적 추가/제거 테스트
# ========================================


class TestDynamicRerankerManagement:
    """리랭커 동적 관리 테스트"""

    @pytest.mark.asyncio
    async def test_add_reranker(
        self,
        sample_search_results: list[SearchResult],
        mock_colbert_reranker: IReranker,
        mock_llm_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """리랭커 동적 추가"""
        chain = RerankerChain(
            rerankers=[mock_colbert_reranker],
            config=default_config,
        )

        # LLM 리랭커 추가
        chain.add_reranker(mock_llm_reranker)

        await chain.rerank("테스트", sample_search_results)

        # 두 리랭커 모두 호출됨
        mock_colbert_reranker.rerank.assert_called_once()
        mock_llm_reranker.rerank.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_reranker(
        self,
        sample_search_results: list[SearchResult],
        mock_colbert_reranker: IReranker,
        mock_llm_reranker: IReranker,
        default_config: RerankerChainConfig,
    ) -> None:
        """리랭커 동적 제거"""
        chain = RerankerChain(
            rerankers=[mock_colbert_reranker, mock_llm_reranker],
            config=default_config,
        )

        # ColBERT 리랭커 제거
        chain.remove_reranker("colbert")

        await chain.rerank("테스트", sample_search_results)

        # ColBERT 호출 안 됨
        mock_colbert_reranker.rerank.assert_not_called()
        # LLM만 호출됨
        mock_llm_reranker.rerank.assert_called_once()


# ========================================
# 설정 검증 테스트
# ========================================


class TestConfigValidation:
    """설정 값 검증 테스트"""

    def test_valid_config_creation(self) -> None:
        """유효한 설정 생성"""
        config = RerankerChainConfig(
            enabled=True,
            continue_on_error=True,
            log_intermediate_results=True,
        )

        assert config.enabled is True
        assert config.continue_on_error is True
        assert config.log_intermediate_results is True

    def test_default_config_values(self) -> None:
        """기본 설정 값 확인"""
        config = RerankerChainConfig()

        assert config.enabled is True
        assert config.continue_on_error is True
        assert config.log_intermediate_results is False
