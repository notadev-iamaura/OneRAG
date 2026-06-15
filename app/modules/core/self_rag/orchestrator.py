"""
Self-RAG 오케스트레이터

쿼리 복잡도 계산, 검색, 생성, 평가, 재생성을 조율합니다.
"""

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from ..routing import ComplexityCalculator, ComplexityResult
from .evaluator import LLMQualityEvaluator, QualityScore

logger = structlog.get_logger(__name__)


@dataclass
class SelfRAGResult:
    """Self-RAG 처리 결과"""

    answer: str
    used_self_rag: bool
    complexity: ComplexityResult
    initial_quality: QualityScore | None
    final_quality: QualityScore | None
    regenerated: bool
    processing_time: float
    metadata: dict[str, Any] = field(
        default_factory=dict
    )  # 기본값 추가 (dataclass 필드 순서 문제 해결)
    tokens_used: int = 0  # 재생성 시 토큰 수 추적


class SelfRAGOrchestrator:
    """Self-RAG 오케스트레이터"""

    def __init__(
        self,
        complexity_calculator: ComplexityCalculator,
        evaluator: LLMQualityEvaluator,
        retrieval_module: Any,
        generation_module: Any,
        initial_top_k: int = 5,
        retry_top_k: int = 15,
        max_retries: int = 1,
        enabled: bool = True,
    ):
        self.complexity_calculator = complexity_calculator
        self.evaluator = evaluator
        self.retrieval_module = retrieval_module
        self.generation_module = generation_module
        self.initial_top_k = initial_top_k
        self.retry_top_k = retry_top_k
        self.max_retries = max_retries
        self.enabled = enabled

        # Rollback 설정 (config에서 가져와야 하지만 일단 기본값)
        self.enable_rollback = True
        self.rollback_threshold = -0.1

        logger.info(
            "self_rag_orchestrator_initialized",
            initial_top_k=initial_top_k,
            retry_top_k=retry_top_k,
            max_retries=max_retries,
            enabled=enabled,
        )

    async def process(self, query: str, session_id: str, **kwargs: Any) -> SelfRAGResult:
        """
        Self-RAG 프로세스 실행

        Args:
            query: 사용자 질문
            session_id: 세션 ID
            **kwargs: 추가 파라미터 (collection_name 등)

        Returns:
            SelfRAGResult: 처리 결과
        """
        start_time = time.time()

        if not self.enabled:
            return await self._regular_flow(query, session_id, start_time, **kwargs)

        complexity = await self.complexity_calculator.calculate(query)

        if not self.complexity_calculator.requires_self_rag(complexity):
            logger.info("complexity_too_low_skipping_self_rag", score=complexity.score)
            return await self._regular_flow(query, session_id, start_time, complexity, **kwargs)

        logger.info("starting_self_rag_flow", score=complexity.score)

        # 호출자 dict를 복사해 부수효과(limit 주입)를 차단하고, 사용자 옵션
        # (응답 언어/모델/스타일 등)을 검색·생성에 모두 보존한다.
        base_options = dict(kwargs.get("options") or {})
        search_options = {**base_options, "limit": self.initial_top_k}
        initial_docs = await self.retrieval_module.search(query, search_options)

        # generate_answer 메서드 사용 (generate 아님)
        generation_result = await self.generation_module.generate_answer(
            query=query, context_documents=initial_docs, options=base_options
        )
        initial_answer = generation_result.answer  # GenerationResult에서 answer 추출

        initial_quality = await self.evaluator.evaluate(
            query=query, answer=initial_answer, context=[doc.content for doc in initial_docs]
        )

        if not self.evaluator.requires_regeneration(initial_quality):
            logger.info(
                "initial_quality_sufficient",
                score=initial_quality.overall,
                threshold=self.evaluator.quality_threshold,
            )
            processing_time = time.time() - start_time
            return SelfRAGResult(
                answer=initial_answer,
                used_self_rag=True,
                complexity=complexity,
                initial_quality=initial_quality,
                final_quality=initial_quality,
                regenerated=False,
                processing_time=processing_time,
                metadata={"initial_top_k": self.initial_top_k, "docs_retrieved": len(initial_docs)},
            )

        logger.warning(
            "quality_insufficient_regenerating",
            score=initial_quality.overall,
            threshold=self.evaluator.quality_threshold,
        )

        retry_search_options = {**base_options, "limit": self.retry_top_k}
        retry_docs = await self.retrieval_module.search(query, retry_search_options)

        # generate_answer 메서드 사용 (generate 아님)
        final_generation_result = await self.generation_module.generate_answer(
            query=query, context_documents=retry_docs, options=base_options
        )
        final_answer = final_generation_result.answer  # GenerationResult에서 answer 추출
        final_tokens = final_generation_result.tokens_used  # 재생성 시 토큰 수 추적

        final_quality = await self.evaluator.evaluate(
            query=query, answer=final_answer, context=[doc.content for doc in retry_docs]
        )

        processing_time = time.time() - start_time

        logger.info(
            "self_rag_completed",
            initial_quality=initial_quality.overall,
            final_quality=final_quality.overall,
            regenerated=True,
            processing_time=processing_time,
        )

        return SelfRAGResult(
            answer=final_answer,
            used_self_rag=True,
            complexity=complexity,
            initial_quality=initial_quality,
            final_quality=final_quality,
            regenerated=True,
            processing_time=processing_time,
            tokens_used=final_tokens,  # 재생성 시 토큰 수 저장
            metadata={
                "initial_top_k": self.initial_top_k,
                "retry_top_k": self.retry_top_k,
                "initial_docs": len(initial_docs),
                "retry_docs": len(retry_docs),
            },
        )

    async def verify_existing_answer(
        self,
        query: str,
        existing_answer: str,
        existing_docs: list[Any],
        session_id: str,
        options: dict[str, Any] | None = None,
    ) -> SelfRAGResult:
        """
        이미 생성된 답변의 품질을 검증하고 필요시 재생성

        RAGPipeline과 통합 시 사용하는 최적화된 메서드.
        기존 검색/생성 결과를 재활용하여 중복을 방지합니다.

        Args:
            query: 사용자 질문
            existing_answer: RAGPipeline에서 이미 생성한 답변
            existing_docs: RAGPipeline에서 이미 검색한 문서
            session_id: 세션 ID
            options: 검색/생성 옵션(응답 언어/모델/스타일 등). 재검색·재생성
                경로에 그대로 전달되어 사용자 옵션 소실을 방지한다. None이면
                빈 옵션으로 처리한다.

        Returns:
            SelfRAGResult: 검증 결과 (원본 또는 재생성 답변)
        """
        start_time = time.time()
        # 호출자 dict를 복사해 부수효과를 차단한다(limit 주입 등).
        base_options = dict(options or {})

        # 1. Self-RAG 비활성화 확인
        if not self.enabled:
            logger.info("self_rag_disabled", mode="verify_existing")
            return SelfRAGResult(
                answer=existing_answer,
                used_self_rag=False,
                complexity=ComplexityResult(0.0, 0.0, 0.0, 0.0, {}),
                initial_quality=None,
                final_quality=None,
                regenerated=False,
                processing_time=time.time() - start_time,
                metadata={"reason": "self_rag_disabled"},
            )

        # 2. 복잡도 계산
        complexity = await self.complexity_calculator.calculate(query)

        if not self.complexity_calculator.requires_self_rag(complexity):
            logger.info(
                "complexity_too_low_using_existing_answer",
                score=complexity.score,
                threshold=self.complexity_calculator.threshold,
            )
            return SelfRAGResult(
                answer=existing_answer,
                used_self_rag=False,
                complexity=complexity,
                initial_quality=None,
                final_quality=None,
                regenerated=False,
                processing_time=time.time() - start_time,
                metadata={"reason": "complexity_too_low", "existing_docs": len(existing_docs)},
            )

        logger.info("self_rag_verify_mode", complexity=complexity.score)

        # 3. 기존 답변 품질 평가 (검색/생성 없이 평가만!)
        try:
            initial_quality = await self.evaluator.evaluate(
                query=query,
                answer=existing_answer,
                context=[
                    doc.page_content if hasattr(doc, "page_content") else doc.content
                    for doc in existing_docs
                ],
            )

            logger.info(
                "existing_answer_quality_evaluated",
                quality=initial_quality.overall,
                threshold=self.evaluator.quality_threshold,
                relevance=initial_quality.relevance,
                grounding=initial_quality.grounding,
                completeness=initial_quality.completeness,
                confidence=initial_quality.confidence,
            )
        except Exception as e:
            logger.error(f"quality_evaluation_failed: {e}, using existing answer")
            return SelfRAGResult(
                answer=existing_answer,
                used_self_rag=True,
                complexity=complexity,
                initial_quality=None,
                final_quality=None,
                regenerated=False,
                processing_time=time.time() - start_time,
                metadata={"reason": "evaluation_error", "error": str(e)},
            )

        # 4. 품질이 충분하면 기존 답변 사용 (재생성 불필요)
        if not self.evaluator.requires_regeneration(initial_quality):
            logger.info(
                "existing_answer_quality_sufficient",
                score=initial_quality.overall,
                threshold=self.evaluator.quality_threshold,
            )
            processing_time = time.time() - start_time
            return SelfRAGResult(
                answer=existing_answer,  # ✅ 기존 답변 그대로 사용
                used_self_rag=True,
                complexity=complexity,
                initial_quality=initial_quality,
                final_quality=initial_quality,
                regenerated=False,
                processing_time=processing_time,
                metadata={"reason": "quality_sufficient", "existing_docs": len(existing_docs)},
            )

        # 5. 품질이 낮으면 재검색 및 재생성
        logger.warning(
            "quality_insufficient_regenerating",
            score=initial_quality.overall,
            threshold=self.evaluator.quality_threshold,
        )

        try:
            # 재검색 (더 많은 문서로) — 사용자 옵션 보존 + retry limit 적용
            retry_search_options = {**base_options, "limit": self.retry_top_k}
            retry_docs = await self.retrieval_module.search(query, retry_search_options)

            logger.info("retry_search_completed", docs_count=len(retry_docs))

            # 재생성 — 사용자 옵션(응답 언어/모델 등) 보존
            final_generation_result = await self.generation_module.generate_answer(
                query=query, context_documents=retry_docs, options=base_options
            )
            final_answer = final_generation_result.answer
            final_tokens = final_generation_result.tokens_used  # 재생성 시 토큰 수 추적

            # 재생성 품질 평가
            final_quality = await self.evaluator.evaluate(
                query=query,
                answer=final_answer,
                context=[
                    doc.page_content if hasattr(doc, "page_content") else doc.content
                    for doc in retry_docs
                ],
            )

            logger.info(
                "regeneration_completed",
                initial_quality=initial_quality.overall,
                final_quality=final_quality.overall,
                improvement=final_quality.overall - initial_quality.overall,
            )

            # 6. Rollback 결정 (재생성이 오히려 더 나쁘면 원본 유지)
            if (
                self.enable_rollback
                and final_quality.overall < initial_quality.overall + self.rollback_threshold
            ):
                logger.warning(
                    "quality_degraded_rollback_to_existing",
                    initial=initial_quality.overall,
                    final=final_quality.overall,
                    threshold=self.rollback_threshold,
                )
                processing_time = time.time() - start_time
                return SelfRAGResult(
                    answer=existing_answer,  # ✅ 원본 답변으로 롤백
                    used_self_rag=True,
                    complexity=complexity,
                    initial_quality=initial_quality,
                    final_quality=final_quality,
                    regenerated=False,  # 재생성 시도했으나 롤백
                    processing_time=processing_time,
                    tokens_used=0,  # 롤백 시 초기 토큰 수는 0 (기존 답변은 이미 추적됨)
                    metadata={
                        "reason": "rollback",
                        "regeneration_attempted": True,
                        "retry_docs": len(retry_docs),
                    },
                )

            # 7. 재생성 답변 사용
            processing_time = time.time() - start_time
            return SelfRAGResult(
                answer=final_answer,  # ✅ 재생성 답변 사용
                used_self_rag=True,
                complexity=complexity,
                initial_quality=initial_quality,
                final_quality=final_quality,
                regenerated=True,
                processing_time=processing_time,
                tokens_used=final_tokens,  # 재생성 시 토큰 수 저장
                metadata={
                    "retry_docs": len(retry_docs),
                    "improvement": final_quality.overall - initial_quality.overall,
                },
            )

        except Exception as e:
            logger.error(f"regeneration_failed: {e}, using existing answer")
            processing_time = time.time() - start_time
            return SelfRAGResult(
                answer=existing_answer,  # ✅ 에러 시 원본 답변 사용
                used_self_rag=True,
                complexity=complexity,
                initial_quality=initial_quality,
                final_quality=None,
                regenerated=False,
                processing_time=processing_time,
                metadata={"reason": "regeneration_error", "error": str(e)},
            )

    async def _regular_flow(
        self,
        query: str,
        session_id: str,
        start_time: float,
        complexity: ComplexityResult | None = None,
        **kwargs: Any,
    ) -> SelfRAGResult:
        """일반 RAG 플로우 (Self-RAG 미사용)"""
        # 호출자 dict를 복사해 부수효과(limit 주입)를 차단하고 사용자 옵션을 보존한다.
        base_options = dict(kwargs.get("options") or {})
        search_options = {**base_options, "limit": self.initial_top_k}
        docs = await self.retrieval_module.search(query, search_options)

        # generate_answer 메서드 사용 (generate 아님)
        generation_result = await self.generation_module.generate_answer(
            query=query, context_documents=docs, options=base_options
        )
        answer = generation_result.answer  # GenerationResult에서 answer 추출

        processing_time = time.time() - start_time

        return SelfRAGResult(
            answer=answer,
            used_self_rag=False,
            complexity=complexity or ComplexityResult(0.0, 0.0, 0.0, 0.0, {}),
            initial_quality=None,
            final_quality=None,
            regenerated=False,
            processing_time=processing_time,
            metadata={"docs_retrieved": len(docs)},
        )
