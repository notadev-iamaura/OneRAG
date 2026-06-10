"""
build_result의 quality_score/refusal_reason 전파 테스트 (Phase 4.4)

목적:
    self_rag_verify가 설정한 quality_score/refusal_reason이 응답 딕셔너리에
    포함돼야 한다. 누락되면 chat_router의 quality 메타데이터 블록이 항상
    None을 받아 도달 불가능한 dead code가 된다.
"""

from __future__ import annotations

from app.api.services.rag_pipeline import RAGPipeline


def _make_pipeline() -> RAGPipeline:
    # build_result는 self.privacy_masker만 사용하므로 무거운 __init__을 우회한다.
    pipe = RAGPipeline.__new__(RAGPipeline)
    pipe.privacy_masker = None  # type: ignore[attr-defined]
    return pipe


def test_build_result_includes_quality_fields() -> None:
    """quality_score/refusal_reason 전달 시 응답 딕셔너리에 포함돼야 한다."""
    pipe = _make_pipeline()
    result = pipe.build_result(
        answer="답변",
        sources=[],
        tokens_used=10,
        topic="t",
        processing_time=0.1,
        search_count=1,
        ranked_count=1,
        model_info={"provider": "google", "model": "x"},
        routing_metadata=None,
        quality_score=0.85,
        refusal_reason="quality_too_low",
    )
    assert result["quality_score"] == 0.85
    assert result["refusal_reason"] == "quality_too_low"


def test_build_result_omits_quality_when_none() -> None:
    """quality 필드가 None이면 응답 딕셔너리에 넣지 않아야 한다 (기존 동작 보존)."""
    pipe = _make_pipeline()
    result = pipe.build_result(
        answer="답변",
        sources=[],
        tokens_used=10,
        topic="t",
        processing_time=0.1,
        search_count=1,
        ranked_count=1,
        model_info={},
        routing_metadata=None,
    )
    assert "quality_score" not in result
    assert "refusal_reason" not in result
