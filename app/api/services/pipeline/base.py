"""단계 믹스인이 공유하는 RAGPipeline 인스턴스 속성 선언.
RAGPipeline.__init__ 이 실제 값을 채우고, 각 *StageMixin 은 이 선언만 보고 타입 검사를 통과한다.
믹스인끼리 서로의 메서드를 호출하므로(예: 검색 단계가 _run_stage_with_timeout 사용) 타입 검사
시점에만 __getattr__ 로 Any 를 돌려준다. 런타임에는 존재하지 않아 실제 메서드가 그대로 쓰인다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any


class PipelineStateBase:
    """RAGPipeline 이 __init__ 에서 설정하는 속성들의 타입 선언(값은 갖지 않는다)."""

    _sql_all_category_label: str
    _sql_entity_name_fallback_template: str
    _sql_preview_fallback: str
    agent_orchestrator: Any
    circuit_breaker_factory: Any
    config: Any
    cost_tracker: Any
    document_preview_unavailable_message: str
    exact_identifier_enabled: Any
    extract_topic_func: Any
    generation_fallback_no_docs_message: str
    generation_fallback_with_docs_message: str
    generation_module: Any
    generation_module_missing_message: str
    generation_type_error_message: str
    grok_answer_provider: Any
    hallucination_gate_enabled: Any
    hallucination_gate_no_answer_message: str
    hallucination_gate_require_period_match: Any
    llm_factory: Any
    min_score: Any
    multiturn_anchor_boost_multiplier: Any
    multiturn_anchor_enabled: Any
    multiturn_followup_dependent_patterns: tuple[str, ...]
    multiturn_followup_start_patterns: tuple[str, ...]
    multiturn_rewrite_enabled: Any
    multiturn_rewrite_prompt_template: str
    multiturn_rewrite_provider: Any
    multiturn_short_question_max_words: Any
    performance_metrics: Any
    pipeline_stage_budgets: dict[str, float | None]
    pipeline_stream_first_chunk_seconds: Any
    pipeline_stream_total_budget_seconds: Any
    pipeline_timeout_enabled: Any
    pipeline_total_budget_seconds: Any
    privacy_masker: Any
    prompt_leakage_blocked_message: str
    query_expansion: Any
    query_router: Any
    rerank_top_n: Any
    retrieval_limit: Any
    retrieval_module: Any
    rule_based_router: Any | None
    score_normalizer: Any
    self_rag_low_quality_reject_message: str
    self_rag_low_quality_reject_text: str
    self_rag_module: Any
    session_module: Any
    sql_search_service: Any

    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any:  # pragma: no cover - 타입 검사 전용
            ...
