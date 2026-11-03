"""6단계 검증: Self-RAG 평가/재생성, 기간 불일치 환각 게이트.

rag_pipeline.py 의 RAGPipeline 에서 분리한 단계 믹스인. 동작은 분리 전과 동일하다.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ....lib.langfuse_client import langfuse_context, observe  # Langfuse 트레이싱
from ....lib.logger import get_logger
from ....lib.prompt_sanitizer import contains_output_leakage
from .document_utils import (
    _CALENDAR_YEAR_PATTERN,
)

if TYPE_CHECKING:
    from ...modules.core.generation.generator import GenerationResult

from .base import PipelineStateBase

logger = get_logger(__name__)


class VerificationStageMixin(PipelineStateBase):
    """6단계 검증: Self-RAG 평가/재생성, 기간 불일치 환각 게이트."""


    def _hallucination_gate_period_mismatch(
        self, message: str, documents: list[Any]
    ) -> bool:
        """질문에 명시된 연도가 검색 문서들의 연도와 전혀 일치하지 않는지 판정(GAP C).

        다른 기간 데이터로 단정하는 negative 환각을 막기 위한 판정. 캘린더 연도(20xx)만
        매칭하며(언어무관), 특정 회계연도 표기 휴리스틱은 채택하지 않는다. 오탐 방지를
        위해 질문 또는 문서에 연도 정보가 없으면 False(게이트 미적용)를 반환한다.

        Args:
            message: 사용자 질문
            documents: 검색/리랭킹된 컨텍스트 문서

        Returns:
            기간 불일치면 True(보류 대상), 아니면 False.
        """
        query_years = {int(y) for y in _CALENDAR_YEAR_PATTERN.findall(message)}
        if not query_years:
            return False
        doc_years: set[int] = set()
        for document in documents:
            doc_years |= self._document_calendar_years(document)
        if not doc_years:
            return False
        return query_years.isdisjoint(doc_years)


    def _apply_hallucination_gate(
        self,
        message: str,
        generation_result: GenerationResult,
        documents: list[Any],
        options: dict[str, Any] | None,
    ) -> GenerationResult:
        """기간 불일치 환각 게이트(GAP C, 기본 OFF, opt-in).

        hallucination_gate.enabled=true이고 질문 기간이 문서 기간과 전혀 일치하지
        않으면, 답변을 '확인 불가' 메시지로 교체해 환각을 차단한다. 비활성(기본)이면
        generation_result를 그대로 반환해 기존 동작을 유지한다. self_rag_verify 이후에
        호출되어 최종 답변 기준으로 1회만 판정한다.

        Args:
            message: 사용자 질문
            generation_result: 현재 생성 결과
            documents: 컨텍스트 문서
            options: 요청 옵션(예약, 현재 미사용)

        Returns:
            게이트 통과 시 원본, 차단 시 보류 메시지로 교체된 GenerationResult.
        """
        if not self.hallucination_gate_enabled:
            return generation_result
        if not self.hallucination_gate_require_period_match:
            return generation_result
        if not self._hallucination_gate_period_mismatch(message, documents):
            return generation_result
        logger.info("환각 게이트: 질문 기간과 문서 기간 불일치 → '확인 불가' 응답으로 교체")
        return replace(
            generation_result,
            answer=self.hallucination_gate_no_answer_message,
            text=self.hallucination_gate_no_answer_message,
        )


    @observe(name="Self-RAG Quality Verification", capture_input=False, capture_output=False)
    async def self_rag_verify(
        self,
        message: str,
        session_id: str,
        generation_result: GenerationResult,
        documents: list[Any],
        options: dict[str, Any],
    ) -> GenerationResult:
        """
        6단계: Self-RAG 품질 검증 (선택적)

        RAGPipeline이 이미 생성한 답변의 품질을 평가하고, 필요시에만 재생성합니다.
        기존 검색/생성 결과를 재활용하여 중복을 최소화합니다.

        워크플로우:
        1. 복잡도 계산 (낮으면 품질 검증 스킵)
        2. 기존 답변 품질 평가 (재검색/재생성 없이 평가만!)
        3. 품질 >= 0.8 → 기존 답변 그대로 사용 ✅
        4. 품질 < 0.8 → 재검색(15개) + 재생성 + Rollback 판단

        Args:
            message: 사용자 질문
            session_id: 세션 ID
            generation_result: RAGPipeline이 생성한 초기 답변
            documents: RAGPipeline이 검색한 문서 리스트
            options: 추가 옵션

        Returns:
            GenerationResult: 최종 답변 (기존 답변 또는 재생성 답변)
        """
        from ....modules.core.generation.generator import GenerationResult

        logger.debug("[6단계] Self-RAG 품질 검증 시작")

        # ⭐ 디버깅 추적 데이터 추출
        debug_trace_data = options.get("_debug_trace_data")

        # Self-RAG 비활성화 확인
        self_rag_config = self.config.get("self_rag", {})
        if not self_rag_config.get("enabled", False):
            logger.debug("Self-RAG 비활성화 - 기존 답변 사용")
            return generation_result

        # Future 객체 해결
        self_rag_module = self.self_rag_module
        if self_rag_module:
            if asyncio.iscoroutine(self_rag_module) or isinstance(self_rag_module, asyncio.Future):
                self_rag_module = await self_rag_module

        # Self-RAG 모듈 없음
        if not self_rag_module:
            logger.debug("Self-RAG 모듈 없음 - 기존 답변 사용")
            return generation_result

        try:
            logger.info("Self-RAG 품질 검증 시작 (기존 답변 재활용 모드)")

            # ✅ 최적화: verify_existing_answer 메서드 사용 (중복 제거)
            # RAGPipeline이 이미 생성한 답변과 문서를 전달
            # 재생성 시 사용자 옵션(응답 언어/모델/스타일 등)을 보존한다.
            # 파이프라인 내부 전용 키(_debug_trace_data)는 제외한다.
            verify_options = {
                key: value
                for key, value in options.items()
                if key != "_debug_trace_data"
            }
            # Match the main retrieval path's data_source mapping and score option.
            verify_options["filters"] = self._build_retrieval_filters(options)
            verify_options.setdefault("min_score", self.min_score)
            self_rag_result = await self_rag_module.verify_existing_answer(
                query=message,
                existing_answer=generation_result.answer,  # ✅ 기존 답변 전달
                existing_docs=documents,  # ✅ 기존 문서 전달
                session_id=session_id,
                options=verify_options,
            )

            # Self-RAG가 적용되었는지 확인
            if self_rag_result.used_self_rag:
                logger.info(
                    "Self-RAG 검증 완료",
                    extra={
                        "complexity": self_rag_result.complexity.score,
                        "regenerated": self_rag_result.regenerated
                    }
                )

                # ⭐ Self-RAG 평가 추적
                if (debug_trace_data is not None
                        and self_rag_result.initial_quality is not None
                        and self_rag_result.final_quality is not None):
                    debug_trace_data["self_rag_evaluation"] = {
                        "initial_quality": self_rag_result.initial_quality.overall,
                        "regenerated": self_rag_result.regenerated,
                        "final_quality": self_rag_result.final_quality.overall,
                        "reason": self_rag_result.initial_quality.reasoning,
                    }

                # ⭐ 품질 게이트 적용
                min_quality = self_rag_config.get("min_quality_to_answer", 0.6)
                final_quality_score = (
                    self_rag_result.final_quality.overall
                    if self_rag_result.final_quality is not None
                    else None
                )

                if final_quality_score is not None and final_quality_score < min_quality:
                    logger.warning(
                        "저품질 답변 감지 - 답변 거부",
                        extra={
                            "score": final_quality_score,
                            "threshold": min_quality
                        }
                    )

                    # 거부 메시지 반환
                    return GenerationResult(
                        answer=self.self_rag_low_quality_reject_message,
                        text=self.self_rag_low_quality_reject_text,
                        tokens_used=generation_result.tokens_used + self_rag_result.tokens_used,
                        model_used=generation_result.model_used,
                        provider=generation_result.provider,
                        generation_time=generation_result.generation_time,
                        refusal_reason="quality_too_low",  # ⭐ 신규 필드
                        quality_score=final_quality_score,  # ⭐ 신규 필드
                        quality_status=self_rag_result.outcome.value,
                        source_documents=None,
                        _model_info_override={
                            **generation_result.model_info,
                            "self_rag_applied": True,
                            "self_rag_regenerated": self_rag_result.regenerated,
                            "self_rag_outcome": self_rag_result.outcome.value,
                            "self_rag_eval_status": (
                                self_rag_result.initial_eval_status.value
                                if self_rag_result.initial_eval_status is not None
                                else None
                            ),
                            "self_rag_final_eval_status": (
                                self_rag_result.final_eval_status.value
                                if self_rag_result.final_eval_status is not None
                                else None
                            ),
                            "self_rag_rollback_reason": self_rag_result.rollback_reason,
                            "self_rag_skip_reason": None,
                        },
                    )
                if final_quality_score is None:
                    logger.warning(
                        "self_rag_quality_unavailable",
                        outcome=self_rag_result.outcome.value,
                    )

                # 품질 점수 로깅 및 Langfuse Score 기록
                if self_rag_result.initial_quality:
                    initial_q = self_rag_result.initial_quality.overall
                    logger.info("초기 품질", extra={"score": initial_q})

                    # Langfuse Score 기록: 초기 품질
                    try:
                        langfuse_context.score_current_trace(
                            name="self_rag_initial_quality",
                            value=initial_q,
                            comment=f"Self-RAG 초기 답변 품질 (complexity: {self_rag_result.complexity.score:.2f})",
                        )
                    except Exception as e:
                        logger.debug(f"Langfuse Score 기록 실패 (무시): {e}")

                    if self_rag_result.regenerated and self_rag_result.final_quality:
                        final_q = self_rag_result.final_quality.overall
                        improvement = final_q - initial_q
                        logger.info(
                            "품질 비교",
                            extra={
                                "initial": initial_q,
                                "final": final_q,
                                "improvement": improvement
                            }
                        )

                        # Langfuse Score 기록: 최종 품질 및 개선도
                        try:
                            langfuse_context.score_current_trace(
                                name="self_rag_final_quality",
                                value=final_q,
                                comment=f"Self-RAG 재생성 후 품질 (improvement: {improvement:+.2f})",
                            )
                            langfuse_context.score_current_trace(
                                name="self_rag_improvement",
                                value=improvement,
                                comment="Self-RAG 품질 개선도 (final - initial)",
                            )
                        except Exception as e:
                            logger.debug(f"Langfuse Score 기록 실패 (무시): {e}")

                # Self-RAG 답변 출력 누출 검사
                answer = self_rag_result.answer
                if contains_output_leakage(answer):
                    logger.error(
                        "프롬프트 누출 감지 (Self-RAG) - 답변 차단",
                        extra={"preview": answer[:100]}
                    )
                    answer = self.prompt_leakage_blocked_message
                    self.performance_metrics.record_error("prompt_leakage_blocked")

                # Self-RAG 답변으로 교체 (재생성됐든 안 됐든)
                return GenerationResult(
                    answer=answer,
                    text=answer,
                    tokens_used=generation_result.tokens_used + self_rag_result.tokens_used,
                    model_used=generation_result.model_used,
                    provider=generation_result.provider,
                    generation_time=generation_result.generation_time,
                    model_config=generation_result.model_config,
                    quality_score=final_quality_score,  # ⭐ 신규 필드
                    quality_status=self_rag_result.outcome.value,
                    source_documents=self_rag_result.selected_documents,
                    _model_info_override={
                        **generation_result.model_info,
                        "self_rag_applied": True,
                        "self_rag_regenerated": self_rag_result.regenerated,
                        "complexity_score": self_rag_result.complexity.score,
                        "initial_quality": (
                            self_rag_result.initial_quality.overall
                            if self_rag_result.initial_quality
                            else None
                        ),
                        "final_quality": (
                            self_rag_result.final_quality.overall
                            if self_rag_result.final_quality
                            else None
                        ),
                        "self_rag_outcome": self_rag_result.outcome.value,
                        "self_rag_eval_status": (
                            self_rag_result.initial_eval_status.value
                            if self_rag_result.initial_eval_status is not None
                            else None
                        ),
                        "self_rag_final_eval_status": (
                            self_rag_result.final_eval_status.value
                            if self_rag_result.final_eval_status is not None
                            else None
                        ),
                        "self_rag_rollback_reason": self_rag_result.rollback_reason,
                        "self_rag_skip_reason": None,
                    },
                )
            else:
                logger.info(
                    "Self-RAG 미적용 - 기존 답변 사용",
                    extra={
                        "complexity": self_rag_result.complexity.score,
                        "reason": self_rag_result.metadata.get("reason"),
                    }
                )
                # Self-RAG 미적용 시에도 메타데이터 추가 (API 응답 완전성 보장)
                return GenerationResult(
                    answer=generation_result.answer,
                    text=generation_result.text,
                    tokens_used=generation_result.tokens_used,
                    model_used=generation_result.model_used,
                    provider=generation_result.provider,
                    generation_time=generation_result.generation_time,
                    model_config=generation_result.model_config,
                    _model_info_override={
                        **generation_result.model_info,
                        "self_rag_applied": False,
                        "complexity_score": self_rag_result.complexity.score,
                        "self_rag_outcome": self_rag_result.outcome.value,
                        "self_rag_final_eval_status": (
                            self_rag_result.final_eval_status.value
                            if self_rag_result.final_eval_status is not None
                            else None
                        ),
                        "self_rag_rollback_reason": self_rag_result.rollback_reason,
                        "self_rag_skip_reason": self_rag_result.metadata.get("reason"),
                    },
                )

        except Exception as e:
            logger.warning(
                "[6단계] Self-RAG 검증 실패, 기존 답변 사용",
                extra={"error": str(e)},
                exc_info=True
            )
            return generation_result

