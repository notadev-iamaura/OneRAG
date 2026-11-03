"""7단계 출력: Source 변환, 디버그 트레이스, 최종 응답 구성.

rag_pipeline.py 의 RAGPipeline 에서 분리한 단계 믹스인. 동작은 분리 전과 동일하다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ....lib.logger import get_logger
from ....lib.types import RAGResultDict
from ..source_contract import normalize_source_payload
from .document_utils import (
    _document_metadata,
)
from .models import FormattedSources

if TYPE_CHECKING:
    from ...modules.core.sql_search import SQLSearchResult
    from ..schemas.debug import DebugTrace

from .base import PipelineStateBase

logger = get_logger(__name__)


class OutputStageMixin(PipelineStateBase):
    """7단계 출력: Source 변환, 디버그 트레이스, 최종 응답 구성."""


    def _create_debug_trace(
        self,
        enable_debug_trace: bool,
        debug_trace_data: dict[str, Any],
        message: str,
    ) -> DebugTrace | None:
        """DebugTrace 객체 생성"""
        if not enable_debug_trace or not debug_trace_data:
            return None

        try:
            from ...schemas.debug import DebugTrace

            if "query_transformation" not in debug_trace_data:
                debug_trace_data["query_transformation"] = {
                    "original": message,
                    "expanded": None,
                    "final_query": message,
                }
            if "retrieved_documents" not in debug_trace_data:
                debug_trace_data["retrieved_documents"] = []

            debug_trace = DebugTrace(**debug_trace_data)
            logger.debug(
                "DebugTrace 생성 완료",
                extra={"document_count": len(debug_trace.retrieved_documents)}
            )
            return debug_trace
        except Exception as e:
            logger.warning(
                "DebugTrace 생성 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            return None


    def _format_rag_source(self, idx: int, doc: Any) -> dict[str, Any] | None:
        """RAG 검색 결과를 Source 객체로 변환"""
        try:
            metadata = getattr(doc, "metadata", {}) or {}
            source_metadata = dict(metadata)
            document_name = (
                metadata.get("source_file")
                or metadata.get("filename")
                or metadata.get("document_name")
                or metadata.get("source")
                or f"Document {idx + 1}"
            )

            if self.privacy_masker:
                document_name = self.privacy_masker.mask_filename(document_name)
                for key in ("source_file", "filename", "document_name", "file_name"):
                    if source_metadata.get(key):
                        source_metadata[key] = self.privacy_masker.mask_filename(
                            str(source_metadata[key])
                        )

            content_text = getattr(doc, "content", None) or getattr(doc, "page_content", "")
            if content_text and self.privacy_masker:
                content_text = self.privacy_masker.mask_text(content_text)
            content_preview = content_text[:200] if content_text else ""

            raw_score = getattr(doc, "score", 0.0)
            normalized_score = self.score_normalizer.normalize(raw_score)

            # file_path(서버 내부 절대경로)는 출처 응답에 노출하지 않는다.
            # source_contract.normalize_source_payload가 file_path 키를 metadata와
            # 최상위 필드 모두에서 제거하므로, 디렉토리 구조가 새어나가지 않도록
            # 여기서 source_metadata에 file_path를 주입하지 않는다(정보 노출 차단).
            source_metadata.pop("file_path", None)

            return normalize_source_payload(
                sequence_id=idx,
                source_type="rag",
                document_name=document_name,
                relevance=normalized_score,
                content_preview=content_preview,
                metadata=source_metadata,
            )
        except Exception as e:
            logger.warning(
                "소스 포맷팅 실패",
                extra={"source_idx": idx, "error": str(e)},
                exc_info=True
            )
            return None


    def _format_sql_row(
        self,
        row: dict[str, Any],
        row_idx: int,
        source_id: int,
        sql_query: str | None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """SQL 검색 결과의 한 행을 Source 객체로 변환"""
        entity_name = (
            row.get("entity_name")
            or row.get("name")
            or self._sql_entity_name_fallback_template.format(index=row_idx + 1)
        )
        row_preview = ", ".join(f"{k}: {v}" for k, v in row.items() if v is not None)

        if row_preview and self.privacy_masker:
            row_preview = self.privacy_masker.mask_text(row_preview)

        document_name = f"[{category}] {entity_name}" if category else str(entity_name)
        metadata = {
            "category": category,
            "entity_name": entity_name,
            "document_id": (
                row["document_id"]
                if row.get("document_id") is not None and row.get("document_id") != ""
                else row["id"]
                if row.get("id") is not None and row.get("id") != ""
                else row.get("entity_id")
            ),
        }

        source_data = normalize_source_payload(
            sequence_id=source_id,
            source_type="sql",
            document_name=document_name,
            relevance=100.0,
            content_preview=row_preview[:200] if row_preview else self._sql_preview_fallback,
            metadata={key: value for key, value in metadata.items() if value is not None},
            additional_metadata={"row_keys": sorted(str(key) for key in row.keys())},
        )
        source_data.update(
            {
                "sql_query": sql_query,
                "sql_result_summary": row_preview,
            }
        )
        return source_data


    def _add_multi_query_sql_sources(
        self, sources: list[Any], sql_search_result: SQLSearchResult, max_sources: int
    ) -> int:
        """멀티 쿼리 SQL 결과를 sources에 추가"""
        added_count = 0
        for query_result in sql_search_result.query_results:
            if not query_result.success or not query_result.result:
                continue

            sql_result = query_result.result
            sql_query = query_result.query.sql_query
            category = query_result.query.target_category or self._sql_all_category_label

            for row_idx, row in enumerate(sql_result.data):
                if added_count >= max_sources:
                    break

                sql_source_data = self._format_sql_row(
                    row, row_idx, len(sources), sql_query, category
                )
                sources.append(self.Source(**sql_source_data))
                added_count += 1

        logger.info(
            "멀티 SQL 소스 추가",
            extra={
                "row_count": added_count,
                "query_count": len(sql_search_result.query_results)
            }
        )
        return added_count


    def _add_single_query_sql_sources(
        self, sources: list[Any], sql_search_result: SQLSearchResult, max_sources: int
    ) -> int:
        """단일 쿼리 SQL 결과를 sources에 추가"""
        sql_result = sql_search_result.query_result
        sql_gen = sql_search_result.generation_result
        sql_query = sql_gen.sql_query if sql_gen else None
        added_count = 0

        for row_idx, row in enumerate(sql_result.data[:max_sources]):
            sql_source_data = self._format_sql_row(row, row_idx, len(sources), sql_query)
            sources.append(self.Source(**sql_source_data))
            added_count += 1

        logger.info(
            "SQL 소스 추가",
            extra={
                "added_count": added_count,
                "total_rows": sql_result.row_count,
                "query": sql_query[:50] if sql_query else 'N/A'
            }
        )
        return added_count


    def format_sources(
        self,
        ranked_results: list[Any],
        sql_search_result: SQLSearchResult | None = None,
    ) -> FormattedSources:
        """
        6단계: 검색 결과 → Source 객체 변환

        - RAG 문서 → Source 객체 변환 (source_type="rag")
        - SQL 검색 결과 → Source 객체 변환 (source_type="sql")
        - 메타데이터 정규화 (file_type, relevance 등)

        Args:
            ranked_results: 리랭킹된 문서 (RRF 병합 결과)
            sql_search_result: SQL 검색 결과 (선택적)

        Returns:
            FormattedSources: Source 객체 리스트 (RAG + SQL 통합)
        """
        logger.debug("[6단계] 소스 포맷팅 시작")
        sources = []

        try:
            for idx, doc in enumerate(ranked_results):
                # 인접 청크 확장 이웃 청크와 명시 문서 digest(_generation_only)는 실제
                # 검색 히트가 아니므로 사용자 인용 소스에서 제외한다(오염 방지)(#4, GAP #1).
                metadata = _document_metadata(doc)
                if metadata.get("context_expanded") or metadata.get("_generation_only"):
                    continue
                source_data = self._format_rag_source(idx, doc)
                if source_data:
                    sources.append(self.Source(**source_data))

            if sql_search_result and sql_search_result.used:
                try:
                    max_sql_sources = 10
                    if sql_search_result.is_multi_query and sql_search_result.query_results:
                        self._add_multi_query_sql_sources(sources, sql_search_result, max_sql_sources)
                    elif sql_search_result.query_result:
                        self._add_single_query_sql_sources(sources, sql_search_result, max_sql_sources)
                except Exception as sql_err:
                    logger.warning(
                        "SQL 소스 포맷팅 실패 (무시)",
                        extra={"error": str(sql_err)},
                        exc_info=True
                    )

            logger.debug(
                "[6단계] 소스 포맷팅 완료",
                extra={"source_count": len(sources), "type": "RAG + SQL"}
            )
            return FormattedSources(sources=sources, count=len(sources))
        except Exception as e:
            logger.error(
                "[6단계] 소스 리스트 포맷팅 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            return FormattedSources(sources=[], count=0)


    def build_result(
        self,
        answer: str,
        sources: list[Any],
        tokens_used: int,
        topic: str,
        processing_time: float,
        search_count: int,
        ranked_count: int,
        model_info: dict[str, Any],
        routing_metadata: dict[str, Any] | None,
        debug_trace: DebugTrace | None = None,  # ⭐ 신규 파라미터
        quality_score: float | None = None,  # Self-RAG 품질 점수
        refusal_reason: str | None = None,  # 저품질 거부 사유
    ) -> RAGResultDict:
        """
        7단계: 최종 응답 딕셔너리 구성

        - 표준 응답 형식 생성
        - 라우팅 메타데이터 포함 (선택적)
        - 디버깅 추적 정보 포함 (선택적)

        Args:
            answer: 생성된 답변
            sources: Source 객체 리스트
            tokens_used: 사용된 토큰 수
            topic: 추출된 토픽
            processing_time: 총 처리 시간 (초)
            search_count: 검색된 문서 수
            ranked_count: 리랭킹된 문서 수
            model_info: 모델 정보
            routing_metadata: 라우팅 메타데이터
            debug_trace: 디버깅 추적 정보 (enable_debug_trace=True 시)

        Returns:
            표준 응답 딕셔너리

        Note:
            이 메서드는 동기 함수 (async 불필요)
        """
        logger.debug("[8단계] 결과 구성 시작")

        # model_info 표준화 (API 응답 일관성 보장)
        if model_info:
            # 필수 필드 보장 + 하위 호환성
            standardized_model_info = {
                "provider": model_info.get("provider", "unknown"),
                "model": model_info.get("model", "unknown"),
                "model_used": model_info.get("model", model_info.get("model_used", "unknown")),
                "self_rag_applied": model_info.get("self_rag_applied", False),
            }

            # 선택적 필드 (존재하는 경우만 추가)
            optional_fields = [
                "complexity_score",
                "initial_quality",
                "final_quality",
                "self_rag_regenerated",
                "self_rag_outcome",
                "self_rag_eval_status",
                "self_rag_final_eval_status",
                "self_rag_rollback_reason",
                "self_rag_skip_reason",
                "mode",
                "tool_usage",
                "citations_count",
            ]
            for field in optional_fields:
                if field in model_info and model_info[field] is not None:
                    standardized_model_info[field] = model_info[field]
        else:
            # model_info가 없는 경우 안전한 기본값 (방어적 프로그래밍)
            logger.warning("model_info가 None - 기본값 사용")
            standardized_model_info = {
                "provider": "unknown",
                "model": "unknown",
                "model_used": "unknown",
                "self_rag_applied": False,
            }

        # PII 마스킹: 최종 답변에서 개인정보 마스킹 (활성화 시에만)
        masked_answer = answer
        if self.privacy_masker:
            masked_answer = self.privacy_masker.mask_text(answer)

        result = {
            "answer": masked_answer,
            "sources": sources,
            "tokens_used": tokens_used,
            "topic": topic,
            "processing_time": processing_time,
            "search_results": search_count,
            "ranked_results": ranked_count,
            "model_info": standardized_model_info,
        }

        if routing_metadata:
            result["routing_metadata"] = routing_metadata

        # ⭐ Self-RAG 품질 점수/거부 사유 전파
        # (chat_router의 quality 메타데이터 블록이 이 값을 읽는다 — 누락 시 항상 None)
        if quality_score is not None:
            result["quality_score"] = quality_score
        if refusal_reason is not None:
            result["refusal_reason"] = refusal_reason

        # ⭐ 디버깅 추적 정보 추가
        if debug_trace is not None:
            result["debug_trace"] = debug_trace

        logger.debug(
            "[8단계] 결과 구성 완료",
            extra={
                "search_count": search_count,
                "ranked_count": ranked_count
            }
        )
        return cast(RAGResultDict, result)

