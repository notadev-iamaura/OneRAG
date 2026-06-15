"""
Retrieval Module Interfaces
검색 모듈 인터페이스 정의 (Protocol 기반)

이 파일은 Retriever, Reranker, CacheManager의 표준 인터페이스를 정의합니다.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class SearchResult:
    """검색 결과 데이터 클래스"""

    id: str
    content: str
    score: float
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        # 하위 호환성을 위해 속성으로도 접근 가능하게 설정
        for key, value in self.metadata.items():
            setattr(self, key, value)


class IRetriever(Protocol):
    """
    벡터 검색 인터페이스 (Protocol 기반)

    구현 예시:
    - MongoDBRetriever: MongoDB Atlas 하이브리드 검색 (Dense + BM25)
    - MockRetriever: 테스트용 모의 검색
    """

    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        alpha: float | None = None,
    ) -> list[SearchResult]:
        """
        쿼리에 대한 벡터 검색 수행

        Args:
            query: 검색 쿼리 문자열
            top_k: 반환할 최대 결과 수
            filters: 메타데이터 필터링 조건
            alpha: 하이브리드 가중치 동적 오버라이드(선택). None이면 구현체의
                기본 alpha를 사용한다. dense-only 구현체(pgvector/mongodb 등)는
                이 파라미터를 받되 무시한다(시그니처 호환성 유지용).

        Returns:
            검색 결과 리스트 (SearchResult)
        """
        ...

    async def health_check(self) -> bool:
        """
        검색 엔진 Health Check

        Returns:
            정상 동작 여부 (True/False)
        """
        ...


class IReranker(Protocol):
    """
    리랭킹 인터페이스 (Protocol 기반)

    구현 예시:
    - JinaReranker: Jina AI Reranker API
    - CohereReranker: Cohere Rerank API
    - LLMReranker: LLM 기반 리랭킹
    - NoOpReranker: 리랭킹 없이 원본 반환 (pass-through)
    """

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_n: int | None = None,
    ) -> list[SearchResult]:
        """
        검색 결과 리랭킹

        Args:
            query: 원본 쿼리 문자열
            results: 초기 검색 결과 리스트
            top_n: 리랭킹 후 반환할 최대 결과 수 (None이면 전체)

        Returns:
            리랭킹된 결과 리스트 (점수 재조정됨)
        """
        ...

    def supports_caching(self) -> bool:
        """
        캐싱 지원 여부 반환

        Returns:
            캐싱 가능 여부 (True/False)
        """
        ...


@runtime_checkable
class IMultiQueryRetriever(Protocol):
    """
    다중 쿼리 검색 및 RRF 병합 인터페이스 (Protocol 기반)

    구현 예시:
    - RetrievalOrchestrator: RRF 기반 다중 쿼리 병합
    - MongoDBRetriever: 직접 _search_and_merge 구현 (향후)

    이 Protocol은 hasattr 기반 duck-typing을 대체합니다.
    """

    async def _search_and_merge(
        self,
        queries: list[str],
        top_k: int,
        filters: dict[str, Any] | None = None,
        weights: list[float] | None = None,
        use_rrf: bool = True,
    ) -> list[SearchResult]:
        """
        다중 쿼리 병렬 검색 및 RRF 기반 결과 병합

        Args:
            queries: 검색할 쿼리 리스트
            top_k: 최종 반환할 결과 수
            filters: 검색 필터
            weights: 각 쿼리의 가중치 (기본값: 모두 1.0)
            use_rrf: RRF 사용 여부 (False면 단순 점수 병합)

        Returns:
            RRF 점수로 정렬된 검색 결과 리스트
        """
        ...


class ICacheManager(Protocol):
    """
    캐시 관리자 인터페이스 (Protocol 기반)

    구현 예시:
    - MemoryCacheManager: In-memory LRU 캐시
    - RedisCacheManager: Redis 기반 분산 캐시
    - NoOpCacheManager: 캐싱 비활성화 (pass-through)
    """

    async def get(self, key: str) -> list[SearchResult] | None:
        """
        캐시에서 검색 결과 조회

        Args:
            key: 캐시 키 (보통 쿼리 해시)

        Returns:
            캐시된 검색 결과 (없으면 None)
        """
        ...

    async def set(
        self,
        key: str,
        value: list[SearchResult],
        ttl: int | None = None,
    ) -> None:
        """
        검색 결과를 캐시에 저장

        Args:
            key: 캐시 키
            value: 저장할 검색 결과
            ttl: Time-To-Live (초 단위, None이면 기본값 사용)
        """
        ...

    async def invalidate(self, key: str) -> None:
        """
        특정 키의 캐시 무효화

        Args:
            key: 무효화할 캐시 키
        """
        ...

    async def clear(self) -> None:
        """
        모든 캐시 클리어
        """
        ...

    def get_stats(self) -> dict[str, Any]:
        """
        캐시 통계 반환

        Returns:
            캐시 히트율, 미스율 등의 통계 딕셔너리
        """
        ...


# ========================================
# Abstract Base Classes (선택적 사용)
# ========================================
# Protocol은 Duck Typing을 강제하지 않으므로,
# 엄격한 타입 체킹이 필요한 경우 ABC를 함께 사용할 수 있습니다.


class BaseRetriever(ABC):
    """Retriever ABC (엄격한 타입 체킹용)"""

    @abstractmethod
    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        alpha: float | None = None,
    ) -> list[SearchResult]:
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        pass


class BaseReranker(ABC):
    """Reranker ABC (엄격한 타입 체킹용)"""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_n: int | None = None,
    ) -> list[SearchResult]:
        pass

    @abstractmethod
    def supports_caching(self) -> bool:
        pass


class BaseCacheManager(ABC):
    """CacheManager ABC (엄격한 타입 체킹용)"""

    @abstractmethod
    async def get(self, key: str) -> list[SearchResult] | None:
        pass

    @abstractmethod
    async def set(
        self,
        key: str,
        value: list[SearchResult],
        ttl: int | None = None,
    ) -> None:
        pass

    @abstractmethod
    async def invalidate(self, key: str) -> None:
        pass

    @abstractmethod
    async def clear(self) -> None:
        pass

    @abstractmethod
    def get_stats(self) -> dict[str, Any]:
        pass
