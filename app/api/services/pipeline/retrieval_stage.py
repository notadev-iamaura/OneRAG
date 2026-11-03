"""3단계 검색: 병렬 SQL/RAG 검색, 정확 식별자·문서명 구출, 앵커 소프트 부스트, 컨텍스트 확장.

rag_pipeline.py 의 RAGPipeline 에서 분리한 단계 믹스인. 동작은 분리 전과 동일하다.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from typing import TYPE_CHECKING, Any, cast

from ....lib.circuit_breaker import CircuitBreakerOpenError
from ....lib.errors import ErrorCode, RetrievalError
from ....lib.langfuse_client import observe  # Langfuse 트레이싱
from ....lib.logger import get_logger
from ....modules.core.retrieval.interfaces import IMultiQueryRetriever, SearchResult
from .document_utils import (
    _CALENDAR_YEAR_PATTERN,
    _CONTEXT_EXPANSION_MAX_WINDOW,
    _NAMED_DOCUMENT_HIGH_VALUE_PATTERN,
    _NAMED_DOCUMENT_LIST_PAGE_SIZE,
    _chunk_to_search_result,
    _coerce_bool,
    _coerce_bounded_int,
    _coerce_optional_int,
    _coerce_positive_int,
    _context_chunk_identity,
    _context_chunk_index,
    _context_document_id,
    _document_content,
    _document_identity,
    _document_matches_requested_filename,
    _document_metadata,
    _document_score,
    _document_text_for_exact_signals,
    _document_value,
    _exact_identifier_terms,
    _latin_phrase_terms,
    _named_document_match_terms,
    _normalize_exact_match_text,
    _normalize_named_document_text,
    _quoted_content_hints,
    _requested_document_filenames,
)
from .models import PipelineTracker, PreparedContext, RetrievalResults

if TYPE_CHECKING:
    from ...modules.core.sql_search import SQLSearchResult

from .base import PipelineStateBase

logger = get_logger(__name__)


def _is_async_callable(candidate: Any) -> bool:
    """await 가능한 호출체인지 판정한다(코루틴 함수 또는 AsyncMock 류)."""
    if candidate is None:
        return False
    if inspect.iscoroutinefunction(candidate):
        return True
    call = getattr(candidate, "__call__", None)  # noqa: B004 - 바운드 객체의 __call__ 검사
    return inspect.iscoroutinefunction(call)


class RetrievalStageMixin(PipelineStateBase):
    """3단계 검색: 병렬 SQL/RAG 검색, 정확 식별자·문서명 구출, 앵커 소프트 부스트, 컨텍스트 확장."""


    async def _execute_parallel_search(
        self,
        message: str,
        prepared_context: PreparedContext,
        options: dict[str, Any],
    ) -> tuple[RetrievalResults, SQLSearchResult | None]:
        """SQL + RAG 병렬 검색 실행"""
        if self.sql_search_service and self.sql_search_service.is_enabled():
            logger.info("SQL 검색 + RAG 검색 병렬 실행 시작")
            rag_task = self.retrieve_documents(
                prepared_context.expanded_queries,
                prepared_context.query_weights,
                prepared_context.session_context,
                options,
            )
            sql_task = self._execute_sql_search(message)

            rag_result, sql_result = await asyncio.gather(
                rag_task, sql_task, return_exceptions=True
            )

            if isinstance(rag_result, Exception):
                logger.error("RAG 검색 실패", extra={"error": str(rag_result)}, exc_info=True)
                raise rag_result
            retrieval_results = rag_result

            sql_search_result = None
            if isinstance(sql_result, Exception):
                logger.warning(
                    "SQL 검색 실패 (무시)",
                    extra={"error": str(sql_result)},
                    exc_info=True
                )
            else:
                sql_search_result = sql_result
                if sql_search_result and sql_search_result.used:
                    row_count = sql_search_result.query_result.row_count if sql_search_result.query_result else 0
                    logger.info(
                        "SQL 검색 성공",
                        extra={
                            "row_count": row_count,
                            "total_time": sql_search_result.total_time
                        }
                    )

            return retrieval_results, sql_search_result
        else:
            retrieval_results = await self.retrieve_documents(
                prepared_context.expanded_queries,
                prepared_context.query_weights,
                prepared_context.session_context,
                options,
            )
            return retrieval_results, None


    def _track_debug_documents(
        self, enable_debug_trace: bool, debug_trace_data: dict[str, Any], documents: list[Any]
    ) -> None:
        """디버그 추적용 문서 정보 기록"""
        if not enable_debug_trace:
            return

        debug_trace_data["retrieved_documents"] = [
            {
                "id": doc.metadata.get("id", "") if hasattr(doc, "metadata") else "",
                "title": doc.metadata.get("title", "") if hasattr(doc, "metadata") else "",
                "chunk_text": (getattr(doc, "page_content", "")[:200] if hasattr(doc, "page_content") else ""),
                "vector_score": doc.metadata.get("score", 0.0) if hasattr(doc, "metadata") else 0.0,
                "bm25_score": doc.metadata.get("bm25_score") if hasattr(doc, "metadata") else None,
                "rerank_score": None,
                "used_in_answer": False,
            }
            for doc in documents
        ]


    def _update_retrieval_metrics(
        self,
        tracker: PipelineTracker,
        prepared_context: PreparedContext,
        sql_search_result: SQLSearchResult | None,
    ) -> None:
        """검색 메트릭 업데이트"""
        tracker.stages["retrieve_documents"]["multi_query_count"] = len(
            prepared_context.expanded_queries
        )
        tracker.stages["retrieve_documents"]["rrf_enabled"] = (
            len(prepared_context.expanded_queries) > 1
        )
        tracker.stages["retrieve_documents"]["query_weights"] = prepared_context.query_weights
        tracker.stages["retrieve_documents"]["sql_search_used"] = (
            sql_search_result.used if sql_search_result else False
        )


    def _retrieval_candidate_limit(self, requested_limit: int) -> int:
        """검색 candidate pool 크기를 계산한다(GAP A).

        exact_identifier.enabled=true일 때만 candidate pool을 확장한다(×MULTIPLIER,
        +MIN_EXTRA, 상한 MAX). 정확 식별자가 dense·BM25 상위에서 밀려도 rescue·rerank
        안정화가 더 넓은 후보에서 끌어올릴 수 있게 한다. OFF면 요청 한도 그대로(no-op).

        Args:
            requested_limit: 사용자가 요청한 검색 결과 수

        Returns:
            확장된 candidate 한도(OFF면 requested_limit 그대로).
        """
        if not self.exact_identifier_enabled:
            return requested_limit
        if requested_limit >= self.RETRIEVAL_CANDIDATE_MAX:
            return requested_limit
        expanded_limit = max(
            requested_limit * self.RETRIEVAL_CANDIDATE_MULTIPLIER,
            requested_limit + self.RETRIEVAL_CANDIDATE_MIN_EXTRA,
        )
        return int(max(requested_limit, min(expanded_limit, self.RETRIEVAL_CANDIDATE_MAX)))


    @staticmethod
    def _exact_identifier_terms(query: str) -> list[str]:
        """질문에서 정확 식별자 토큰을 추출한다(GAP A). 모듈 헬퍼 위임."""
        return _exact_identifier_terms(query)


    @staticmethod
    def _latin_phrase_terms(query: str) -> list[str]:
        """질문에서 라틴 다중 단어 구문을 추출한다(GAP A). 모듈 헬퍼 위임."""
        return _latin_phrase_terms(query)


    def _augment_search_queries_with_exact_terms(
        self,
        original_query: str,
        search_queries: list[str],
        query_weights: list[float],
    ) -> tuple[list[str], list[float]]:
        """정확 매칭 프로브 쿼리를 의미 쿼리를 대체하지 않고 추가 주입한다(GAP A).

        식별자(가중치 1.25)와 라틴 구문(1.1)을 별도 검색 쿼리로 추가해, dense/BM25가
        놓치기 쉬운 고유 식별자의 리콜을 보강한다. exact_identifier.enabled=false면
        입력을 그대로 반환(no-op). 정규화 키 기준 중복은 추가하지 않으며 최대 8개로 제한.

        Args:
            original_query: 원본(또는 재작성된) 질문
            search_queries: 기존 검색 쿼리 리스트
            query_weights: 기존 쿼리 가중치 리스트

        Returns:
            (보강된 쿼리 리스트, 보강된 가중치 리스트). OFF면 입력 그대로.
        """
        if not self.exact_identifier_enabled:
            return search_queries, query_weights

        augmented_queries = list(search_queries)
        augmented_weights = list(query_weights)
        existing = {_normalize_exact_match_text(q) for q in augmented_queries}
        candidates: list[tuple[str, float]] = []
        for term in _exact_identifier_terms(original_query):
            candidates.append((term, 1.25))
        for term in _latin_phrase_terms(original_query):
            candidates.append((term, 1.1))

        for term, weight in candidates:
            key = _normalize_exact_match_text(term)
            if not key or key in existing:
                continue
            augmented_queries.append(term)
            augmented_weights.append(weight)
            existing.add(key)
            if len(augmented_queries) >= 8:
                break
        return augmented_queries, augmented_weights


    def _exact_signal_score(self, query: str, document: Any) -> float:
        """문서가 질문의 정확 신호(식별자/라틴 구문/연도)와 얼마나 일치하는지 점수화(GAP A).

        원본 구현의 언어 전용 휴리스틱은 제거하고 언어무관 신호만 채택한다.
        - 식별자 매칭: +12.0 (가장 강한 신호)
        - 라틴 구문 매칭: +5.0
        - 캘린더 연도 일치: +5.0 / 문서에 다른 연도만 존재: -8.0
        """
        text = _document_text_for_exact_signals(document)
        normalized_text = _normalize_exact_match_text(text)
        score = 0.0

        for term in _exact_identifier_terms(query):
            if _normalize_exact_match_text(term) in normalized_text:
                score += 12.0

        for term in _latin_phrase_terms(query):
            if _normalize_exact_match_text(term) in normalized_text:
                score += 5.0

        query_years = {int(y) for y in _CALENDAR_YEAR_PATTERN.findall(query)}
        if query_years:
            doc_years = self._document_calendar_years(document)
            if query_years & doc_years:
                score += 5.0
            elif doc_years:
                score -= 8.0

        return score


    @staticmethod
    def _document_calendar_years(document: Any) -> set[int]:
        """문서의 식별 메타(파일명 등)에서 캘린더 연도(20xx)를 추출한다(GAP A/C).

        OneRAG의 파일명 연도 추출(doc_years 메타)을 우선 사용하고, 없으면 식별 메타
        문자열에서 직접 20xx를 추출한다(언어무관).
        """
        metadata = _document_metadata(document)
        years: set[int] = set()
        raw_doc_years = metadata.get("doc_years")
        if isinstance(raw_doc_years, list | tuple | set):
            for value in raw_doc_years:
                parsed = _coerce_optional_int(value)
                if parsed is not None:
                    years.add(parsed)
        source = str(
            metadata.get("source_file")
            or metadata.get("source")
            or metadata.get("document_name")
            or ""
        )
        for match in _CALENDAR_YEAR_PATTERN.findall(source):
            years.add(int(match))
        return years


    async def _rescue_exact_identifier_candidates(
        self,
        retrieval_module: Any,
        query: str,
        results: list[SearchResult],
        filters: dict[str, Any] | None,
        limit: int,
    ) -> list[SearchResult]:
        """정확 식별자를 직접 타깃 재검색해 매칭 후보를 병합한다(GAP A).

        exact_identifier.enabled=false거나 식별자가 없으면 results를 그대로 반환(no-op).
        식별자별로 직접 검색을 돌려, 식별자가 문서 텍스트에 포함된 후보만 추려 기존
        결과 앞쪽으로 병합한다(_document_identity 기준 중복 제거). 검색 실패는 graceful.

        Args:
            retrieval_module: 검색 모듈(search 메서드 또는 orchestrator.search)
            query: 검색 질문
            results: 기존 검색 결과
            filters: 검색 메타 필터
            limit: 최대 결과 수

        Returns:
            병합된 결과(no-op 시 results 그대로).
        """
        if not self.exact_identifier_enabled:
            return results
        identifiers = _exact_identifier_terms(query)
        if not identifiers:
            return results

        search_func = getattr(retrieval_module, "search", None)
        if search_func is None:
            orchestrator = getattr(retrieval_module, "orchestrator", None)
            search_func = (
                getattr(orchestrator, "search", None) if orchestrator is not None else None
            )
        if search_func is None:
            return results

        rescued: list[SearchResult] = []
        for identifier in identifiers[:3]:
            try:
                candidates = await search_func(
                    identifier, {"limit": limit, "filters": filters}
                )
            except Exception as exc:
                logger.debug(
                    "정확 식별자 보강 검색 실패",
                    extra={"identifier": identifier, "error": str(exc)},
                )
                continue
            identifier_key = _normalize_exact_match_text(identifier)
            for candidate in candidates or []:
                text_key = _normalize_exact_match_text(
                    _document_text_for_exact_signals(candidate)
                )
                if identifier_key and identifier_key in text_key:
                    rescued.append(candidate)

        if not rescued:
            return results

        merged: list[SearchResult] = []
        seen: set[Any] = set()
        for candidate in [*rescued, *results]:
            key = _document_identity(candidate)
            if key in seen:
                continue
            seen.add(key)
            merged.append(candidate)
        logger.info(
            "정확 식별자 후보 보강 완료",
            extra={
                "identifiers": identifiers[:3],
                "rescued_count": len(rescued),
                "merged_count": len(merged),
            },
        )
        return merged[:limit]


    async def _extract_anchor_sources(
        self,
        message: str,
        session_id: str,
        chat_history: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """직전 대화에서 인용된 문서(anchor)를 추출하고 오염 게이트로 유지/폐기 결정(GAP B).

        멀티턴 anchor soft boost의 입력. 직전 assistant 메시지의 sources에서 문서
        식별자(`document`=파일명, `document_id`)를 anchor로 추출한다.

        오염 방지 게이트(고착 방지의 핵심):
        - `_needs_standalone_rewrite`를 재사용한다. True(대명사/생략/축약 → 같은 주제의
          후속 질문)면 anchor 유지, False(충분히 길고 자립적 → 주제 전환 가능성)면 폐기.
        - 기능 비활성(multiturn_anchor_enabled=False)/session_module 부재/직전 sources
          부재 시 빈 리스트를 반환해 기존 동작과 100% 동일(no-op)하게 만든다.

        Args:
            message: 후속 사용자 질문(원본)
            session_id: 세션 ID
            chat_history: 이미 조회된 채팅 히스토리(중복 조회 방지). None이면 직접 조회.

        Returns:
            anchor 리스트(각 {"document", "document_id"}), 폐기/부재 시 빈 리스트.
        """
        if not self.multiturn_anchor_enabled:
            return []
        if self.session_module is None:
            return []

        # 오염 게이트: 자립적(주제 전환) 질문이면 anchor 폐기
        if not self._needs_standalone_rewrite(message):
            logger.debug(
                "anchor 폐기: 자립적 질문(주제 전환 가능성)",
                extra={"message": message[:40]},
            )
            return []

        if chat_history is not None:
            history: dict[str, Any] | None = chat_history
        else:
            get_history = getattr(self.session_module, "get_chat_history", None)
            if get_history is None:
                return []
            try:
                history = await get_history(session_id)
            except Exception as e:
                logger.debug(
                    "anchor 추출 생략: 채팅 히스토리 조회 실패",
                    extra={"error": str(e)},
                )
                return []

        messages = history.get("messages", []) if isinstance(history, dict) else []
        if not messages:
            return []

        # 가장 최근 assistant 메시지를 역순 탐색
        last_sources: list[Any] = []
        for msg in reversed(messages):
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "assistant":
                raw_sources = msg.get("sources", [])
                if isinstance(raw_sources, list):
                    last_sources = raw_sources
                break

        if not last_sources:
            return []

        anchors: list[dict[str, Any]] = []
        seen: set[str] = set()
        for src in last_sources:
            if not isinstance(src, dict):
                continue
            document = src.get("document") or src.get("source_file")
            document_id = src.get("document_id") or src.get("source_id")
            if not document and not document_id:
                continue
            identity = f"{document_id or ''}|{document or ''}"
            if identity in seen:
                continue
            seen.add(identity)
            anchors.append({"document": document, "document_id": document_id})

        if anchors:
            logger.debug(
                "anchor 유지(후속 질문, soft boost 대상)",
                extra={"anchor_count": len(anchors), "message": message[:40]},
            )
        return anchors


    @staticmethod
    def _document_matches_anchor(
        document: Any, anchor_sources: list[dict[str, Any]]
    ) -> bool:
        """문서가 anchor(직전 인용 문서)와 일치하는지 판정(GAP B).

        document_id 우선, 없으면 source_file(파일명)로 일치 여부를 확인한다.
        """
        metadata = _document_metadata(document)
        doc_id = metadata.get("document_id") or metadata.get("source_id")
        doc_file = metadata.get("source_file") or metadata.get("document")
        for anchor in anchor_sources:
            anchor_id = anchor.get("document_id")
            anchor_file = anchor.get("document")
            if anchor_id and doc_id and str(anchor_id) == str(doc_id):
                return True
            if anchor_file and doc_file and str(anchor_file) == str(doc_file):
                return True
        return False


    def _apply_anchor_soft_boost(
        self, anchor_sources: list[dict[str, Any]], ranked_results: list[Any]
    ) -> list[Any]:
        """리랭킹 결과에 직전 인용 문서(anchor) soft boost를 적용한다(GAP B).

        고착(staleness) 방지를 위해 hard filter(anchor 문서만 남기기)는 절대 쓰지 않고,
        anchor 일치 문서만 boosted 점수만큼 제자리에서 위로 끌어올린다(anchor-only
        stable-insert). 점수 격차가 크면 anchor라도 끌어올리지 못한다.

        불변식(회귀 방지): "anchor 미일치 문서끼리의 상대 순서는 입력과 100% 동일"하게
        보존한다. 직전 fusion(_fuse_reranked_results_with_original_signals)이 의도적으로
        점수 내림차순이 아닌 순서를 만들 수 있으므로 전면 sort를 쓰지 않고 anchor만
        bubble-up 한다.

        no-op 조건(기존 랭킹과 100% 동일):
        - 기능 비활성(multiturn_anchor_enabled=False)
        - anchor 없음 / 결과 2개 미만 / anchor 일치 문서 없음

        Args:
            anchor_sources: anchor 리스트({"document", "document_id"})
            ranked_results: 리랭킹된 문서 리스트(직전 fusion 순서)

        Returns:
            soft boost 후 재정렬된 문서 리스트(no-op 시 입력 그대로).
        """
        if not self.multiturn_anchor_enabled:
            return ranked_results
        if not anchor_sources or len(ranked_results) < 2:
            return ranked_results

        multiplier = self.multiturn_anchor_boost_multiplier
        matches = [
            self._document_matches_anchor(doc, anchor_sources) for doc in ranked_results
        ]
        if not any(matches):
            return ranked_results

        # 비교용 점수: anchor는 base*multiplier, 비-anchor는 base 그대로.
        # _document_score는 None을 반환할 수 있으므로 0.0으로 보정한다.
        effective_scores = [
            (_document_score(doc) or 0.0) * (multiplier if matches[index] else 1.0)
            for index, doc in enumerate(ranked_results)
        ]

        # anchor-only stable-insert: 비-anchor는 항상 맨 뒤 append(상대순서 불변),
        # anchor는 result 뒤쪽부터 위로 스캔하며 자신보다 "엄격히 작은" 문서만 추월.
        result: list[Any] = []
        result_scores: list[float] = []
        for index, document in enumerate(ranked_results):
            if not matches[index]:
                result.append(document)
                result_scores.append(effective_scores[index])
                continue
            boosted = effective_scores[index]
            insert_at = len(result)
            while insert_at > 0 and result_scores[insert_at - 1] < boosted:
                insert_at -= 1
            result.insert(insert_at, document)
            result_scores.insert(insert_at, boosted)

        if [id(d) for d in result] != [id(d) for d in ranked_results]:
            logger.info(
                "anchor soft boost 적용(순서 변경)",
                extra={
                    "boost_multiplier": multiplier,
                    "anchor_match_count": sum(matches),
                },
            )
        return result


    def _build_retrieval_filters(self, options: dict[str, Any]) -> dict[str, Any] | None:
        """요청 옵션에서 검색 메타데이터 필터를 구성한다(#12, GAP G).

        options['filters'](dict)에 더해, 라우팅 결과(data_source)에 대응하는 config
        기반 메타 필터를 병합한다(GAP G). filter_mappings가 비어있으면(기본) 기존
        무필터 동작과 100% 동일하게 동작한다(회귀 방지).
        """
        raw_filters = options.get("filters")
        filters = dict(raw_filters) if isinstance(raw_filters, dict) else {}

        # 라우팅 data_source → config 매핑 필터 병합 (GAP G).
        # 매핑이 비어있으면 추가 필터 없음(no-op) — 운영 회귀 방지 핵심 안전장치.
        data_source_filter = self._resolve_data_source_filter(options.get("data_source"))
        for key, value in data_source_filter.items():
            filters.setdefault(key, value)

        return filters or None


    def _resolve_data_source_filter(self, data_source: str | None) -> dict[str, Any]:
        """라우팅 data_source 값에 대응하는 config 기반 메타 필터를 반환한다(GAP G).

        매핑 설정 위치: ``query_routing.data_source_routing.filter_mappings``
        (app/config/features/routing.yaml). 기본값은 빈 dict이며, 이 경우 어떤
        data_source에 대해서도 추가 필터를 만들지 않는다(no-op, 회귀 0).

        Args:
            data_source: 라우팅 결과 data_source 값(예: "structured"/"general"/"both").
                None이면 빈 필터를 반환한다.

        Returns:
            병합 대상 메타 필터 dict(매핑 미설정/미일치 시 빈 dict).
        """
        if not data_source:
            return {}

        query_routing = self.config.get("query_routing", {})
        if not isinstance(query_routing, dict):
            return {}
        data_source_routing = query_routing.get("data_source_routing", {})
        if not isinstance(data_source_routing, dict):
            return {}

        filter_mappings = data_source_routing.get("filter_mappings") or {}
        if not isinstance(filter_mappings, dict):
            return {}

        mapped = filter_mappings.get(str(data_source))
        if not isinstance(mapped, dict):
            return {}

        # 얕은 복사로 호출자 측 변형을 방지한다.
        return dict(mapped)


    def _resolve_context_expansion(self, options: dict[str, Any]) -> tuple[bool, int]:
        """Resolve adjacent chunk expansion as an explicit opt-in feature."""
        rag_config = self.config.get("rag", {})
        configured = rag_config.get("context_expansion", {})
        context_config = configured if isinstance(configured, dict) else {}

        enabled = _coerce_bool(context_config.get("enabled"), default=False)
        for option_key in ("expand_adjacent_chunks", "context_expansion_enabled"):
            if option_key in options:
                enabled = _coerce_bool(options.get(option_key), default=enabled)
                break

        configured_window = _coerce_optional_int(context_config.get("window"))
        requested_window = _coerce_optional_int(
            options.get("adjacent_chunk_window", options.get("context_expansion_window"))
        )
        # 설정값 0은 "명시적 비활성"이므로 None일 때만 기본값(1)을 사용한다([32]).
        if requested_window is not None:
            window = requested_window
        elif configured_window is not None:
            window = configured_window
        else:
            window = 1

        configured_max_window = _coerce_optional_int(context_config.get("max_window"))
        # max_window=0도 명시적 값으로 취급(아래 max(1, ...) 클램프가 최소 1 보장)([34]).
        max_window = (
            configured_max_window
            if configured_max_window is not None
            else _CONTEXT_EXPANSION_MAX_WINDOW
        )
        max_window = max(1, min(max_window, _CONTEXT_EXPANSION_MAX_WINDOW))
        window = max(0, min(window, max_window))

        return enabled and window > 0, window


    async def expand_context_documents(
        self,
        ranked_results: list[Any],
        options: dict[str, Any],
    ) -> list[Any]:
        """
        Optionally add adjacent chunks around ranked hits before generation.

        Default is off. When enabled, the method uses the existing
        get_document_chunks(document_id) retriever capability and falls back to
        the original ranked results if metadata or retriever support is absent.
        """
        enabled, window = self._resolve_context_expansion(options)
        if not enabled or not ranked_results:
            return ranked_results

        retrieval_module = self.retrieval_module
        if asyncio.iscoroutine(retrieval_module) or isinstance(retrieval_module, asyncio.Future):
            retrieval_module = await retrieval_module

        get_document_chunks = getattr(retrieval_module, "get_document_chunks", None)
        if not callable(get_document_chunks):
            logger.warning("인접 청크 확장 스킵 - get_document_chunks 미지원")
            return ranked_results

        original_by_identity: dict[tuple[Any, ...], Any] = {}
        for document in ranked_results:
            original_by_identity.setdefault(_context_chunk_identity(document), document)

        chunk_cache: dict[str, list[dict[str, Any]]] = {}
        expanded: list[Any] = []
        seen: set[tuple[Any, ...]] = set()

        def append_once(document: Any) -> None:
            identity = _context_chunk_identity(document)
            if identity in seen:
                return
            seen.add(identity)
            expanded.append(document)

        # 인접 청크가 필요한 distinct document_id를 먼저 수집해 동시 조회한다([16]).
        distinct_doc_ids: list[str] = []
        seen_doc_ids: set[str] = set()
        for document in ranked_results:
            doc_id = _context_document_id(document)
            if (
                doc_id is not None
                and _context_chunk_index(document) is not None
                and doc_id not in seen_doc_ids
            ):
                seen_doc_ids.add(doc_id)
                distinct_doc_ids.append(doc_id)

        async def _fetch_chunks(document_id: str) -> tuple[str, list[dict[str, Any]]]:
            try:
                chunks = await get_document_chunks(document_id)
            except NotImplementedError:
                logger.debug(
                    "인접 청크 확장 스킵 - retriever 메서드 미구현",
                    extra={"document_id": document_id},
                )
                chunks = []
            except Exception as exc:
                logger.warning(
                    "인접 청크 조회 실패 - 원본 검색 결과 유지",
                    extra={"document_id": document_id, "error": str(exc)},
                    exc_info=True,
                )
                chunks = []
            return document_id, chunks if isinstance(chunks, list) else []

        if distinct_doc_ids:
            fetched = await asyncio.gather(
                *(_fetch_chunks(doc_id) for doc_id in distinct_doc_ids)
            )
            for doc_id, chunks in fetched:
                chunk_cache[doc_id] = chunks

        for document in ranked_results:
            document_id = _context_document_id(document)
            chunk_index = _context_chunk_index(document)
            if document_id is None or chunk_index is None:
                append_once(document)
                continue

            chunks = chunk_cache.get(document_id, [])
            if not chunks:
                append_once(document)
                continue

            chunks_by_index: dict[int, dict[str, Any]] = {}
            for chunk in chunks:
                index = _context_chunk_index(chunk)
                if index is not None:
                    chunks_by_index.setdefault(index, chunk)

            for index in range(chunk_index - window, chunk_index + window + 1):
                if index < 0:
                    continue
                if index == chunk_index:
                    append_once(document)
                    continue

                identity: tuple[Any, ...] = ("chunk", document_id, index)
                if identity in original_by_identity:
                    append_once(original_by_identity[identity])
                    continue

                neighbor_chunk = chunks_by_index.get(index)
                if not neighbor_chunk:
                    continue
                chunk = neighbor_chunk
                adjacent_document = _chunk_to_search_result(
                    chunk,
                    source_document=document,
                    source_chunk_index=chunk_index,
                )
                if adjacent_document is not None:
                    append_once(adjacent_document)

        if len(expanded) != len(ranked_results):
            logger.info(
                "인접 청크 컨텍스트 확장 완료",
                extra={
                    "before_count": len(ranked_results),
                    "after_count": len(expanded),
                    "window": window,
                }
            )
        return expanded


    # ========================================================================
    # 명시 문서명 기반 컨텍스트 보강 (named-document chunk rescue) - GAP #1
    # ========================================================================
    def _resolve_named_document_rescue(self) -> tuple[bool, int, int]:
        """명시 문서 보강 설정을 해석한다(opt-in, 기본 OFF).

        Returns:
            (enabled, max_chunks, digest_max_lines)
        """
        rag_config = self.config.get("rag", {})
        configured = rag_config.get("named_document_rescue", {})
        rescue_config = configured if isinstance(configured, dict) else {}

        enabled = _coerce_bool(rescue_config.get("enabled"), default=False)
        max_chunks = _coerce_bounded_int(rescue_config.get("max_chunks"), 4, 1, 12)
        digest_max_lines = _coerce_bounded_int(
            rescue_config.get("digest_max_lines"), 40, 20, 120
        )
        return enabled, max_chunks, digest_max_lines


    async def _list_documents_for_named_rescue(self) -> list[dict[str, Any]]:
        """retriever에서 문서 목록을 조회한다(GAP #1, 미지원 시 빈 리스트)."""
        retrieval_module = self.retrieval_module
        if asyncio.iscoroutine(retrieval_module) or isinstance(
            retrieval_module, asyncio.Future
        ):
            retrieval_module = await retrieval_module

        method = getattr(retrieval_module, "list_documents", None)
        if not callable(method):
            orchestrator = getattr(retrieval_module, "orchestrator", None)
            method = getattr(orchestrator, "list_documents", None)
        if not callable(method):
            logger.debug("명시 문서 보강 스킵 - list_documents 미지원")
            return []

        try:
            payload = await method(page=1, page_size=_NAMED_DOCUMENT_LIST_PAGE_SIZE)
        except NotImplementedError:
            logger.debug("명시 문서 보강 스킵 - list_documents 미구현")
            return []
        except Exception as exc:
            logger.warning(
                "명시 문서 목록 조회 실패 - 원본 검색 결과 유지",
                extra={"error": str(exc)},
                exc_info=True,
            )
            return []

        if isinstance(payload, dict) and isinstance(payload.get("documents"), list):
            return [doc for doc in payload["documents"] if isinstance(doc, dict)]
        if isinstance(payload, list):
            return [doc for doc in payload if isinstance(doc, dict)]
        return []


    async def _get_chunks_for_named_rescue(self, document_id: str) -> list[Any]:
        """지목 문서의 전체 청크를 조회한다(GAP #1, 미지원/실패 시 빈 리스트)."""
        retrieval_module = self.retrieval_module
        if asyncio.iscoroutine(retrieval_module) or isinstance(
            retrieval_module, asyncio.Future
        ):
            retrieval_module = await retrieval_module

        method = getattr(retrieval_module, "get_document_chunks", None)
        if not callable(method):
            orchestrator = getattr(retrieval_module, "orchestrator", None)
            method = getattr(orchestrator, "get_document_chunks", None)
        if not callable(method):
            return []

        try:
            chunks = await method(document_id)
        except NotImplementedError:
            return []
        except Exception as exc:
            logger.warning(
                "명시 문서 청크 조회 실패 - 해당 문서 보강 생략",
                extra={"document_id": document_id, "error": str(exc)},
                exc_info=True,
            )
            return []
        return chunks if isinstance(chunks, list) else []


    def _named_document_chunk_result(
        self,
        chunk: Any,
        document_record: dict[str, Any],
        score: float,
    ) -> SearchResult | None:
        """청크를 보강용 SearchResult로 변환한다(GAP #1)."""
        content = _document_content(chunk)
        if not content.strip():
            return None

        metadata = dict(_document_metadata(chunk))
        metadata.pop("content", None)
        metadata.pop("embedding", None)
        metadata["named_document_rescue"] = True
        metadata.setdefault("document_id", document_record.get("id"))
        metadata.setdefault("source_file", document_record.get("filename"))
        metadata.setdefault("file_type", document_record.get("file_type"))

        chunk_id = _document_value(chunk, "id")
        if chunk_id in (None, ""):
            document_id = metadata.get("document_id") or "unknown"
            chunk_index = metadata.get("chunk_index", metadata.get("chunk", "na"))
            chunk_id = f"{document_id}:named:{chunk_index}"
        return SearchResult(
            id=str(chunk_id), content=content, score=score, metadata=metadata
        )


    def _rank_named_document_chunks(
        self,
        message: str,
        chunks: list[Any],
        document_record: dict[str, Any],
        max_chunks: int,
    ) -> list[SearchResult]:
        """지목 문서 청크를 질의 관련성 기준으로 정렬해 상위 N개를 반환한다(GAP #1)."""
        terms = _named_document_match_terms(message)
        quoted_hints = _quoted_content_hints(message)
        scored_chunks: list[tuple[int, int, SearchResult]] = []
        for index, chunk in enumerate(chunks):
            result = self._named_document_chunk_result(chunk, document_record, 1.0)
            if result is None:
                continue
            normalized_content = _normalize_named_document_text(result.content)
            content_score = sum(len(term) for term in terms if term in normalized_content)
            content_score += sum(
                len(hint) * 3 for hint in quoted_hints if hint in normalized_content
            )
            chunk_index = _context_chunk_index(result)
            stable_index = chunk_index if chunk_index is not None else index
            scored_chunks.append((content_score, stable_index, result))

        if not scored_chunks:
            return []

        ranked = sorted(scored_chunks, key=lambda item: (-item[0], item[1]))
        selected = ranked[:max_chunks]
        # 질의와 겹치는 라인이 전혀 없으면(최고점=0) 원래 청크 순서대로 앞부분을 제공한다.
        if selected and selected[0][0] == 0:
            selected = sorted(scored_chunks, key=lambda item: item[1])[:max_chunks]

        results: list[SearchResult] = []
        for offset, (_, _, result) in enumerate(selected):
            # 실제 히트보다 약간 낮은 점수대로 두어 정렬/표기 오염을 방지한다.
            result.score = max(0.95 - (offset * 0.01), 0.5)
            results.append(result)
        return results


    def _named_document_digest_result(
        self,
        message: str,
        chunks: list[Any],
        document_record: dict[str, Any],
        max_lines: int,
    ) -> SearchResult | None:
        """지목 문서 전체에서 질의 관련 라인을 모아 digest 결과를 만든다(GAP #1).

        벡터 검색이 놓친 문서라도 사용자가 명시한 이상, 전체에서 후보 근거를 한 번에
        제공해 답변 누락을 막는다. _generation_only로 표기해 인접 청크 확장/카운트에서
        제외되도록 한다.
        """
        terms = _named_document_match_terms(message)
        quoted_hints = _quoted_content_hints(message)
        scored_lines: list[tuple[int, int, str]] = []
        seen: set[str] = set()

        for chunk_order, chunk in enumerate(chunks):
            chunk_index = _context_chunk_index(chunk)
            stable_chunk_index = chunk_index if chunk_index is not None else chunk_order
            content = _document_content(chunk)
            for line_order, raw_line in enumerate(content.splitlines()):
                line = " ".join(raw_line.split())
                if not line:
                    continue
                if len(line) > 260:
                    line = f"{line[:257]}..."
                normalized_line = _normalize_named_document_text(line)
                if not normalized_line or normalized_line in seen:
                    continue

                score = 0
                if any(hint and hint in normalized_line for hint in quoted_hints):
                    score += 80
                score += sum(min(len(term), 12) for term in terms if term in normalized_line)
                if _NAMED_DOCUMENT_HIGH_VALUE_PATTERN.search(line):
                    score += 10
                if score <= 0:
                    continue

                seen.add(normalized_line)
                scored_lines.append(
                    (
                        score,
                        (stable_chunk_index * 1000) + line_order,
                        f"chunk {stable_chunk_index} line {line_order + 1}: {line}",
                    )
                )

        if not scored_lines:
            return None

        selected = sorted(scored_lines, key=lambda item: (-item[0], item[1]))[:max_lines]
        selected = sorted(selected, key=lambda item: item[1])
        digest_lines = [
            "named_document_digest: 질문에 명시된 문서 전체에서 뽑은 관련 후보 근거입니다.",
            *[line for _, _, line in selected],
        ]

        document_id = str(document_record.get("id") or "named-document")
        filename = str(
            document_record.get("filename") or document_record.get("source_file") or ""
        )
        metadata: dict[str, Any] = {
            "document_id": document_id,
            "source_file": filename,
            "file_type": document_record.get("file_type"),
            "chunk_index": -1,
            "named_document_digest": True,
            "_generation_only": True,
        }
        return SearchResult(
            id=f"{document_id}:named-digest",
            content="\n".join(digest_lines),
            score=0.99,
            metadata=metadata,
        )


    async def prepend_named_document_chunks(
        self,
        message: str,
        ranked_results: list[Any],
        options: dict[str, Any],
    ) -> list[Any]:
        """질문에 명시된 문서의 청크를 검색 결과 앞에 prepend한다(GAP #1, 기본 OFF).

        사용자가 파일명(확장자)이나 따옴표 인용구로 특정 문서를 지목하면, 벡터 검색이
        그 문서를 놓쳐도 list_documents/get_document_chunks로 직접 fetch해 digest +
        ranked chunks를 앞에 붙인다. 인접 청크 확장(expand_context_documents)과는
        독립된 별개 경로이며, 미지원 retriever면 graceful no-op으로 원본을 유지한다.

        Args:
            message: 사용자 질문(원문)
            ranked_results: 리랭킹까지 끝난 검색 결과
            options: 요청 옵션(현재 미사용, 시그니처 호환/확장 여지용)

        Returns:
            보강된 결과(앞: 명시 문서 digest/청크, 뒤: 원본). no-op이면 원본 그대로.
        """
        enabled, max_chunks, digest_max_lines = self._resolve_named_document_rescue()
        if not enabled or not ranked_results:
            return ranked_results

        requested_filenames = _requested_document_filenames(message)
        if not requested_filenames:
            return ranked_results

        document_records = await self._list_documents_for_named_rescue()
        if not document_records:
            return ranked_results

        rescued: list[SearchResult] = []
        for filename in requested_filenames:
            matching_records = [
                document
                for document in document_records
                if _document_matches_requested_filename(filename, document)
            ]
            # 동명 문서가 여럿이어도 첫 매칭 1건만 보강해 컨텍스트 폭증을 막는다.
            for record in matching_records[:1]:
                document_id = record.get("id")
                if document_id in (None, ""):
                    continue
                chunks = await self._get_chunks_for_named_rescue(str(document_id))
                if not chunks:
                    continue
                digest = self._named_document_digest_result(
                    message, chunks, record, digest_max_lines
                )
                if digest is not None:
                    rescued.append(digest)
                rescued.extend(
                    self._rank_named_document_chunks(
                        message, chunks, record, max_chunks
                    )
                )

        if not rescued:
            return ranked_results

        # 명시 문서 보강 결과를 앞에, 원본을 뒤에 두고 청크 동일성 기준 중복을 제거한다.
        expanded: list[Any] = []
        seen: set[tuple[Any, ...]] = set()
        for document in [*rescued, *ranked_results]:
            identity = _context_chunk_identity(document)
            if identity in seen:
                continue
            seen.add(identity)
            expanded.append(document)

        logger.info(
            "명시 문서명 기반 컨텍스트 보강 완료",
            extra={
                "requested_filenames": requested_filenames,
                "rescued_chunks": len(rescued),
                "base_count": len(ranked_results),
                "expanded_count": len(expanded),
            },
        )
        return expanded


    @observe(name="Document Retrieval (Hybrid Search)", capture_input=False, capture_output=False)
    async def retrieve_documents(
        self,
        search_queries: list[str] | str,
        query_weights: list[float] | None,
        context: str | None,
        options: dict[str, Any],
    ) -> RetrievalResults:
        """
        3단계: MongoDB Atlas 하이브리드 검색 (Multi-Query RRF 지원)

        - Multi-Query RRF: 다중 쿼리로 병렬 검색 후 RRF 알고리즘으로 병합
        - Single Query: 기존 방식 (하위 호환성)
        - Circuit Breaker 보호
        - 성능 메트릭 기록

        Args:
            search_queries: 검색 쿼리 (단일 문자열 또는 리스트)
            query_weights: 쿼리 가중치 리스트 (Multi-Query RRF용, 선택적)
            context: 세션 컨텍스트 (선택적)
            options: 검색 옵션 (limit, min_score 등)

        Note:
            스코어 가중치는 ScoringService(rag.yaml의 scoring 섹션)에서 자동 적용됩니다.

        Returns:
            RetrievalResults: 검색된 문서 리스트 (RRF 병합 완료)

        Raises:
            RetrievalError: 검색 실패 시
        """
        # 하위 호환성: 단일 쿼리를 리스트로 변환
        if isinstance(search_queries, str):
            search_queries = [search_queries]
            query_weights = [1.0]

        # query_weights 기본값
        if not query_weights:
            query_weights = [1.0] * len(search_queries)

        logger.debug(
            "[4단계] 문서 검색 시작",
            extra={
                "query_count": len(search_queries),
                "multi_query_rrf": "활성화" if len(search_queries) > 1 else "비활성화"
            }
        )

        # Future 객체 해결 (DI Container에서 Future를 전달할 수 있음)
        retrieval_module = self.retrieval_module
        if asyncio.iscoroutine(retrieval_module) or isinstance(retrieval_module, asyncio.Future):
            retrieval_module = await retrieval_module

        if not retrieval_module:
            logger.error("검색 모듈 없음")
            raise RetrievalError(ErrorCode.RETRIEVAL_SEARCH_FAILED)

        # Circuit Breaker는 선택 의존성이다. 팩토리가 주입되지 않은 구성(경량 서비스/테스트)에서는
        # 보호 없이 직접 호출한다(예전에는 AttributeError로 검색 전체가 실패했다).
        cb = (
            self.circuit_breaker_factory.get("document_retrieval")
            if self.circuit_breaker_factory is not None
            else None
        )

        # 정확 식별자 보강(GAP A): candidate pool을 확장해 식별자 문서가 상위에서
        # 밀려도 rescue/안정화가 끌어올릴 여지를 만든다. exact_identifier OFF면
        # candidate_limit == requested_limit이라 기존 동작과 동일(no-op).
        requested_limit = _coerce_positive_int(
            options.get("limit", self.retrieval_limit), self.retrieval_limit
        )
        candidate_limit = self._retrieval_candidate_limit(requested_limit)

        async def _search() -> list[SearchResult]:
            """실제 검색 로직 (Circuit Breaker 내부) - Multi-Query RRF"""
            # ✅ #12 수정: 요청 옵션의 메타데이터 필터를 실제 검색에 연결한다.
            # 필터가 없으면 None을 반환해 기존 무필터 동작과 100% 동일하다(회귀 방지).
            retrieval_filters = self._build_retrieval_filters(options)
            search_options = {
                "limit": candidate_limit,
                "min_score": options.get("min_score", self.min_score),
                "context": context,
                "filters": retrieval_filters,
            }

            # Multi-Query 검색: IMultiQueryRetriever Protocol 체크
            # RetrievalOrchestrator 직접 사용 (프로덕션)
            # Protocol 검사는 속성 존재만 보므로, 실제로 await 가능한 코루틴 함수인지도 확인한다.
            if isinstance(retrieval_module, IMultiQueryRetriever) and _is_async_callable(
                getattr(retrieval_module, "_search_and_merge", None)
            ):
                return list(
                    await retrieval_module._search_and_merge(
                    queries=search_queries,
                    top_k=search_options["limit"],
                    filters=retrieval_filters,
                    weights=query_weights,
                    use_rrf=True,  # RRF 활성화
                )
                )
            # 하위 호환성: orchestrator를 속성으로 갖는 경우
            elif hasattr(retrieval_module, "orchestrator"):
                orchestrator = retrieval_module.orchestrator
                if isinstance(orchestrator, IMultiQueryRetriever) and _is_async_callable(
                    getattr(orchestrator, "_search_and_merge", None)
                ):
                    # orchestrator._search_and_merge 직접 호출 (RRF 병합)
                    return list(
                        await orchestrator._search_and_merge(
                        queries=search_queries,
                        top_k=search_options["limit"],
                        filters=retrieval_filters,
                        weights=query_weights,
                        use_rrf=True,  # RRF 활성화
                    )
                    )

            # Fallback: 단일 쿼리 검색 (기존 방식)
            # orchestrator.search(query, options) 시그니처를 그대로 사용한다.
            # search_options의 filters는 어댑터가 추출해 search_and_rerank에 전달한다(#39).
            return cast(
                list[SearchResult], await retrieval_module.search(search_queries[0], search_options)
            )

        try:
            start_time = time.time()
            search_results = (
                await cb.call(_search, fallback=lambda: []) if cb is not None else await _search()
            )
            # 정확 식별자 rescue(GAP A): 식별자 직접 재검색으로 매칭 후보를 병합한다.
            # exact_identifier OFF거나 식별자가 없으면 no-op이다.
            search_results = await self._rescue_exact_identifier_candidates(
                retrieval_module,
                " ".join(search_queries),
                search_results,
                self._build_retrieval_filters(options),
                candidate_limit,
            )
            # 리랭킹이 켜져 있으면 확장된 candidate를 그대로 넘겨 리랭커가 더 넓은
            # 풀에서 정렬하게 하고, 그렇지 않으면 요청 한도로 잘라 기존 동작을 유지한다.
            if (
                self.exact_identifier_enabled
                and len(search_results) > requested_limit
                and not self._should_preserve_candidates_for_rerank()
            ):
                search_results = search_results[:requested_limit]
            latency_ms = (time.time() - start_time) * 1000
            self.performance_metrics.record_latency("retrieve_documents", latency_ms)
            logger.info(
                "[4단계] 검색 완료",
                extra={
                    "document_count": len(search_results),
                    "latency_ms": latency_ms,
                    "multi_query_rrf": "활성화" if len(search_queries) > 1 else "비활성화"
                }
            )
            return RetrievalResults(documents=search_results, count=len(search_results))
        except CircuitBreakerOpenError:
            logger.warning("Circuit Breaker OPEN - 검색 서비스 일시 차단")
            return RetrievalResults(documents=[], count=0)
        except Exception as e:
            logger.error(
                "[4단계] 문서 검색 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            raise RetrievalError(
                ErrorCode.RETRIEVAL_SEARCH_FAILED,
                queries=[q[:50] for q in search_queries],
                error=str(e),
            ) from e


    async def _execute_sql_search(self, query: str) -> SQLSearchResult | None:
        """
        SQL 검색 실행 (내부 헬퍼 메서드)

        RAG 검색과 병렬로 실행되며, 실패해도 파이프라인은 계속 진행됩니다.
        타임아웃과 에러 핸들링이 적용됩니다.

        Args:
            query: 사용자 질문

        Returns:
            SQLSearchResult | None: SQL 검색 결과 또는 None (실패/비활성화 시)
        """
        if not self.sql_search_service:
            return None

        from ....modules.core.sql_search import SQLSearchResult

        try:
            # SQL 검색 설정에서 타임아웃 조회
            sql_config = self.config.get("sql_search", {}).get("pipeline", {})
            timeout = sql_config.get("timeout", 8)  # 기본 8초

            # 타임아웃 적용
            result = await asyncio.wait_for(self.sql_search_service.search(query), timeout=timeout)

            return result

        except TimeoutError:
            logger.warning(
                "SQL 검색 타임아웃",
                extra={"timeout_seconds": timeout}
            )
            return SQLSearchResult(
                success=False,
                generation_result=None,
                query_result=None,
                formatted_context="",
                total_time=timeout,
                used=False,
                error="SQL 검색 타임아웃",
            )
        except Exception as e:
            logger.warning(
                "SQL 검색 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            return SQLSearchResult(
                success=False,
                generation_result=None,
                query_result=None,
                formatted_context="",
                total_time=0,
                used=False,
                error=str(e),
            )

