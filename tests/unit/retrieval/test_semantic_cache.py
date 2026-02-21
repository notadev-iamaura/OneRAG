"""
InMemorySemanticCache 단위 테스트

쿼리 임베딩 유사도 기반 시맨틱 캐시 검증.

테스트 케이스:
1. 캐시 저장 및 조회 (정확 일치)
2. 유사 쿼리 캐시 히트 (코사인 유사도)
3. 유사도 임계값 미달 시 캐시 미스
4. TTL 만료 처리
5. LRU 캐시 용량 제한
6. 빈 캐시 조회
7. 통계 정보 반환

구현일: 2025-12-31
TDD Phase: RED (실패 테스트 작성)
"""

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock

import numpy as np
import pytest

# TDD RED: 아직 존재하지 않는 모듈 임포트 (이 테스트는 실패해야 함)
from app.modules.core.retrieval.cache.semantic_cache import (
    InMemorySemanticCache,
    SemanticCacheConfig,
)
from app.modules.core.retrieval.interfaces import SearchResult

# ========================================
# 테스트 픽스처
# ========================================


@pytest.fixture
def mock_embedder() -> Callable[[str], list[float]]:
    """
    테스트용 Mock 임베딩 함수

    단순히 문자열 해시 기반으로 일관된 벡터 반환.
    실제 의미론적 유사도 테스트를 위해 미리 정의된 유사 쿼리 그룹 사용.
    """
    # 미리 정의된 유사 쿼리 그룹 (실제 테스트에서 사용)
    # 코사인 유사도 기준으로 벡터 설계
    similar_queries = {
        "서울 맛집 추천": np.array([1.0, 0.0, 0.0, 0.0, 0.0]),
        "서울 맛집 추천해줘": np.array([0.98, 0.2, 0.0, 0.0, 0.0]),  # ~97% 유사
        "서울 레스토랑 추천": np.array([0.95, 0.31, 0.0, 0.0, 0.0]),   # ~95% 유사
        "부산 맛집 추천": np.array([0.5, 0.5, 0.5, 0.5, 0.0]),       # ~50% 유사
        "호텔 가격 문의": np.array([0.0, 1.0, 0.0, 0.0, 0.0]),        # 0% 유사 (직교)
        # LRU 테스트용 직교 벡터들 (서로 0% 유사, 다른 쿼리들과도 직교)
        "쿼리1": np.array([0.0, 0.0, 1.0, 0.0, 0.0]),
        "쿼리2": np.array([0.0, 0.0, 0.0, 1.0, 0.0]),
        "쿼리3": np.array([0.0, 0.0, 0.0, 0.0, 1.0]),
        "쿼리4": np.array([0.0, 0.0, 0.5, 0.5, 0.0]),  # 쿼리1, 2, 3과 다름
    }

    def embed(query: str) -> list[float]:
        if query in similar_queries:
            return similar_queries[query].tolist()
        # 알 수 없는 쿼리는 해시 기반 직교 벡터 생성
        # 각 쿼리마다 다른 차원에 1을 배치하여 직교성 보장
        np.random.seed(hash(query) % 2**32)
        vec = np.zeros(5)
        vec[hash(query) % 5] = 1.0
        return vec.tolist()

    return embed


@pytest.fixture
def async_mock_embedder(mock_embedder: Callable[[str], list[float]]) -> AsyncMock:
    """비동기 Mock 임베딩 함수"""
    async_embedder = AsyncMock()
    async_embedder.side_effect = lambda q: mock_embedder(q)
    return async_embedder


@pytest.fixture
def default_config() -> SemanticCacheConfig:
    """기본 설정 (보수적 초기값)"""
    return SemanticCacheConfig(
        enabled=True,
        similarity_threshold=0.95,  # 95% 유사도 (보수적)
        max_entries=1000,
        ttl_seconds=3600,           # 1시간
        embedding_dim=5,            # 테스트용 작은 차원
    )


@pytest.fixture
def sample_search_results() -> list[SearchResult]:
    """테스트용 검색 결과"""
    return [
        SearchResult(
            id="doc_1",
            content="서울 맛집 A의 특징입니다.",
            score=0.95,
            metadata={"name": "맛집 A", "category": "restaurant"},
        ),
        SearchResult(
            id="doc_2",
            content="서울 맛집 B의 가격 정보입니다.",
            score=0.90,
            metadata={"name": "맛집 B", "category": "restaurant"},
        ),
    ]


# ========================================
# 기본 동작 테스트
# ========================================


