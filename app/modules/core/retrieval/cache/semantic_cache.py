"""
Semantic Cache Manager
쿼리 임베딩 유사도 기반 시맨틱 캐시

기능:
- 코사인 유사도 기반 유사 쿼리 캐시 히트
- LRU 캐시 정책으로 메모리 관리
- TTL 기반 자동 만료
- 보수적 임계값 설정 (false positive 최소화)

구현일: 2025-12-31
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

import numpy as np
from cachetools import LRUCache

from .....lib.logger import get_logger
from ..interfaces import SearchResult

logger = get_logger(__name__)


# ========================================
# 설정 스키마
# ========================================


@dataclass
class SemanticCacheConfig:
    """
    시맨틱 캐시 설정

    Attributes:
        enabled: 캐시 활성화 여부
        similarity_threshold: 코사인 유사도 임계값 (0.0-1.0)
        max_entries: 최대 캐시 엔트리 수
        ttl_seconds: 캐시 엔트리 TTL (초)
        embedding_dim: 임베딩 벡터 차원
    """

    enabled: bool = True
    similarity_threshold: float = 0.95
    max_entries: int = 1000
    ttl_seconds: int = 3600
    embedding_dim: int = 768

    def __post_init__(self) -> None:
        """설정값 검증"""
        if not 0.0 <= self.similarity_threshold <= 1.0:
            raise ValueError(
                f"similarity_threshold must be between 0.0 and 1.0, got {self.similarity_threshold}"
            )
        if self.max_entries <= 0:
            raise ValueError(
                f"max_entries must be positive, got {self.max_entries}"
            )
        if self.ttl_seconds <= 0:
            raise ValueError(
                f"ttl_seconds must be positive, got {self.ttl_seconds}"
            )


# ========================================
# 임베더 프로토콜
# ========================================


class Embedder(Protocol):
    """임베딩 함수 프로토콜 (동기 또는 비동기)"""

    async def __call__(self, text: str) -> list[float]:
        """텍스트를 임베딩 벡터로 변환"""
        ...


# ========================================
# 캐시 엔트리 데이터 클래스
# ========================================


@dataclass
class CacheEntry:
    """캐시 엔트리"""

    embedding: np.ndarray
    results: list[SearchResult]
    created_at: float
    query: str  # 디버깅용


# ========================================
# 시맨틱 캐시 매니저
# ========================================


class InMemorySemanticCache:
    """
    In-memory 시맨틱 캐시 매니저

    특징:
    - 쿼리 임베딩 유사도 기반 캐시 히트
    - LRU 정책으로 오래된 엔트리 자동 제거
    - TTL 기반 만료 처리
    - 에러 시 None 반환 (예외 전파 안 함)
    """

    def __init__(
        self,
        embedder: Embedder | Callable[[str], list[float]],
        config: SemanticCacheConfig,
    ):
        """
        Args:
            embedder: 텍스트 → 임베딩 변환 함수 (비동기)
            config: 시맨틱 캐시 설정
        """
        self.embedder = embedder
        self.config = config

        # LRU 캐시 (키: 해시, 값: CacheEntry — embedding은 CacheEntry에 포함)
        self._cache: LRUCache[str, CacheEntry] = LRUCache(maxsize=config.max_entries)

        # 통계
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "invalidations": 0,
            "embedder_errors": 0,
        }

        logger.info(
            f"InMemorySemanticCache 초기화: "
            f"threshold={config.similarity_threshold}, "
            f"max_entries={config.max_entries}, "
            f"ttl={config.ttl_seconds}s"
        )

    async def get(self, query: str) -> list[SearchResult] | None:
        """
        시맨틱 캐시에서 유사 쿼리 결과 조회

        Args:
            query: 검색 쿼리

        Returns:
            캐시된 결과 (없으면 None)
        """
        # 비활성화 상태면 바이패스
        if not self.config.enabled:
            return None

        try:
            # 쿼리 임베딩 생성
            query_embedding = await self._get_embedding(query)
            if query_embedding is None:
                self._stats["misses"] += 1
                return None

            # 캐시에서 유사 쿼리 검색
            best_match, best_key = self._find_similar_entry(query_embedding)

            if best_match is not None and best_key is not None:
                # LRU 캐시 접근 갱신 (recency update)
                # cachetools LRUCache는 __getitem__을 통해 접근 시 자동으로 순서 갱신
                _ = self._cache[best_key]

                self._stats["hits"] += 1
                logger.debug(f"시맨틱 캐시 히트: '{query[:30]}...'")
                return best_match.results
            else:
                self._stats["misses"] += 1
                return None

        except Exception as e:
            logger.warning(f"시맨틱 캐시 조회 오류: {e}")
            self._stats["misses"] += 1
            return None

    async def set(
        self,
        query: str,
        results: list[SearchResult],
        ttl: int | None = None,
    ) -> None:
        """
        시맨틱 캐시에 결과 저장

        Args:
            query: 검색 쿼리
            results: 저장할 검색 결과
            ttl: TTL (초, None이면 기본값 사용)
        """
        # 비활성화 상태면 저장 안 함
        if not self.config.enabled:
            return

        try:
            # 쿼리 임베딩 생성
            query_embedding = await self._get_embedding(query)
            if query_embedding is None:
                return

            # 캐시 키 생성 (쿼리 해시)
            cache_key = self._generate_key(query)

            # 캐시 엔트리 생성
            entry = CacheEntry(
                embedding=query_embedding,
                results=results,
                created_at=time.time(),
                query=query,
            )

            # LRU 캐시에 저장 (embedding은 CacheEntry에 포함되어 함께 관리/퇴출됨)
            self._cache[cache_key] = entry

            self._stats["sets"] += 1
            logger.debug(f"시맨틱 캐시 저장: '{query[:30]}...' (결과 {len(results)}개)")

        except Exception as e:
            logger.warning(f"시맨틱 캐시 저장 오류: {e}")

    async def invalidate(self, query: str) -> None:
        """
        특정 쿼리의 캐시 무효화

        Args:
            query: 무효화할 쿼리
        """
        cache_key = self._generate_key(query)

        if cache_key in self._cache:
            del self._cache[cache_key]

        self._stats["invalidations"] += 1
        logger.debug(f"시맨틱 캐시 무효화: '{query[:30]}...'")

    async def clear(self) -> None:
        """모든 캐시 클리어"""
        self._cache.clear()
        logger.info("시맨틱 캐시 전체 클리어")

    def get_stats(self) -> dict[str, Any]:
        """
        캐시 통계 반환

        Returns:
            히트/미스 통계, 히트율 등
        """
        total_requests = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total_requests if total_requests > 0 else 0.0

        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "total_entries": len(self._cache),
            "hit_rate": round(hit_rate, 4),
            "sets": self._stats["sets"],
            "invalidations": self._stats["invalidations"],
            "embedder_errors": self._stats["embedder_errors"],
            "config": {
                "enabled": self.config.enabled,
                "similarity_threshold": self.config.similarity_threshold,
                "max_entries": self.config.max_entries,
                "ttl_seconds": self.config.ttl_seconds,
            },
        }

    # ========================================
    # Private 메서드
    # ========================================

    async def _get_embedding(self, text: str) -> np.ndarray | None:
        """
        텍스트 임베딩 생성

        Args:
            text: 임베딩할 텍스트

        Returns:
            임베딩 벡터 (오류 시 None)
        """
        try:
            # embedder 호출 (비동기 또는 동기 함수 모두 지원)
            result = self.embedder(text)

            # awaitable이면 await
            if hasattr(result, "__await__"):
                embedding_list = await result
            else:
                embedding_list = result

            return cast(np.ndarray, np.array(embedding_list, dtype=np.float32))

        except Exception as e:
            logger.warning(f"임베딩 생성 오류: {e}")
            self._stats["embedder_errors"] += 1
            return None

    def _find_similar_entry(self, query_embedding: np.ndarray) -> tuple[CacheEntry | None, str | None]:
        """
        캐시에서 유사한 쿼리 검색

        Args:
            query_embedding: 쿼리 임베딩 벡터

        Returns:
            (유사도 임계값을 넘는 가장 유사한 엔트리, 해당 캐시 키) 또는 (None, None)
        """
        best_entry: CacheEntry | None = None
        best_key: str | None = None
        best_similarity: float = 0.0
        current_time = time.time()

        # 만료된 엔트리 수집 (순회 중 삭제 방지)
        expired_keys: list[str] = []

        for cache_key, entry in self._cache.items():
            # TTL 체크
            if current_time - entry.created_at > self.config.ttl_seconds:
                expired_keys.append(cache_key)
                continue

            # 코사인 유사도 계산
            cached_embedding = entry.embedding
            similarity = self._cosine_similarity(query_embedding, cached_embedding)

            if similarity >= self.config.similarity_threshold:
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_entry = entry
                    best_key = cache_key

        # 만료된 엔트리 정리
        for key in expired_keys:
            if key in self._cache:
                del self._cache[key]

        return best_entry, best_key

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """
        코사인 유사도 계산

        Args:
            a: 벡터 A
            b: 벡터 B

        Returns:
            코사인 유사도 (0.0-1.0)
        """
        dot_product = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return float(dot_product / (norm_a * norm_b))

    @staticmethod
    def _generate_key(query: str) -> str:
        """
        캐시 키 생성 (쿼리 해시)

        Args:
            query: 쿼리 문자열

        Returns:
            해시 기반 캐시 키
        """
        import hashlib
        return hashlib.sha256(query.encode()).hexdigest()
