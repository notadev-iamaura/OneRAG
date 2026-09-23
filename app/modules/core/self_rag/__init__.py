"""
Self-RAG Module - 자가 평가 및 개선 RAG 시스템

Self-RAG (Self-Reflective Retrieval-Augmented Generation) 시스템:
- 복잡도 기반 자동 활성화
- 초기 답변 품질 평가
- 필요 시 자동 재생성

주요 구성 요소:
- SelfRAGOrchestrator: Self-RAG 프로세스 총괄 조율
- SelfRAGResult: 처리 결과 및 메타데이터

사용 예시:
    from app.modules.core.self_rag import SelfRAGOrchestrator

    orchestrator = SelfRAGOrchestrator(
        complexity_calculator=complexity_calc,
        evaluator=quality_eval,
        retrieval_module=retrieval,
        generation_module=generator,
        initial_top_k=5,
        retry_top_k=15,
        enabled=True
    )

    result = await orchestrator.process(
        query="복잡한 질문",
        session_id="session-123"
    )

    print(f"답변: {result.answer}")
    print(f"Self-RAG 사용: {result.used_self_rag}")
    print(f"재생성 여부: {result.regenerated}")
    print(f"초기 품질: {result.initial_quality}")
    print(f"최종 품질: {result.final_quality}")
"""

from .evaluator import EvalStatus, LLMQualityEvaluator, QualityEvaluation, QualityScore
from .orchestrator import SelfRAGOrchestrator, SelfRAGOutcome, SelfRAGResult

__all__ = [
    "SelfRAGOrchestrator",
    "SelfRAGResult",
    "LLMQualityEvaluator",
    "QualityScore",
    "EvalStatus",
    "QualityEvaluation",
    "SelfRAGOutcome",
]
