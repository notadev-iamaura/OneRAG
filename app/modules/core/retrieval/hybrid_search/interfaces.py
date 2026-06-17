"""
하이브리드 검색 인터페이스

벡터 검색과 그래프 검색을 결합하는 전략의 인터페이스를 정의합니다.
RRF(Reciprocal Rank Fusion) 알고리즘을 사용하여 두 검색 결과를 결합합니다.

주요 컴포넌트:
- HybridSearchResult: 하이브리드 검색 결과 데이터 클래스
- IHybridSearchStrategy: 하이브리드 검색 전략 프로토콜

생성일: 2026-01-05
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..interfaces import SearchResult


@dataclass
class HybridSearchResult:
    """
    하이브리드 검색 결과

    벡터 검색과 그래프 검색 결과를 RRF로 결합한 최종 결과입니다.

    Attributes:
        documents: 결합된 검색 결과 목록 (점수순 정렬)
        vector_count: 벡터 검색에서 가져온 문서 수
        graph_count: 그래프 검색에서 가져온 문서 수
        total_score: 전체 결합 점수 (평균 hybrid_score)
        metadata: 추가 메타데이터 (가중치, 쿼리 등)

    사용 예시:
        >>> result = HybridSearchResult(
        ...     documents=[SearchResult(id="doc1", content="...", score=0.9, metadata={})],
        ...     vector_count=5,
        ...     graph_count=3,
        ...     total_score=0.85,
        ... )
        >>> print(f"총 {len(result.documents)}개 결과")
    """

    documents: list[SearchResult]
    vector_count: int = 0
    graph_count: int = 0
    total_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        """문자열 표현"""
        return (
            f"HybridSearchResult("
            f"documents={len(self.documents)}, "
            f"vector_count={self.vector_count}, "
            f"graph_count={self.graph_count}, "
            f"total_score={self.total_score:.3f})"
        )


@runtime_checkable
class IHybridSearchStrategy(Protocol):
    """
    하이브리드 검색 전략 인터페이스 (Protocol 기반)

    벡터 검색과 그래프 검색을 결합하는 전략을 정의합니다.
    구현체는 RRF, 가중 평균 등 다양한 결합 알고리즘을 사용할 수 있습니다.

    구현 예시:
    - VectorGraphHybridSearch: 벡터+그래프 RRF 결합 검색
    - VectorOnlySearch: 벡터 검색만 사용 (그래프 비활성화)

    Examples:
        >>> result = await hybrid_search.search("RAG란 무엇인가요?", top_k=10)
    """

    async def search(
        self,
        query: str,
        top_k: int = 10,
        vector_weight: float = 0.6,
        graph_weight: float = 0.4,
        **kwargs: Any,
    ) -> HybridSearchResult:
        """
        하이브리드 검색 수행

        벡터 검색과 그래프 검색을 병렬로 실행하고
        가중치 기반 RRF 알고리즘으로 결과를 결합합니다.

        Args:
            query: 검색 쿼리 문자열
            top_k: 반환할 최대 결과 수
            vector_weight: 벡터 검색 가중치 (0.0 ~ 1.0, 기본값: 0.6)
            graph_weight: 그래프 검색 가중치 (0.0 ~ 1.0, 기본값: 0.4)
            **kwargs: 추가 파라미터 (필터, 엔티티 타입 등)

        Returns:
            HybridSearchResult: 결합된 검색 결과

        Notes:
            - vector_weight + graph_weight는 자동으로 정규화됩니다
            - graph_store가 없으면 벡터 검색만 수행됩니다
        """
        ...

    def get_config(self) -> dict[str, Any]:
        """
        현재 설정 반환

        Returns:
            설정 딕셔너리 (vector_weight, graph_weight, rrf_k 등)
        """
        ...
