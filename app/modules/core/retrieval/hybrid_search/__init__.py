"""
벡터+그래프 하이브리드 검색 모듈

벡터 검색과 그래프 검색을 결합하여 더 정확한 결과를 제공합니다.
RRF(Reciprocal Rank Fusion) 알고리즘을 사용하여 두 검색 결과를 결합합니다.

구성요소:
- IHybridSearchStrategy: 하이브리드 검색 전략 인터페이스 (Protocol)
- HybridSearchResult: 하이브리드 검색 결과 데이터 클래스
- VectorGraphHybridSearch: 벡터+그래프 결합 검색 구현체

사용 예시:
    from app.modules.core.retrieval.hybrid_search import (
        VectorGraphHybridSearch,
        HybridSearchResult,
    )

    # 하이브리드 검색 생성
    hybrid = VectorGraphHybridSearch(retriever, graph_store, config)
    result = await hybrid.search("RAG란 무엇인가요?", top_k=10)

    # 타입 체크
    if isinstance(hybrid, IHybridSearchStrategy):
        print("프로토콜 구현 확인")

생성일: 2026-01-05
"""
from .interfaces import HybridSearchResult, IHybridSearchStrategy
from .vector_graph_search import VectorGraphHybridSearch

__all__ = [
    "IHybridSearchStrategy",
    "HybridSearchResult",
    "VectorGraphHybridSearch",
]