class TestSemanticCacheBasicOperations:
    """시맨틱 캐시 기본 동작 테스트"""

    @pytest.mark.asyncio
    async def test_cache_set_and_get_exact_match(
        self,
        async_mock_embedder: AsyncMock,
        default_config: SemanticCacheConfig,
        sample_search_results: list[SearchResult],
    ) -> None:
        """정확히 동일한 쿼리로 캐시 저장 및 조회"""
        cache = InMemorySemanticCache(
            embedder=async_mock_embedder,
            config=default_config,
        )

        query = "서울 맛집 추천"

        # 캐시 저장
        await cache.set(query, sample_search_results)

        # 동일 쿼리로 조회
        result = await cache.get(query)

        assert result is not None
        assert len(result) == 2
        assert result[0].id == "doc_1"
        assert result[1].id == "doc_2"

    @pytest.mark.asyncio
    async def test_cache_miss_empty_cache(
        self,
        async_mock_embedder: AsyncMock,
        default_config: SemanticCacheConfig,
    ) -> None:
        """빈 캐시에서 조회 시 None 반환"""
        cache = InMemorySemanticCache(
            embedder=async_mock_embedder,
            config=default_config,
        )

        result = await cache.get("서울 맛집 추천")

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_invalidate(
        self,
        async_mock_embedder: AsyncMock,
        default_config: SemanticCacheConfig,
        sample_search_results: list[SearchResult],
    ) -> None:
        """캐시 무효화 테스트"""
        cache = InMemorySemanticCache(
            embedder=async_mock_embedder,
            config=default_config,
        )

        query = "서울 맛집 추천"
        await cache.set(query, sample_search_results)

        # 캐시 무효화
        await cache.invalidate(query)

        # 조회 시 None
        result = await cache.get(query)
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_clear(
        self,
        async_mock_embedder: AsyncMock,
        default_config: SemanticCacheConfig,
        sample_search_results: list[SearchResult],
    ) -> None:
        """전체 캐시 클리어 테스트"""
        cache = InMemorySemanticCache(
            embedder=async_mock_embedder,
            config=default_config,
        )

        # 여러 쿼리 캐시 저장
        await cache.set("쿼리1", sample_search_results)
        await cache.set("쿼리2", sample_search_results)

        # 전체 클리어
        await cache.clear()

        # 모든 캐시가 비어 있음
        assert await cache.get("쿼리1") is None
        assert await cache.get("쿼리2") is None


# ========================================
# 시맨틱 유사도 테스트
# ========================================


class TestSemanticSimilarity:
    """시맨틱 유사도 기반 캐시 히트 테스트"""

    @pytest.mark.asyncio
    async def test_similar_query_cache_hit(
        self,
        async_mock_embedder: AsyncMock,
        sample_search_results: list[SearchResult],
    ) -> None:
        """유사한 쿼리로 캐시 히트 (임계값 이상)"""
        # 낮은 임계값으로 유사 쿼리 허용
        config = SemanticCacheConfig(
            enabled=True,
            similarity_threshold=0.90,  # 90%
            max_entries=1000,
            ttl_seconds=3600,
            embedding_dim=5,
        )
        cache = InMemorySemanticCache(
            embedder=async_mock_embedder,
            config=config,
        )

        # 원본 쿼리 저장
        await cache.set("서울 맛집 추천", sample_search_results)

        # 유사 쿼리로 조회 (캐시 히트 예상)
        result = await cache.get("서울 맛집 추천해줘")

        assert result is not None
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_dissimilar_query_cache_miss(
        self,
        async_mock_embedder: AsyncMock,
        default_config: SemanticCacheConfig,
        sample_search_results: list[SearchResult],
    ) -> None:
        """다른 쿼리는 캐시 미스 (임계값 미달)"""
        cache = InMemorySemanticCache(
            embedder=async_mock_embedder,
            config=default_config,
        )

        # 원본 쿼리 저장
        await cache.set("서울 맛집 추천", sample_search_results)

        # 완전히 다른 쿼리로 조회 (캐시 미스 예상)
        result = await cache.get("호텔 가격 문의")

        assert result is None

    @pytest.mark.asyncio
    async def test_threshold_boundary_exact(
        self,
        async_mock_embedder: AsyncMock,
        sample_search_results: list[SearchResult],
    ) -> None:
        """임계값 경계 테스트 (정확히 임계값인 경우)"""
        # 매우 높은 임계값
        config = SemanticCacheConfig(
            enabled=True,
            similarity_threshold=0.99,  # 99%
            max_entries=1000,
            ttl_seconds=3600,
            embedding_dim=5,
        )
        cache = InMemorySemanticCache(
            embedder=async_mock_embedder,
            config=config,
        )

        await cache.set("서울 맛집 추천", sample_search_results)

        # 약간 다른 쿼리는 미스 (99% 미달)
        result = await cache.get("서울 레스토랑 추천")

        assert result is None


