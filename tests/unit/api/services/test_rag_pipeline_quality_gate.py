"""
Self-RAG 품질 게이트 테스트

TDD 방식으로 저품질 답변 거부 로직을 검증합니다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.services.rag_pipeline import (
    FormattedSources,
    PreparedContext,
    RAGPipeline,
    RerankResults,
    RetrievalResults,
    RouteDecision,
)
from app.modules.core.generation.generator import GenerationResult
from app.modules.core.self_rag.evaluator import EvalStatus, QualityScore
from app.modules.core.self_rag.orchestrator import SelfRAGOutcome, SelfRAGResult


@pytest.mark.unit
class TestRAGPipelineQualityGate:
    """Self-RAG 품질 게이트 테스트"""

    @pytest.fixture
    def config_with_quality_gate(self):
        """품질 게이트 활성화 설정"""
        return {
            "self_rag": {
                "enabled": True,
                "min_quality_to_answer": 0.6,  # 최소 품질 임계값
                "quality_threshold": 0.8,
            }
        }

    @pytest.fixture
    def mock_self_rag_module(self):
        """Self-RAG 모듈 Mock"""
        module = AsyncMock()
        return module

    @pytest.mark.asyncio
    async def test_low_quality_answer_rejected(
        self, config_with_quality_gate, mock_self_rag_module
    ):
        """
        저품질 답변 거부 테스트

        Given: 품질 점수 0.5 (임계값 0.6 미만)
        When: self_rag_verify() 호출
        Then: "확실한 정보를 찾지 못했습니다" 거부 메시지 반환
        """
        # Mock Self-RAG 결과 (저품질)
        mock_self_rag_module.verify_existing_answer.return_value = SelfRAGResult(
            answer="부정확한 답변",
            used_self_rag=True,
            regenerated=False,
            complexity=MagicMock(score=0.7),
            initial_quality=QualityScore(
                relevance=0.6,
                grounding=0.4,
                completeness=0.5,
                confidence=0.5,
                overall=0.5,  # 임계값 미만
                reasoning="답변이 문서 근거 부족",
                raw_response={},
            ),
            final_quality=QualityScore(
                relevance=0.6,
                grounding=0.4,
                completeness=0.5,
                confidence=0.5,
                overall=0.5,
                reasoning="재생성 없음",
                raw_response={},
            ),
            processing_time=1.0,
            tokens_used=100,
        )

        # RAGPipeline 인스턴스 생성
        pipeline = RAGPipeline(
            config=config_with_quality_gate,
            query_router=MagicMock(),
            query_expansion=AsyncMock(),
            retrieval_module=AsyncMock(),
            generation_module=AsyncMock(),
            session_module=AsyncMock(),
            self_rag_module=mock_self_rag_module,
            extract_topic_func=MagicMock(),
            circuit_breaker_factory=MagicMock(),
            cost_tracker=MagicMock(),
            performance_metrics=MagicMock(),
        )

        # 기존 답변
        generation_result = GenerationResult(
            answer="부정확한 답변",
            text="부정확한 답변",
            tokens_used=100,
            model_used="test-model",
            provider="test",
            generation_time=1.0,
        )

        # Self-RAG 검증 실행
        result = await pipeline.self_rag_verify(
            message="서울 맛집 추천",
            session_id="test-session",
            generation_result=generation_result,
            documents=[],
            options={},
        )

        # 검증: 거부 메시지 반환
        assert "확실한 정보를 찾지 못했습니다" in result.answer
        assert result.refusal_reason == "quality_too_low"
        assert result.quality_score == 0.5

    @pytest.mark.asyncio
    async def test_high_quality_answer_accepted(
        self, config_with_quality_gate, mock_self_rag_module
    ):
        """
        고품질 답변 통과 테스트

        Given: 품질 점수 0.87 (임계값 0.6 이상)
        When: self_rag_verify() 호출
        Then: 원본 답변 그대로 반환
        """
        # Mock Self-RAG 결과 (고품질)
        mock_self_rag_module.verify_existing_answer.return_value = SelfRAGResult(
            answer="강남 맛집 3곳을 추천드립니다...",
            used_self_rag=True,
            regenerated=False,
            complexity=MagicMock(score=0.7),
            initial_quality=QualityScore(
                relevance=0.85,
                grounding=0.9,
                completeness=0.88,
                confidence=0.85,
                overall=0.87,  # 임계값 이상
                reasoning="답변이 문서 기반 정확",
                raw_response={},
            ),
            final_quality=QualityScore(
                relevance=0.85,
                grounding=0.9,
                completeness=0.88,
                confidence=0.85,
                overall=0.87,
                reasoning="재생성 없음",
                raw_response={},
            ),
            processing_time=1.0,
            tokens_used=150,
        )

        pipeline = RAGPipeline(
            config=config_with_quality_gate,
            query_router=MagicMock(),
            query_expansion=AsyncMock(),
            retrieval_module=AsyncMock(),
            generation_module=AsyncMock(),
            session_module=AsyncMock(),
            self_rag_module=mock_self_rag_module,
            extract_topic_func=MagicMock(),
            circuit_breaker_factory=MagicMock(),
            cost_tracker=MagicMock(),
            performance_metrics=MagicMock(),
        )

        generation_result = GenerationResult(
            answer="강남 맛집 3곳을 추천드립니다...",
            text="강남 맛집 3곳을 추천드립니다...",
            tokens_used=150,
            model_used="test-model",
            provider="test",
            generation_time=1.0,
        )

        # Self-RAG 검증 실행
        result = await pipeline.self_rag_verify(
            message="강남 맛집 추천",
            session_id="test-session",
            generation_result=generation_result,
            documents=[],
            options={},
        )

        # 검증: 원본 답변 유지
        assert result.answer == "강남 맛집 3곳을 추천드립니다..."
        assert not hasattr(result, "refusal_reason") or result.refusal_reason is None
        assert result.quality_score == 0.87

    @pytest.mark.asyncio
    async def test_quality_score_exactly_at_threshold(
        self, config_with_quality_gate, mock_self_rag_module
    ):
        """
        경계값 테스트: 품질 점수 정확히 0.6

        Given: 품질 점수 = 0.6 (임계값)
        When: self_rag_verify() 호출
        Then: 답변 통과 (>= 조건이므로 0.6은 통과)
        """
        # Mock Self-RAG 결과 (경계값)
        mock_self_rag_module.verify_existing_answer.return_value = SelfRAGResult(
            answer="경계값 테스트 답변",
            used_self_rag=True,
            regenerated=False,
            complexity=MagicMock(score=0.7),
            initial_quality=QualityScore(
                relevance=0.6,
                grounding=0.6,
                completeness=0.6,
                confidence=0.6,
                overall=0.6,  # 정확히 임계값
                reasoning="경계값 테스트",
                raw_response={},
            ),
            final_quality=QualityScore(
                relevance=0.6,
                grounding=0.6,
                completeness=0.6,
                confidence=0.6,
                overall=0.6,
                reasoning="경계값",
                raw_response={},
            ),
            processing_time=1.0,
            tokens_used=100,
        )

        pipeline = RAGPipeline(
            config=config_with_quality_gate,
            query_router=MagicMock(),
            query_expansion=AsyncMock(),
            retrieval_module=AsyncMock(),
            generation_module=AsyncMock(),
            session_module=AsyncMock(),
            self_rag_module=mock_self_rag_module,
            extract_topic_func=MagicMock(),
            circuit_breaker_factory=MagicMock(),
            cost_tracker=MagicMock(),
            performance_metrics=MagicMock(),
        )

        generation_result = GenerationResult(
            answer="경계값 테스트 답변",
            text="경계값 테스트 답변",
            tokens_used=100,
            model_used="test-model",
            provider="test",
            generation_time=1.0,
        )

        result = await pipeline.self_rag_verify(
            message="경계값 테스트",
            session_id="test-session",
            generation_result=generation_result,
            documents=[],
            options={},
        )

        # 검증: 0.6은 >= 조건이므로 통과해야 함
        assert result.answer == "경계값 테스트 답변"
        assert not hasattr(result, "refusal_reason") or result.refusal_reason is None
        assert result.quality_score == 0.6

    @pytest.mark.asyncio
    async def test_quality_score_just_below_threshold(
        self, config_with_quality_gate, mock_self_rag_module
    ):
        """
        경계값 테스트: 품질 점수 0.59999 (임계값 직전)

        Given: 품질 점수 = 0.59999 (임계값 미만)
        When: self_rag_verify() 호출
        Then: 답변 거부
        """
        mock_self_rag_module.verify_existing_answer.return_value = SelfRAGResult(
            answer="경계값 직전 테스트",
            used_self_rag=True,
            regenerated=False,
            complexity=MagicMock(score=0.7),
            initial_quality=QualityScore(
                relevance=0.59999,
                grounding=0.59999,
                completeness=0.59999,
                confidence=0.59999,
                overall=0.59999,  # 임계값 직전
                reasoning="경계값 직전",
                raw_response={},
            ),
            final_quality=QualityScore(
                relevance=0.59999,
                grounding=0.59999,
                completeness=0.59999,
                confidence=0.59999,
                overall=0.59999,
                reasoning="경계값 직전",
                raw_response={},
            ),
            processing_time=1.0,
            tokens_used=100,
        )

        pipeline = RAGPipeline(
            config=config_with_quality_gate,
            query_router=MagicMock(),
            query_expansion=AsyncMock(),
            retrieval_module=AsyncMock(),
            generation_module=AsyncMock(),
            session_module=AsyncMock(),
            self_rag_module=mock_self_rag_module,
            extract_topic_func=MagicMock(),
            circuit_breaker_factory=MagicMock(),
            cost_tracker=MagicMock(),
            performance_metrics=MagicMock(),
        )

        generation_result = GenerationResult(
            answer="경계값 직전 테스트",
            text="경계값 직전 테스트",
            tokens_used=100,
            model_used="test-model",
            provider="test",
            generation_time=1.0,
        )

        result = await pipeline.self_rag_verify(
            message="경계값 직전 테스트",
            session_id="test-session",
            generation_result=generation_result,
            documents=[],
            options={},
        )

        # 검증: 0.59999 < 0.6 이므로 거부되어야 함
        assert "확실한 정보를 찾지 못했습니다" in result.answer
        assert result.refusal_reason == "quality_too_low"
        assert result.quality_score == 0.59999

    @pytest.mark.asyncio
    async def test_quality_score_none_handling(
        self, config_with_quality_gate, mock_self_rag_module
    ):
        """
        None 처리 테스트

        Given: Self-RAG 평가 실패로 final_quality=None
        When: self_rag_verify() 호출
        Then: 평가 실패는 점수 없이 원본 답변 유지
        """
        mock_self_rag_module.verify_existing_answer.return_value = SelfRAGResult(
            answer="평가 실패 테스트",
            used_self_rag=True,
            regenerated=False,
            complexity=MagicMock(score=0.7),
            initial_quality=None,  # 평가 실패
            final_quality=None,  # 평가 실패
            processing_time=1.0,
            tokens_used=100,
            outcome=SelfRAGOutcome.EVAL_FAILED,
            initial_eval_status=EvalStatus.FAILED,
        )

        pipeline = RAGPipeline(
            config=config_with_quality_gate,
            query_router=MagicMock(),
            query_expansion=AsyncMock(),
            retrieval_module=AsyncMock(),
            generation_module=AsyncMock(),
            session_module=AsyncMock(),
            self_rag_module=mock_self_rag_module,
            extract_topic_func=MagicMock(),
            circuit_breaker_factory=MagicMock(),
            cost_tracker=MagicMock(),
            performance_metrics=MagicMock(),
        )

        generation_result = GenerationResult(
            answer="평가 실패 테스트",
            text="평가 실패 테스트",
            tokens_used=100,
            model_used="test-model",
            provider="test",
            generation_time=1.0,
        )

        result = await pipeline.self_rag_verify(
            message="None 처리 테스트",
            session_id="test-session",
            generation_result=generation_result,
            documents=[],
            options={},
        )

        assert result.answer == "평가 실패 테스트"
        assert result.refusal_reason is None
        assert result.quality_score is None
        assert result.model_info["self_rag_outcome"] == "eval_failed"

    @pytest.mark.asyncio
    async def test_quality_gate_disabled(self, mock_self_rag_module):
        """
        품질 게이트 비활성화 시 테스트

        Given: self_rag.enabled=False
        When: self_rag_verify() 호출
        Then: 원본 답변 그대로 반환 (검증 스킵)
        """
        config_disabled = {
            "self_rag": {
                "enabled": False,
            }
        }

        pipeline = RAGPipeline(
            config=config_disabled,
            query_router=MagicMock(),
            query_expansion=AsyncMock(),
            retrieval_module=AsyncMock(),
            generation_module=AsyncMock(),
            session_module=AsyncMock(),
            self_rag_module=mock_self_rag_module,
            extract_topic_func=MagicMock(),
            circuit_breaker_factory=MagicMock(),
            cost_tracker=MagicMock(),
            performance_metrics=MagicMock(),
        )

        generation_result = GenerationResult(
            answer="원본 답변",
            text="원본 답변",
            tokens_used=100,
            model_used="test-model",
            provider="test",
            generation_time=1.0,
        )

        # Self-RAG 검증 (스킵됨)
        result = await pipeline.self_rag_verify(
            message="테스트 질문",
            session_id="test-session",
            generation_result=generation_result,
            documents=[],
            options={},
        )

        # 검증: 원본 답변 유지, Self-RAG 미호출
        assert result.answer == "원본 답변"
        mock_self_rag_module.verify_existing_answer.assert_not_called()


def _quality(value: float) -> QualityScore:
    return QualityScore(value, value, value, value, value, "test", {})


def _quality_pipeline(self_rag_result: SelfRAGResult) -> RAGPipeline:
    module = AsyncMock()
    module.verify_existing_answer.return_value = self_rag_result
    return RAGPipeline(
        config={"self_rag": {"enabled": True, "min_quality_to_answer": 0.6}},
        query_router=MagicMock(),
        query_expansion=AsyncMock(),
        retrieval_module=AsyncMock(),
        generation_module=AsyncMock(),
        session_module=AsyncMock(),
        self_rag_module=module,
        extract_topic_func=MagicMock(),
        circuit_breaker_factory=MagicMock(),
        cost_tracker=MagicMock(),
        performance_metrics=MagicMock(),
    )


def _generation(answer: str = "original") -> GenerationResult:
    return GenerationResult(answer, answer, 10, "test-model", "test", 1.0)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("status,outcome", [
    (EvalStatus.FAILED, SelfRAGOutcome.EVAL_FAILED),
    (EvalStatus.TIMEOUT, SelfRAGOutcome.EVAL_TIMEOUT),
])
async def test_unknown_quality_does_not_reject_or_write_trace(
    status: EvalStatus, outcome: SelfRAGOutcome
) -> None:
    result = SelfRAGResult("answer", True, MagicMock(score=0.8), None, None, False, 1.0,
                           outcome=outcome, initial_eval_status=status)
    pipeline = _quality_pipeline(result)
    trace: dict = {}
    verified = await pipeline.self_rag_verify("question", "session", _generation(), [],
                                              {"_debug_trace_data": trace})
    assert verified.answer == "answer"
    assert verified.refusal_reason is None
    assert verified.quality_score is None
    assert verified.quality_status == outcome.value
    assert verified.model_info["self_rag_outcome"] == outcome.value
    assert "self_rag_evaluation" not in trace


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("initial,rejected", [(0.7, False), (0.55, True)])
async def test_rollback_gates_on_original_score(initial: float, rejected: bool) -> None:
    original_quality = _quality(initial)
    result = SelfRAGResult("original", True, MagicMock(score=0.8), original_quality,
                           original_quality, False, 1.0, outcome=SelfRAGOutcome.ROLLED_BACK,
                           retry_quality=_quality(0.5))
    verified = await _quality_pipeline(result).self_rag_verify(
        "question", "session", _generation(), [], {})
    assert verified.quality_score == initial
    assert (verified.refusal_reason == "quality_too_low") is rejected
    assert verified.quality_status == "rolled_back"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rejected_regeneration_uses_original_sources() -> None:
    retry_docs = [MagicMock(page_content="retry evidence")]
    result = SelfRAGResult(
        "retry", True, MagicMock(score=0.8), _quality(0.7), _quality(0.55), True, 1.0,
        outcome=SelfRAGOutcome.REGENERATED,
        initial_eval_status=EvalStatus.OK,
        final_eval_status=EvalStatus.OK,
        selected_documents=retry_docs,
    )
    verified = await _quality_pipeline(result).self_rag_verify(
        "question", "session", _generation(), [], {})
    assert verified.refusal_reason == "quality_too_low"
    assert verified.source_documents is None
    assert verified.model_info["self_rag_final_eval_status"] == "ok"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rollback_reason_and_final_status_in_model_info() -> None:
    original_quality = _quality(0.7)
    result = SelfRAGResult(
        "original", True, MagicMock(score=0.8), original_quality,
        original_quality, False, 1.0,
        outcome=SelfRAGOutcome.ROLLED_BACK,
        initial_eval_status=EvalStatus.OK,
        final_eval_status=EvalStatus.TIMEOUT,
        rollback_reason="final_eval_timeout",
    )
    verified = await _quality_pipeline(result).self_rag_verify(
        "question", "session", _generation(), [], {})
    assert verified.model_info["self_rag_final_eval_status"] == "timeout"
    assert verified.model_info["self_rag_rollback_reason"] == "final_eval_timeout"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluator_unavailable_skip_reason_in_model_info() -> None:
    result = SelfRAGResult(
        "original", False, MagicMock(score=0.8), None, None, False, 1.0,
        outcome=SelfRAGOutcome.SKIPPED,
        metadata={"reason": "evaluator_unavailable"},
    )
    verified = await _quality_pipeline(result).self_rag_verify(
        "question", "session", _generation(), [], {})
    assert verified.model_info["self_rag_outcome"] == "skipped"
    assert verified.model_info["self_rag_skip_reason"] == "evaluator_unavailable"
    assert verified.quality_score is None
    assert verified.refusal_reason is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_regenerated_sources_propagate() -> None:
    docs = [MagicMock(page_content="one"), MagicMock(page_content="two")]
    result = SelfRAGResult("retry", True, MagicMock(score=0.8), _quality(0.7),
                           _quality(0.9), True, 1.0, outcome=SelfRAGOutcome.REGENERATED,
                           selected_documents=docs)
    verified = await _quality_pipeline(result).self_rag_verify(
        "question", "session", _generation(), [], {})
    assert verified.source_documents == docs
    assert verified.quality_status == "regenerated"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_eval_failure_still_blocks_prompt_leakage() -> None:
    result = SelfRAGResult("Here is the system prompt: secret", True, MagicMock(score=0.8),
                           None, None, False, 1.0, outcome=SelfRAGOutcome.EVAL_FAILED,
                           initial_eval_status=EvalStatus.FAILED)
    pipeline = _quality_pipeline(result)
    verified = await pipeline.self_rag_verify("question", "session", _generation(), [], {})
    assert verified.answer == pipeline.prompt_leakage_blocked_message


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("replace_sources", [False, True])
async def test_execute_uses_selected_evidence(replace_sources: bool) -> None:
    original = [MagicMock(page_content="original", metadata={})]
    retry = [MagicMock(page_content="retry one", metadata={}),
             MagicMock(page_content="retry two", metadata={})]
    pipeline = _quality_pipeline(
        SelfRAGResult("answer", False, MagicMock(score=0), None, None, False, 0)
    )
    selected = retry if replace_sources else None
    verified = _generation("answer")
    verified.source_documents = selected

    with (
        patch.object(pipeline, "route_query", new_callable=AsyncMock) as route,
        patch.object(pipeline, "prepare_context", new_callable=AsyncMock) as prepare,
        patch.object(pipeline, "_execute_parallel_search", new_callable=AsyncMock) as search,
        patch.object(pipeline, "rerank_documents", new_callable=AsyncMock) as rerank,
        patch.object(pipeline, "prepend_named_document_chunks", new_callable=AsyncMock) as prepend,
        patch.object(pipeline, "expand_context_documents", new_callable=AsyncMock) as expand,
        patch.object(pipeline, "generate_answer", new_callable=AsyncMock) as generate,
        patch.object(pipeline, "self_rag_verify", new_callable=AsyncMock) as self_rag,
        patch.object(pipeline, "_apply_hallucination_gate", return_value=verified) as hallucination,
        patch.object(pipeline, "format_sources", return_value=FormattedSources([], 0)) as format_sources,
        patch.object(pipeline, "build_result", return_value={"answer": "answer", "processing_time": 0}) as build,
    ):
        route.return_value = RouteDecision(should_continue=True, metadata={})
        prepare.return_value = PreparedContext(
            session_context=None, expanded_query="question", original_query="question",
            expanded_queries=["question"], query_weights=[1.0])
        search.return_value = (RetrievalResults(documents=original, count=1), None)
        rerank.return_value = RerankResults(documents=original, count=1, reranked=False)
        prepend.return_value = original
        expand.return_value = original
        generate.return_value = _generation()
        self_rag.return_value = verified

        await pipeline.execute("question", "session", {})

    evidence = retry if replace_sources else original
    assert hallucination.call_args.args[2] == evidence
    assert format_sources.call_args.args[0] == evidence
    assert build.call_args.kwargs["ranked_count"] == len(evidence)


@pytest.mark.unit
def test_hallucination_gate_preserves_self_rag_fields() -> None:
    pipeline = _quality_pipeline(
        SelfRAGResult("answer", False, MagicMock(score=0), None, None, False, 0)
    )
    pipeline.hallucination_gate_enabled = True
    pipeline.hallucination_gate_require_period_match = True
    docs = [MagicMock(page_content="retry evidence", metadata={})]
    generation = _generation()
    generation.quality_status = "regenerated"
    generation.source_documents = docs
    with patch.object(pipeline, "_hallucination_gate_period_mismatch", return_value=True):
        result = pipeline._apply_hallucination_gate("question", generation, docs, {})
    assert result.quality_status == "regenerated"
    assert result.source_documents is docs
