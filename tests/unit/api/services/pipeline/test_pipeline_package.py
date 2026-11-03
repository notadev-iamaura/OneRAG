"""rag_pipeline 분리(단계 믹스인 패키지) 회귀 테스트.

- RAGPipeline 은 단계 믹스인 조합으로 만들어지고, 분리 전 공개/비공개 메서드가 그대로 존재한다.
- 예전 모듈 경로(app.api.services.rag_pipeline)로 import 하던 헬퍼/상수/모델이 계속 제공된다.
- 믹스인은 PipelineStateBase 를 상속해 __init__ 이 채우는 속성 선언을 공유한다.
"""

from __future__ import annotations

import inspect

from app.api.services import rag_pipeline
from app.api.services.pipeline import (
    GenerationStageMixin,
    OutputStageMixin,
    PipelineStateBase,
    RerankStageMixin,
    RetrievalStageMixin,
    RoutingStageMixin,
    VerificationStageMixin,
)
from app.api.services.rag_pipeline import RAGPipeline


def test_pipeline_is_composed_from_stage_mixins() -> None:
    bases = RAGPipeline.__mro__
    for mixin in (
        RoutingStageMixin,
        RetrievalStageMixin,
        RerankStageMixin,
        GenerationStageMixin,
        VerificationStageMixin,
        OutputStageMixin,
    ):
        assert mixin in bases
        assert issubclass(mixin, PipelineStateBase)


def test_stage_methods_live_on_their_stage() -> None:
    expected = {
        RoutingStageMixin: ["route_query", "prepare_context"],
        RetrievalStageMixin: ["retrieve_documents", "expand_context_documents"],
        RerankStageMixin: ["rerank_documents"],
        GenerationStageMixin: ["generate_answer"],
        VerificationStageMixin: ["self_rag_verify", "_apply_hallucination_gate"],
        OutputStageMixin: ["format_sources", "build_result"],
    }
    for mixin, names in expected.items():
        for name in names:
            assert name in vars(mixin), f"{name} 은(는) {mixin.__name__} 에 있어야 한다"
    # 오케스트레이션 자체는 RAGPipeline 에 남는다
    assert "execute" in vars(RAGPipeline)
    assert "run_retrieval_phase" in vars(RAGPipeline)


def test_legacy_import_paths_still_work() -> None:
    for name in (
        "RouteDecision",
        "PreparedContext",
        "RetrievalResults",
        "RerankResults",
        "PipelineTracker",
        "HALLUCINATION_GATE_NO_ANSWER_MESSAGE",
        "_extract_fallback_document_preview",
        "_document_metadata",
    ):
        assert hasattr(rag_pipeline, name), name


def test_no_stage_method_was_lost() -> None:
    """분리 전 RAGPipeline 의 메서드(63개)가 전부 MRO 어딘가에 존재해야 한다."""
    methods = [
        n for n, _ in inspect.getmembers(RAGPipeline, predicate=inspect.isfunction)
        if not n.startswith("__")
    ]
    assert len(methods) >= 63