# ========================================
# TTL 및 만료 테스트
# ========================================


class TestTTLExpiration:
    """TTL(Time-To-Live) 만료 처리 테스트"""

    @pytest.mark.asyncio
    async def test_cache_entry_expires_after_ttl(
        self,
        async_mock_embedder: AsyncMock,
        sample_search_results: list[SearchResult],
    ) -> None:
        """TTL 이후 캐시 엔트리 만료"""
        # 짧은 TTL 설정 (1초)
        config = SemanticCacheConfig(
            enabled=True,
            similarity_threshold=0.95,
            max_entries=1000,
            ttl_seconds=0.3,
            embedding_dim=5,
        )
        cache = InMemorySemanticCache(
            embedder=async_mock_embedder,
            config=config,
        )

        query = "서울 맛집 추천"
        await cache.set(query, sample_search_results)

        # 즉시 조회 시 캐시 히트
        result1 = await cache.get(query)
        assert result1 is not None

        # TTL 대기 후 조회 시 캐시 미스
        await asyncio.sleep(0.5)
        result2 = await cache.get(query)
        assert result2 is None

    @pytest.mark.asyncio
    async def test_cache_entry_valid_before_ttl(
        self,
        async_mock_embedder: AsyncMock,
        sample_search_results: list[SearchResult],
    ) -> None:
        """TTL 이전에는 캐시 유효"""
        config = SemanticCacheConfig(
            enabled=True,
            similarity_threshold=0.95,
            max_entries=1000,
            ttl_seconds=60,  # 60초
            embedding_dim=5,
        )
        cache = InMemorySemanticCache(
            embedder=async_mock_embedder,
            config=config,
        )

        query = "서울 맛집 추천"
        await cache.set(query, sample_search_results)

        # 짧은 대기 후에도 캐시 유효
        await asyncio.sleep(0.1)
        result = await cache.get(query)
        assert result is not None


# ========================================
# LRU 캐시 용량 테스트
# ========================================


class TestLRUCapacity:
    """LRU 캐시 용량 제한 테스트"""

    @pytest.mark.asyncio
    async def test_lru_eviction_oldest_entry(
        self,
        async_mock_embedder: AsyncMock,
        sample_search_results: list[SearchResult],
    ) -> None:
        """용량 초과 시 가장 오래된 엔트리 제거"""
        config = SemanticCacheConfig(
            enabled=True,
            similarity_threshold=0.95,
            max_entries=2,  # 최대 2개
            ttl_seconds=3600,
            embedding_dim=5,
        )
        cache = InMemorySemanticCache(
            embedder=async_mock_embedder,
            config=config,
        )

        # 3개 저장 (2개 용량 초과)
        await cache.set("쿼리1", sample_search_results)
        await cache.set("쿼리2", sample_search_results)
        await cache.set("쿼리3", sample_search_results)

        # 가장 오래된 쿼리1이 제거됨
        assert await cache.get("쿼리1") is None
        assert await cache.get("쿼리2") is not None
        assert await cache.get("쿼리3") is not None

    @pytest.mark.asyncio
    async def test_lru_access_updates_recency(
        self,
        async_mock_embedder: AsyncMock,
        sample_search_results: list[SearchResult],
    ) -> None:
        """접근 시 최근 사용으로 갱신"""
        config = SemanticCacheConfig(
            enabled=True,
            similarity_threshold=0.95,
            max_entries=2,
            ttl_seconds=3600,
            embedding_dim=5,
        )
        cache = InMemorySemanticCache(
            embedder=async_mock_embedder,
            config=config,
        )

        await cache.set("쿼리1", sample_search_results)
        await cache.set("쿼리2", sample_search_results)

        # 쿼리1 접근하여 최근 사용으로 갱신
        await cache.get("쿼리1")

        # 새 쿼리 추가 시 쿼리2가 제거됨
        await cache.set("쿼리3", sample_search_results)

        assert await cache.get("쿼리1") is not None  # 최근 접근으로 유지
        assert await cache.get("쿼리2") is None       # LRU로 제거
        assert await cache.get("쿼리3") is not None


# ========================================
# 통계 및 모니터링 테스트
# ========================================


