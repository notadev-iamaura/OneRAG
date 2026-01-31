"""
하이브리드 검색 결과 병합기

Dense 벡터 검색 결과와 BM25 키워드 검색 결과를
RRF(Reciprocal Rank Fusion) 알고리즘으로 병합합니다.

alpha 파라미터로 두 소스 간 가중치를 조절합니다:
- alpha=1.0: Dense 100%
- alpha=0.0: BM25 100%
- alpha=0.6: Dense 60% + BM25 40% (기본값, Weaviate와 동일)
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.core.retrieval.interfaces import SearchResult

logger = logging.getLogger(__name__)

# RRF 상수 (일반적으로 60 사용)
_RRF_K = 60


class HybridMerger:
    """
    RRF 기반 하이브리드 검색 결과 병합기

    Args:
        alpha: Dense 가중치 (0.0 ~ 1.0, 기본값: 0.6)
    """

    def __init__(self, alpha: float = 0.6) -> None:
        if not 0.0 <= alpha <= 1.0:
            raise ValueError(f"alpha는 0.0~1.0 범위여야 합니다: {alpha}")
        self._alpha = alpha
        logger.info(f"HybridMerger 초기화 (alpha={alpha})")

    def merge(
        self,
        dense_results: list[SearchResult],
        bm25_results: list[dict[str, Any]],
        top_k: int = 10,
    ) -> list[SearchResult]:
        """
        Dense + BM25 결과를 RRF로 병합

        Args:
            dense_results: Dense 벡터 검색 결과 (SearchResult 리스트)
            bm25_results: BM25 키워드 검색 결과 (dict 리스트)
            top_k: 반환할 최대 결과 수

        Returns:
            RRF 점수로 정렬된 SearchResult 리스트
        """
        if not dense_results and not bm25_results:
            return []

        rrf_scores: dict[str, float] = {}
        doc_info: dict[str, dict[str, Any]] = {}

        # Dense 결과 RRF 점수
        for rank, result in enumerate(dense_results):
            rrf_score = self._alpha * (1.0 / (_RRF_K + rank + 1))
            rrf_scores[result.id] = rrf_scores.get(result.id, 0.0) + rrf_score
            if result.id not in doc_info:
                doc_info[result.id] = {
                    "content": result.content,
                    "metadata": result.metadata,
                }

        # BM25 결과 RRF 점수
        bm25_weight = 1.0 - self._alpha
        for rank, bm25_item in enumerate(bm25_results):
            doc_id = bm25_item["id"]
            rrf_score = bm25_weight * (1.0 / (_RRF_K + rank + 1))
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + rrf_score
            if doc_id not in doc_info:
                doc_info[doc_id] = {
                    "content": bm25_item["content"],
                    "metadata": bm25_item.get("metadata", {}),
                }

        # 정렬 + SearchResult 변환
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

        merged: list[SearchResult] = []
        for doc_id in sorted_ids[:top_k]:
            info = doc_info[doc_id]
            merged.append(
                SearchResult(
                    id=doc_id,
                    content=info["content"],
                    score=rrf_scores[doc_id],
                    metadata=info["metadata"],
                )
            )

        logger.debug(
            f"HybridMerger: Dense {len(dense_results)}개 + BM25 {len(bm25_results)}개 "
            f"→ 병합 {len(merged)}개 (alpha={self._alpha})"
        )

        return merged
