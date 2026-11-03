"""4단계 리랭킹: 원 신호 융합, 정확 신호 안정화.

rag_pipeline.py 의 RAGPipeline 에서 분리한 단계 믹스인. 동작은 분리 전과 동일하다.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ....lib.logger import get_logger
from .base import PipelineStateBase
from .document_utils import (
    _CALENDAR_YEAR_PATTERN,
    _annotate_rerank_scores,
    _coerce_bool,
    _coerce_bounded_int,
    _document_identity,
    _document_metadata,
    _exact_identifier_terms,
    _is_noop_rerank,
    _latin_phrase_terms,
    _snapshot_rerank_inputs,
)
from .models import RerankResults

logger = get_logger(__name__)


class RerankStageMixin(PipelineStateBase):
    """4단계 리랭킹: 원 신호 융합, 정확 신호 안정화."""


    def _stabilize_reranked_results_with_exact_signals(
        self, query: str, ranked_results: list[Any]
    ) -> list[Any]:
        """정확 신호가 강한 문서를 상위로 안정화한다(GAP A).

        exact_identifier.enabled=false면 no-op. 질문에 식별자/연도 등 2차 신호가 없거나
        최고 점수가 임계(2.5) 미만이면 그대로 반환한다. 조건 충족 시 정확 신호 점수
        내림차순(동점은 기존 순서)으로 재정렬해, 리랭커가 정확 식별자 문서를 하위로
        밀어버린 경우를 보정한다.

        Args:
            query: 검색 질문
            ranked_results: 리랭킹된 문서 리스트

        Returns:
            안정화된 문서 리스트(미적용 시 입력 그대로).
        """
        if not self.exact_identifier_enabled:
            return ranked_results
        if len(ranked_results) < 2:
            return ranked_results
        has_secondary_signal = bool(
            _exact_identifier_terms(query)
            or _latin_phrase_terms(query)
            or _CALENDAR_YEAR_PATTERN.search(query)
        )
        if not has_secondary_signal:
            return ranked_results
        scored = [
            (self._exact_signal_score(query, document), index, document)
            for index, document in enumerate(ranked_results)
        ]
        if max(score for score, _, _ in scored) < 2.5:
            return ranked_results
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [document for _, _, document in scored]


    def _should_preserve_candidates_for_rerank(self) -> bool:
        """리랭킹이 활성화되어 확장 candidate를 보존해야 하는지 판단(GAP A).

        리랭킹이 켜져 있으면 확장된 candidate pool을 리랭커에 넘겨 더 넓은 풀에서
        정렬하게 한다. 리랭킹이 꺼져 있으면 요청 한도로 잘라 기존 응답 크기를 유지한다.
        """
        reranking_config = self.config.get("reranking", {})
        retrieval_config = self.config.get("retrieval", {})
        return bool(
            (isinstance(reranking_config, dict) and reranking_config.get("enabled", False))
            or (isinstance(retrieval_config, dict) and retrieval_config.get("enable_reranking", False))
        )


    def _rerank_fusion_enabled(
        self,
        reranking_config: dict[str, Any],
        options: dict[str, Any],
    ) -> bool:
        """리랭크 fusion 활성화 여부 판단(#33).

        provider 무관 opt-in(기본 비활성화)으로 일반화한다. 원본 구현의 vertex
        게이팅(provider=="vertex" or has_vertex_signal)을 제거해 어떤 리랭커
        provider에서도 config/options로 켤 수 있게 한다.

        Args:
            reranking_config: reranking 설정 dict
            options: 요청 옵션(런타임 오버라이드)

        Returns:
            fusion 적용 여부
        """
        fusion_config = reranking_config.get("fusion", {})
        fusion_config = fusion_config if isinstance(fusion_config, dict) else {}
        return _coerce_bool(
            options.get("rerank_fusion_enabled", fusion_config.get("enabled")),
            default=False,
        )


    def _original_signal_score(self, document: Any) -> float | None:
        """문서의 원본 lexical/hybrid 신호 점수를 추출한다(#33).

        original_score → rrf_score → bm25_score → hybrid_score 순으로 탐색한다.
        모두 OneRAG 메타데이터에 존재하는 범용 신호 키다.
        """
        metadata = _document_metadata(document)
        for key in ("original_score", "rrf_score", "bm25_score", "hybrid_score"):
            value = metadata.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None


    def _fuse_reranked_results_with_original_signals(
        self,
        ranked_results: list[Any],
        reranking_config: dict[str, Any],
        options: dict[str, Any],
    ) -> list[Any]:
        """리랭커 top-k를 보존하면서 원본 신호 상위 후보를 재삽입한다(#33).

        리랭커(특히 semantic)가 BM25/exact-match 신호를 덮어 식별자·모델코드·연도
        문서를 하위로 미는 도메인 무관 문제를 막는다. 리랭커 top1을 그대로 유지해
        recall@1을 보존하면서, original_score 높은 하위 후보를 상위로 승격해
        recall@5/MRR을 개선한다. 기본 비활성화(opt-in)이며 도메인/언어 하드코딩이 없다.

        Args:
            ranked_results: 리랭킹된 문서 리스트
            reranking_config: reranking 설정 dict
            options: 요청 옵션(런타임 오버라이드)

        Returns:
            fusion이 적용된 문서 리스트(미적용 시 원본 그대로)
        """
        if len(ranked_results) < 3:
            return ranked_results
        if not self._rerank_fusion_enabled(reranking_config, options):
            return ranked_results

        fusion_config = reranking_config.get("fusion", {})
        fusion_config = fusion_config if isinstance(fusion_config, dict) else {}
        strategy = str(
            options.get(
                "rerank_fusion_strategy",
                fusion_config.get("strategy", "rerank_top1_original_top3"),
            )
        ).strip()
        if strategy != "rerank_top1_original_top3":
            return ranked_results

        preserve_top_k = _coerce_bounded_int(
            options.get(
                "rerank_fusion_preserve_rerank_top_k",
                fusion_config.get("preserve_rerank_top_k", 1),
            ),
            1,
            1,
            min(5, len(ranked_results)),
        )
        original_top_k = _coerce_bounded_int(
            options.get(
                "rerank_fusion_original_top_k",
                fusion_config.get("original_top_k", 3),
            ),
            3,
            1,
            min(8, len(ranked_results) - preserve_top_k),
        )

        identities = [_document_identity(document) for document in ranked_results]
        preserved_ids = set(identities[:preserve_top_k])
        candidates: list[tuple[float, int, Any]] = []
        for index, document in enumerate(ranked_results[preserve_top_k:], preserve_top_k):
            signal_score = self._original_signal_score(document)
            if signal_score is None:
                continue
            candidates.append((signal_score, index, document))

        if not candidates:
            return ranked_results

        # 원본 신호 점수 내림차순, 동점 시 기존 순위 유지
        candidates.sort(key=lambda item: (-item[0], item[1]))
        promoted: list[Any] = []
        promoted_ids: set[Any] = set()
        for _, _, document in candidates:
            identity = _document_identity(document)
            if identity in preserved_ids or identity in promoted_ids:
                continue
            promoted.append(document)
            promoted_ids.add(identity)
            if len(promoted) >= original_top_k:
                break

        if not promoted:
            return ranked_results

        # 보존(top-k) → 승격(original 상위) → 나머지 순으로 재배치, identity 중복 제거
        fused: list[Any] = []
        seen: set[Any] = set()
        for document in [
            *ranked_results[:preserve_top_k],
            *promoted,
            *ranked_results[preserve_top_k:],
        ]:
            identity = _document_identity(document)
            if identity in seen:
                continue
            seen.add(identity)
            fused.append(document)

        # 순서 변화가 없으면 원본을 그대로 반환(불필요 로그/객체 생성 방지)
        if [_document_identity(document) for document in fused] == identities:
            return ranked_results

        logger.info(
            "리랭크 fusion 적용",
            extra={
                "strategy": strategy,
                "preserve_rerank_top_k": preserve_top_k,
                "original_top_k": original_top_k,
                "before_count": len(ranked_results),
                "after_count": len(fused),
            },
        )
        return fused


    async def rerank_documents(
        self, search_query: str, search_results: list[Any], options: dict[str, Any]
    ) -> RerankResults:
        """
        4단계: 검색 결과 리랭킹 (선택적)

        - 리랭킹 설정 확인 (config.reranking.enabled)
        - Jina/Cohere/LLM 리랭커 호출
        - 실패 시 원본 반환

        Args:
            search_query: 검색 쿼리
            search_results: 검색 결과 (Document 리스트)
            options: 리랭킹 옵션 (top_n 등)

        Returns:
            RerankResults: 리랭킹된 문서 리스트 (reranked=True/False)
        """
        logger.debug("[5단계] 리랭킹 시작")
        top_n = options.get("top_n", self.rerank_top_n)
        if top_n is not None and top_n < 0:
            raise ValueError("top_n must be non-negative")
        if top_n == 0:
            return RerankResults(documents=[], count=0, reranked=False)
        if not search_results:
            logger.debug("검색 결과 없음, 리랭킹 스킵")
            return RerankResults(documents=[], count=0, reranked=False)
        reranking_config = self.config.get("reranking", {})
        retrieval_config = self.config.get("retrieval", {})
        reranking_enabled = reranking_config.get(
            "enabled", retrieval_config.get("enable_reranking", False)
        )
        if not reranking_enabled:
            logger.debug("리랭킹 비활성화 - 원본 사용")
            return RerankResults(
                documents=search_results, count=len(search_results), reranked=False
            )
        # Future 객체 해결
        retrieval_module = self.retrieval_module
        if asyncio.iscoroutine(retrieval_module) or isinstance(retrieval_module, asyncio.Future):
            retrieval_module = await retrieval_module

        if not retrieval_module or not hasattr(retrieval_module, "rerank"):
            logger.warning("리랭킹 모듈 없음 - 원본 사용")
            return RerankResults(
                documents=search_results, count=len(search_results), reranked=False
            )
        try:
            original_snapshot = _snapshot_rerank_inputs(search_results)
            logger.debug(
                "리랭킹 실행",
                extra={"document_count": len(search_results)}
            )
            ranked_results = await retrieval_module.rerank(
                query=search_query,
                results=search_results,
                top_n=top_n,
            )
            outcome = _document_metadata(ranked_results[0]).get("jev_outcome") if ranked_results else None
            if outcome == "fallback":
                fallback = ranked_results if top_n is None else ranked_results[:top_n]
                return RerankResults(documents=fallback, count=len(fallback), reranked=False)
            if outcome != "judged" and _is_noop_rerank(original_snapshot, ranked_results):
                _annotate_rerank_scores(original_snapshot, ranked_results, reranked=False)
                logger.warning(
                    "[5단계] 리랭커가 원본 결과를 그대로 반환 - 리랭킹 미수행 처리",
                    extra={"document_count": len(ranked_results)}
                )
                return RerankResults(
                    documents=ranked_results,
                    count=len(ranked_results),
                    reranked=False,
                )

            _annotate_rerank_scores(original_snapshot, ranked_results, reranked=True)

            # 리랭킹 후 min_score 필터링
            min_score = reranking_config.get("min_score", 0.05)
            if outcome != "judged" and min_score > 0:
                before_count = len(ranked_results)
                ranked_results = [
                    doc
                    for doc in ranked_results
                    if (hasattr(doc, "score") and doc.score >= min_score)
                    or (hasattr(doc, "metadata") and doc.metadata.get("score", 0) >= min_score)
                ]
                if before_count > len(ranked_results):
                    logger.info(
                        "min_score 필터링",
                        extra={
                            "before_count": before_count,
                            "after_count": len(ranked_results),
                            "threshold": min_score
                        }
                    )
            logger.info(
                "[5단계] 리랭킹 완료",
                extra={"document_count": len(ranked_results)}
            )
            return RerankResults(documents=ranked_results, count=len(ranked_results), reranked=True)
        except Exception as e:
            logger.warning(
                "[5단계] 리랭킹 실패, 원본 사용",
                extra={"error": str(e)},
                exc_info=True
            )
            fallback = search_results if top_n is None else search_results[:top_n]
            return RerankResults(documents=fallback, count=len(fallback), reranked=False)