class TestCacheStatistics:
    """캐시 통계 정보 테스트"""

    @pytest.mark.asyncio
    async def test_get_stats_initial(
        self,
        async_mock_embedder: AsyncMock,
        default_config: SemanticCacheConfig,
    ) -> None:
        """초기 통계 정보"""
        cache = InMemorySemanticCache(
            embedder=async_mock_embedder,
            config=default_config,
        )

        stats = cache.get_stats()

        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["total_entries"] == 0
        assert stats["hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_get_stats_after_operations(
        self,
        async_mock_embedder: AsyncMock,
        default_config: SemanticCacheConfig,
        sample_search_results: list[SearchResult],
    ) -> None:
        """캐시 조작 후 통계 정보"""
        cache = InMemorySemanticCache(
            embedder=async_mock_embedder,
            config=default_config,
        )

        # 캐시 저장
        await cache.set("쿼리1", sample_search_results)

        # 캐시 히트
        await cache.get("쿼리1")

        # 캐시 미스 - mock_embedder에 정의된 직교 벡터 사용
        # "호텔 가격 문의"은 [0, 1, 0, 0, 0]으로 "쿼리1" [0, 0, 1, 0, 0]과 직교 (유사도 0%)
        await cache.get("호텔 가격 문의")

        stats = cache.get_stats()

        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["total_entries"] == 1
        assert stats["hit_rate"] == 0.5  # 1/2


# ========================================
# 에러 처리 테스트
# ========================================


class TestErrorHandling:
    """에러 처리 및 예외 상황 테스트"""

    @pytest.mark.asyncio
    async def test_embedder_failure_returns_none(
        self,
        default_config: SemanticCacheConfig,
        sample_search_results: list[SearchResult],
    ) -> None:
        """임베더 실패 시 None 반환 (예외 전파 안 함)"""
        failing_embedder = AsyncMock(side_effect=Exception("Embedding failed"))

        cache = InMemorySemanticCache(
            embedder=failing_embedder,
            config=default_config,
        )

        # 저장 시도 - 실패해도 예외 전파 안 함
        await cache.set("쿼리", sample_search_results)

        # 조회 시도 - 실패해도 None 반환
        result = await cache.get("쿼리")
        assert result is None

    @pytest.mark.asyncio
    async def test_disabled_cache_bypassed(
        self,
        async_mock_embedder: AsyncMock,
        sample_search_results: list[SearchResult],
    ) -> None:
        """비활성화된 캐시는 바이패스"""
        config = SemanticCacheConfig(
            enabled=False,  # 비활성화
            similarity_threshold=0.95,
            max_entries=1000,
            ttl_seconds=3600,
            embedding_dim=5,
        )
        cache = InMemorySemanticCache(
            embedder=async_mock_embedder,
            config=config,
        )

        await cache.set("쿼리", sample_search_results)
        result = await cache.get("쿼리")

        # 비활성화 상태이므로 항상 None
        assert result is None
        # 임베더 호출되지 않음
        async_mock_embedder.assert_not_called()


# ========================================
# 설정 검증 테스트
# ========================================


class TestConfigValidation:
    """설정 값 검증 테스트"""

    def test_invalid_similarity_threshold_too_low(self) -> None:
        """유사도 임계값이 너무 낮으면 에러"""
        with pytest.raises(ValueError, match="similarity_threshold"):
            SemanticCacheConfig(
                enabled=True,
                similarity_threshold=-0.1,  # 음수
                max_entries=1000,
                ttl_seconds=3600,
                embedding_dim=5,
            )

    def test_invalid_similarity_threshold_too_high(self) -> None:
        """유사도 임계값이 너무 높으면 에러"""
        with pytest.raises(ValueError, match="similarity_threshold"):
            SemanticCacheConfig(
                enabled=True,
                similarity_threshold=1.5,  # 1 초과
                max_entries=1000,
                ttl_seconds=3600,
                embedding_dim=5,
            )

    def test_invalid_max_entries(self) -> None:
        """최대 엔트리 수가 0 이하이면 에러"""
        with pytest.raises(ValueError, match="max_entries"):
            SemanticCacheConfig(
                enabled=True,
                similarity_threshold=0.95,
                max_entries=0,  # 0 이하
                ttl_seconds=3600,
                embedding_dim=5,
            )

    def test_invalid_ttl(self) -> None:
        """TTL이 0 이하이면 에러"""
        with pytest.raises(ValueError, match="ttl_seconds"):
            SemanticCacheConfig(
                enabled=True,
                similarity_threshold=0.95,
                max_entries=1000,
                ttl_seconds=0,  # 0 이하
                embedding_dim=5,
            )

    def test_valid_config_creation(self) -> None:
        """유효한 설정 생성"""
        config = SemanticCacheConfig(
            enabled=True,
            similarity_threshold=0.95,
            max_entries=1000,
            ttl_seconds=3600,
            embedding_dim=768,
        )

        assert config.enabled is True
        assert config.similarity_threshold == 0.95
        assert config.max_entries == 1000
        assert config.ttl_seconds == 3600
        assert config.embedding_dim == 768
