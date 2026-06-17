"""
VectorGraphHybridSearch - 벡터+그래프 결합 검색

벡터 검색(Dense/BM25)과 그래프 검색을 RRF(Reciprocal Rank Fusion)로 결합하여
더 정확한 검색 결과를 제공합니다.

주요 기능:
- 벡터 검색과 그래프 검색 병렬 실행
- RRF(Reciprocal Rank Fusion)로 결과 결합
- 가중치 기반 점수 조정
- 그래프 비활성화 시 벡터 전용 모드

RRF 공식:
    score = sum(weight * 1/(k + rank))
    - k: RRF 상수 (기본값: 60)
    - rank: 각 검색 소스에서의 순위 (1부터 시작)

사용 예시:
    retriever = WeaviateRetriever(config)
    graph_store = NetworkXGraphStore()
    hybrid = VectorGraphHybridSearch(retriever, graph_store, config)
    result = await hybrid.search("RAG란 무엇인가요?", top_k=10)

생성일: 2026-01-05
"""
from __future__ import annotations

from typing import Any

from app.lib.logger import get_logger
from app.modules.core.graph.interfaces import IGraphStore
from app.modules.core.retrieval.interfaces import IRetriever, SearchResult

from .interfaces import HybridSearchResult, IHybridSearchStrategy

logger = get_logger(__name__)


class VectorGraphHybridSearch(IHybridSearchStrategy):
    """
    벡터+그래프 하이브리드 검색 구현체

    두 검색 소스의 결과를 RRF 알고리즘으로 결합합니다.
    IHybridSearchStrategy 프로토콜을 구현합니다.

    Attributes:
        _retriever: 벡터 검색기 (IRetriever)
        _graph_store: 그래프 저장소 (IGraphStore, 선택적)
        _default_vector_weight: 기본 벡터 검색 가중치
        _default_graph_weight: 기본 그래프 검색 가중치
        _rrf_k: RRF 상수 (k 값)
    """

    def __init__(
        self,
        retriever: IRetriever,
        graph_store: IGraphStore | None,
        config: dict[str, Any],
    ) -> None:
        """
        VectorGraphHybridSearch 초기화

        Args:
            retriever: 벡터 검색기 (필수)
            graph_store: 그래프 저장소 (없으면 벡터 전용 모드)
            config: 설정 딕셔너리
                - vector_weight: 벡터 검색 가중치 (기본값: 0.6)
                - graph_weight: 그래프 검색 가중치 (기본값: 0.4)
                - rrf_k: RRF 상수 (기본값: 60)
        """
        self._retriever = retriever
        self._graph_store = graph_store
        self._config = config

        # 가중치 및 RRF 상수 설정
        self._default_vector_weight = config.get("vector_weight", 0.6)
        self._default_graph_weight = config.get("graph_weight", 0.4)
        self._rrf_k = config.get("rrf_k", 60)

        # 모드 결정
        mode = "하이브리드" if graph_store else "벡터 전용"
        logger.info(
            f"VectorGraphHybridSearch 초기화: mode={mode}, "
            f"vector_weight={self._default_vector_weight}, "
            f"graph_weight={self._default_graph_weight}, "
            f"rrf_k={self._rrf_k}"
        )

    async def search(
        self,
        query: str,
        top_k: int = 10,
        vector_weight: float | None = None,
        graph_weight: float | None = None,
        **kwargs: Any,
    ) -> HybridSearchResult:
        """
        하이브리드 검색 수행

        벡터 검색과 그래프 검색을 실행하고 RRF로 결과를 결합합니다.

        Args:
            query: 검색 쿼리
            top_k: 반환할 최대 결과 수
            vector_weight: 벡터 검색 가중치 (None이면 기본값 사용)
            graph_weight: 그래프 검색 가중치 (None이면 기본값 사용)
            **kwargs: 추가 파라미터 (filters 등)

        Returns:
            HybridSearchResult: 결합된 검색 결과
        """
        # top_k가 0이면 빈 결과 반환
        if top_k <= 0:
            return HybridSearchResult(
                documents=[],
                vector_count=0,
                graph_count=0,
                total_score=0.0,
                metadata={"query": query},
            )

        # 가중치 설정 (파라미터 > 기본값)
        v_weight = (
            vector_weight if vector_weight is not None else self._default_vector_weight
        )
        g_weight = (
            graph_weight if graph_weight is not None else self._default_graph_weight
        )

        # 가중치 정규화 (합이 1이 되도록)
        total_weight = v_weight + g_weight
        if total_weight > 0:
            v_weight = v_weight / total_weight
            g_weight = g_weight / total_weight
        else:
            # 가중치 합이 0이면 벡터만 사용
            v_weight = 1.0
            g_weight = 0.0

        logger.info(
            f"하이브리드 검색 시작: query='{query}', top_k={top_k}, "
            f"vector_weight={v_weight:.2f}, graph_weight={g_weight:.2f}"
        )

        # 벡터 검색 실행
        vector_results = await self._vector_search(query, top_k * 2, **kwargs)
        vector_count = len(vector_results)

        # 그래프 검색 실행 (graph_store가 있고 가중치가 0보다 큰 경우)
        graph_results: list[SearchResult] = []
        graph_count = 0

        if self._graph_store is not None and g_weight > 0:
            graph_results = await self._graph_search(query, top_k * 2, **kwargs)
            graph_count = len(graph_results)

        # RRF로 결과 결합
        combined_docs = self._combine_with_rrf(
            vector_results=vector_results,
            graph_results=graph_results,
            vector_weight=v_weight,
            graph_weight=g_weight,
            top_k=top_k,
        )

        # 총 점수 계산 (hybrid_score 평균)
        total_score = 0.0
        if combined_docs:
            total_score = sum(
                doc.metadata.get("hybrid_score", 0) for doc in combined_docs
            ) / len(combined_docs)

        # 결과 구성
        result = HybridSearchResult(
            documents=combined_docs,
            vector_count=vector_count,
            graph_count=graph_count,
            total_score=total_score,
            metadata={
                "vector_weight": v_weight,
                "graph_weight": g_weight,
                "query": query,
                "rrf_k": self._rrf_k,
            },
        )

        logger.info(
            f"하이브리드 검색 완료: {len(combined_docs)}개 결과 "
            f"(벡터: {vector_count}, 그래프: {graph_count})"
        )

        return result

    async def _vector_search(
        self,
        query: str,
        top_k: int,
        **kwargs: Any,
    ) -> list[SearchResult]:
        """
        벡터 검색 수행

        Args:
            query: 검색 쿼리
            top_k: 최대 결과 수
            **kwargs: 추가 파라미터

        Returns:
            검색된 결과 목록
        """
        try:
            results = await self._retriever.search(query, top_k=top_k, **kwargs)
            logger.debug(f"벡터 검색: {len(results)}개 결과")
            return results
        except Exception as e:
            logger.error(f"벡터 검색 실패: {e}")
            return []

    async def _graph_search(
        self,
        query: str,
        top_k: int,
        **kwargs: Any,
    ) -> list[SearchResult]:
        """
        그래프 검색 수행

        그래프에서 엔티티를 검색하고 SearchResult로 변환합니다.

        Args:
            query: 검색 쿼리
            top_k: 최대 결과 수
            **kwargs: 추가 파라미터

        Returns:
            검색된 결과 목록
        """
        if self._graph_store is None:
            return []

        try:
            # 그래프 검색
            graph_result = await self._graph_store.search(query, top_k=top_k)

            # 엔티티에서 문서 ID 추출하여 SearchResult로 변환
            results: list[SearchResult] = []
            for idx, entity in enumerate(graph_result.entities):
                doc_id = entity.properties.get("doc_id")
                if doc_id:
                    # SearchResult 생성 (그래프 점수 기반)
                    results.append(
                        SearchResult(
                            id=str(doc_id),
                            content=f"[그래프] {entity.name}",
                            score=graph_result.score * (1.0 / (idx + 1)),  # 순위 감소
                            metadata={
                                "source": "graph",
                                "entity_id": entity.id,
                                "entity_type": entity.type,
                                "graph_score": graph_result.score,
                            },
                        )
                    )

            logger.debug(f"그래프 검색: {len(results)}개 결과")
            return results

        except Exception as e:
            logger.error(f"그래프 검색 실패: {e}")
            return []

    def _combine_with_rrf(
        self,
        vector_results: list[SearchResult],
        graph_results: list[SearchResult],
        vector_weight: float,
        graph_weight: float,
        top_k: int,
    ) -> list[SearchResult]:
        """
        RRF(Reciprocal Rank Fusion)로 결과 결합

        Args:
            vector_results: 벡터 검색 결과
            graph_results: 그래프 검색 결과
            vector_weight: 벡터 가중치
            graph_weight: 그래프 가중치
            top_k: 반환할 최대 결과 수

        Returns:
            결합된 결과 목록 (hybrid_score 내림차순 정렬)
        """
        # 랭크 딕셔너리 생성 (1-based rank)
        vector_ranks: dict[str, int] = {
            result.id: rank + 1 for rank, result in enumerate(vector_results)
        }
        graph_ranks: dict[str, int] = {
            result.id: rank + 1 for rank, result in enumerate(graph_results)
        }

        # RRF 점수 계산
        rrf_scores = self._calculate_rrf_scores(
            vector_ranks=vector_ranks,
            graph_ranks=graph_ranks,
            vector_weight=vector_weight,
            graph_weight=graph_weight,
            k=self._rrf_k,
        )

        # 결과 딕셔너리 생성 (ID → SearchResult)
        all_results: dict[str, SearchResult] = {}
        for result in vector_results + graph_results:
            if result.id not in all_results:
                all_results[result.id] = result

        # RRF 점수 기준으로 정렬
        sorted_ids = sorted(
            rrf_scores.keys(),
            key=lambda x: rrf_scores[x],
            reverse=True,
        )[:top_k]

        # 결과 생성 (메타데이터에 hybrid_score 추가)
        combined_results: list[SearchResult] = []
        for doc_id in sorted_ids:
            if doc_id in all_results:
                result = all_results[doc_id]
                # 새로운 메타데이터 생성 (원본 보존)
                new_metadata = dict(result.metadata)
                new_metadata["hybrid_score"] = rrf_scores[doc_id]
                new_metadata["vector_rank"] = vector_ranks.get(doc_id)
                new_metadata["graph_rank"] = graph_ranks.get(doc_id)

                # SearchResult 재생성 (메타데이터 업데이트)
                combined_results.append(
                    SearchResult(
                        id=result.id,
                        content=result.content,
                        score=rrf_scores[doc_id],  # RRF 점수로 대체
                        metadata=new_metadata,
                    )
                )

        return combined_results

    def _calculate_rrf_scores(
        self,
        vector_ranks: dict[str, int],
        graph_ranks: dict[str, int],
        vector_weight: float,
        graph_weight: float,
        k: int = 60,
    ) -> dict[str, float]:
        """
        RRF 점수 계산

        RRF 공식: score = sum(weight * 1/(k + rank))

        Args:
            vector_ranks: 벡터 검색 랭크 (doc_id → rank, 1-based)
            graph_ranks: 그래프 검색 랭크 (doc_id → rank, 1-based)
            vector_weight: 벡터 가중치
            graph_weight: 그래프 가중치
            k: RRF 상수 (기본값: 60)

        Returns:
            RRF 점수 딕셔너리 (doc_id → score)
        """
        scores: dict[str, float] = {}

        # 모든 문서 ID 수집
        all_doc_ids = set(vector_ranks.keys()) | set(graph_ranks.keys())

        for doc_id in all_doc_ids:
            score = 0.0

            # 벡터 검색 RRF 점수
            if doc_id in vector_ranks:
                score += vector_weight * (1.0 / (k + vector_ranks[doc_id]))

            # 그래프 검색 RRF 점수
            if doc_id in graph_ranks:
                score += graph_weight * (1.0 / (k + graph_ranks[doc_id]))

            scores[doc_id] = score

        return scores

    def get_config(self) -> dict[str, Any]:
        """
        현재 설정 반환

        Returns:
            설정 딕셔너리 (vector_weight, graph_weight, rrf_k, graph_enabled)
        """
        return {
            "vector_weight": self._default_vector_weight,
            "graph_weight": self._default_graph_weight,
            "rrf_k": self._rrf_k,
            "graph_enabled": self._graph_store is not None,
        }
