"""
RAG Pipeline 모듈

7개 독립 단계로 분해된 RAG 파이프라인 오케스트레이터.
각 단계는 독립적으로 테스트 및 최적화 가능.

단계:
1. route_query: 쿼리 라우팅 (규칙 기반 + LLM 폴백)
2. prepare_context: 세션 컨텍스트 + 쿼리 확장
3. retrieve_documents: MongoDB Atlas 하이브리드 검색
4. rerank_documents: 리랭킹 (선택적)
5. generate_answer: LLM 답변 생성
6. format_sources: Source 객체 변환
7. build_result: 최종 응답 구성

작성일: 2025-01-27
목적: TASK-H4 구현 - 150줄 블랙박스 함수 → 7개 독립 메서드
"""
from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from ...lib.errors import ErrorCode, PipelineTimeoutError
from ...lib.langfuse_client import observe  # Langfuse 트레이싱
from ...lib.logger import get_logger
from ...lib.metrics import CostTracker, PerformanceMetrics
from ...lib.score_normalizer import RRFScoreNormalizer  # RRF 점수 정규화
from ...lib.types import RAGResultDict
from .blocked_response import DEFAULT_BLOCKED_ANSWER

if TYPE_CHECKING:
    from ...modules.core.agent.orchestrator import AgentOrchestrator
    from ...modules.core.sql_search import SQLSearchResult, SQLSearchService



# 분리 전 rag_pipeline 모듈 경로로 import 하던 이름들을 그대로 제공한다(테스트/외부 코드 호환).
from .pipeline.document_utils import (
    _CALENDAR_YEAR_PATTERN,
    _CONTEXT_EXPANSION_MAX_WINDOW,
    _DOCUMENT_FILENAME_PATTERN,
    _EXACT_IDENTIFIER_PATTERN,
    _LATIN_PHRASE_PATTERN,
    _NAMED_DOCUMENT_HIGH_VALUE_PATTERN,
    _NAMED_DOCUMENT_LIST_PAGE_SIZE,
    _NAMED_DOCUMENT_TOKEN_PATTERN,
    _QUOTED_TEXT_PATTERN,
    _RERANK_METADATA_KEYS,
    DOCUMENT_PREVIEW_UNAVAILABLE_MESSAGE,
    GENERATION_FALLBACK_NO_DOCS_MESSAGE,
    GENERATION_FALLBACK_WITH_DOCS_MESSAGE,
    GENERATION_MODULE_MISSING_MESSAGE,
    GENERATION_TYPE_ERROR_MESSAGE,
    HALLUCINATION_GATE_NO_ANSWER_MESSAGE,
    PROMPT_LEAKAGE_BLOCKED_MESSAGE,
    SELF_RAG_LOW_QUALITY_REJECT_MESSAGE,
    SELF_RAG_LOW_QUALITY_REJECT_TEXT,
    _annotate_rerank_scores,
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
    _ensure_document_metadata,
    _exact_identifier_terms,
    _extract_fallback_document_preview,
    _has_rerank_metadata,
    _is_noop_rerank,
    _is_numeric_score,
    _latin_phrase_terms,
    _named_document_match_terms,
    _normalize_exact_match_text,
    _normalize_named_document_text,
    _quoted_content_hints,
    _requested_document_filenames,
    _resolve_generation_fallback_message,
    _same_score,
    _snapshot_rerank_inputs,
)
from .pipeline.generation_stage import GenerationStageMixin
from .pipeline.models import (
    FormattedSources,
    PipelineTracker,
    PreparedContext,
    RerankResults,
    RetrievalResults,
    RouteDecision,
)
from .pipeline.output_stage import OutputStageMixin
from .pipeline.rerank_stage import RerankStageMixin
from .pipeline.retrieval_stage import RetrievalStageMixin
from .pipeline.routing_stage import RoutingStageMixin
from .pipeline.verification_stage import VerificationStageMixin

# 재노출 목록(분리 전 공개 경로 유지). ruff 가 미사용 import 로 지우지 않도록 __all__ 로 선언한다.
__all__ = [
    "RAGPipeline",
    "RetrievalPhase",
    "FormattedSources",
    "PipelineTracker",
    "PreparedContext",
    "RerankResults",
    "RetrievalResults",
    "RouteDecision",
    "DOCUMENT_PREVIEW_UNAVAILABLE_MESSAGE",
    "GENERATION_FALLBACK_NO_DOCS_MESSAGE",
    "GENERATION_FALLBACK_WITH_DOCS_MESSAGE",
    "GENERATION_MODULE_MISSING_MESSAGE",
    "GENERATION_TYPE_ERROR_MESSAGE",
    "HALLUCINATION_GATE_NO_ANSWER_MESSAGE",
    "PROMPT_LEAKAGE_BLOCKED_MESSAGE",
    "SELF_RAG_LOW_QUALITY_REJECT_MESSAGE",
    "SELF_RAG_LOW_QUALITY_REJECT_TEXT",
    "_CALENDAR_YEAR_PATTERN",
    "_CONTEXT_EXPANSION_MAX_WINDOW",
    "_DOCUMENT_FILENAME_PATTERN",
    "_EXACT_IDENTIFIER_PATTERN",
    "_LATIN_PHRASE_PATTERN",
    "_NAMED_DOCUMENT_HIGH_VALUE_PATTERN",
    "_NAMED_DOCUMENT_LIST_PAGE_SIZE",
    "_NAMED_DOCUMENT_TOKEN_PATTERN",
    "_QUOTED_TEXT_PATTERN",
    "_RERANK_METADATA_KEYS",
    "_annotate_rerank_scores",
    "_chunk_to_search_result",
    "_coerce_bool",
    "_coerce_bounded_int",
    "_coerce_optional_int",
    "_coerce_positive_int",
    "_context_chunk_identity",
    "_context_chunk_index",
    "_context_document_id",
    "_document_content",
    "_document_identity",
    "_document_matches_requested_filename",
    "_document_metadata",
    "_document_score",
    "_document_text_for_exact_signals",
    "_document_value",
    "_ensure_document_metadata",
    "_exact_identifier_terms",
    "_extract_fallback_document_preview",
    "_has_rerank_metadata",
    "_is_noop_rerank",
    "_is_numeric_score",
    "_latin_phrase_terms",
    "_named_document_match_terms",
    "_normalize_exact_match_text",
    "_normalize_named_document_text",
    "_quoted_content_hints",
    "_requested_document_filenames",
    "_resolve_generation_fallback_message",
    "_same_score",
    "_snapshot_rerank_inputs",
]

_StageT = TypeVar("_StageT")

logger = get_logger(__name__)



@dataclass
class RetrievalPhase:
    """검색 국면 결과 묶음(run_retrieval_phase 반환값)."""

    prepared_context: PreparedContext
    retrieval_results: RetrievalResults
    sql_search_result: SQLSearchResult | None
    rerank_results: RerankResults
    context_documents: list[Any]


class RAGPipeline(
    RoutingStageMixin,
    RetrievalStageMixin,
    RerankStageMixin,
    GenerationStageMixin,
    VerificationStageMixin,
    OutputStageMixin,
):
    """
    RAG 파이프라인 오케스트레이터

    8개 독립 단계로 분해된 파이프라인:
    1. route_query: 쿼리 라우팅
    2. prepare_context: 컨텍스트 준비
    3. retrieve_documents: 문서 검색
    4. rerank_documents: 리랭킹
    5. generate_answer: 답변 생성
    6. self_rag_verify: Self-RAG 품질 검증 (선택적)
    7. format_sources: 소스 포맷팅
    8. build_result: 결과 구성

    각 단계는 독립적으로 테스트 및 최적화 가능.
    """

    # 기본값 (YAML 설정이 없을 때만 사용)
    FALLBACK_RETRIEVAL_LIMIT = 8

    FALLBACK_MIN_SCORE = 0.05

    FALLBACK_RERANK_TOP_N = 8

    # 정확 식별자 보강용 candidate pool 확장 상수 (GAP A)
    # exact_identifier.enabled=true일 때만 candidate_limit이 확장되며, 기본 OFF면 no-op.
    RETRIEVAL_CANDIDATE_MAX = 40

    RETRIEVAL_CANDIDATE_MIN_EXTRA = 10

    RETRIEVAL_CANDIDATE_MULTIPLIER = 3

    _DEFAULT_BLOCKED_ANSWER = DEFAULT_BLOCKED_ANSWER

    # 멀티턴 standalone rewrite 게이트용 기본 패턴 (한국어 기본값,
    # yaml의 rag.multiturn_rewrite.followup_*_patterns로 언어별 오버라이드 가능)
    # (1) 후속 질문임을 강하게 시사하는 대명사/지시어/생략 표현
    #     주의: "그리고"/"추가로" 같은 일반 접속사는 자립 질문에도 흔히 등장하므로
    #     여기서 제외하고, 문장 시작 위치에서만 후속 신호로 취급한다.
    _DEFAULT_FOLLOWUP_DEPENDENT_PATTERNS: tuple[str, ...] = (
        "그건", "그게", "그것", "그거", "이건", "이게", "이것", "이거",
        "저건", "저게", "그럼", "그러면", "그때", "거기", "여기",
        "위의", "앞서", "방금", "해당", "그 경우", "이 경우", "그 외",
    )

    # (1-b) 문장 시작 위치에서만 후속 신호로 보는 접속사
    #       (문장 중간의 "A 그리고 B"는 자립 질문이므로 게이트를 통과시키지 않는다)
    _DEFAULT_FOLLOWUP_START_PATTERNS: tuple[str, ...] = (
        "그리고", "추가로", "또", "또한",
    )

    # standalone rewrite 기본 프롬프트 템플릿 (한국어, 출력 언어 보존용)
    # yaml의 rag.multiturn_rewrite.prompt_template로 오버라이드 가능하며,
    # 비한국어 외주는 이 템플릿을 해당 언어로 교체할 수 있다.
    # 플레이스홀더: {session_context}(직전 대화 맥락), {message}(후속 질문)
    _DEFAULT_MULTITURN_REWRITE_PROMPT: str = (
        "당신은 멀티턴 대화의 후속 질문을 검색에 적합한 자립적(standalone) "
        "질문으로 재작성하는 전문가입니다.\n\n"
        "아래 [직전 대화 맥락]을 참고하여, [후속 질문]에서 생략되거나 "
        "대명사/지시어로 표현된 핵심 대상(프로그램명, 제도명, 주체 등)을 "
        "명시적으로 복원해 하나의 완결된 질문으로 다시 쓰세요.\n"
        "- 맥락에 없는 정보를 새로 추가하지 마세요.\n"
        "- 후속 질문의 의도를 바꾸지 마세요.\n"
        "- 설명 없이 재작성된 질문 한 문장만 출력하세요.\n\n"
        "[직전 대화 맥락]\n{session_context}\n\n"
        "[후속 질문]\n{message}\n\n"
        "[재작성된 자립적 질문]"
    )

    # 재작성 결과 정제용: 모델이 흔히 붙이는 라벨 접두어
    _REWRITE_LABEL_PATTERN = re.compile(
        r"^\s*(재작성(된)?\s*(질문|쿼리)?|standalone(\s*query)?|질문|rewritten\s*query)\s*[:：]\s*",
        re.IGNORECASE,
    )

    # 재작성 프롬프트 플레이스홀더 치환용: 두 토큰을 단일 패스로 치환해
    # 치환 값 내부 토큰 재치환을 차단한다 (순차 replace는 앞선 치환 결과를
    # 재스캔하므로, 직전 대화에 리터럴 '{message}'가 있으면 컨텍스트 블록에
    # 새 질문이 주입되는 인젝션 벡터가 된다).
    _REWRITE_PLACEHOLDER_PATTERN = re.compile(r"\{session_context\}|\{message\}")



    def __init__(
        self,
        config: dict[str, Any],
        query_router: Any | None,
        query_expansion: Any | None,
        retrieval_module: Any,
        generation_module: Any,
        session_module: Any,
        self_rag_module: Any | None,
        extract_topic_func: Callable,
        circuit_breaker_factory: Any,
        cost_tracker: CostTracker,
        performance_metrics: PerformanceMetrics,
        sql_search_service: SQLSearchService | None = None,
        agent_orchestrator: AgentOrchestrator | None = None,
        grok_answer_provider: Any | None = None,
        llm_factory: Any | None = None,
    ):
        """
        RAGPipeline 초기화 (의존성 주입)

        Args:
            config: 설정 딕셔너리
            query_router: 쿼리 라우터 (선택적)
            query_expansion: 쿼리 확장 모듈 (선택적)
            retrieval_module: 검색 모듈 (필수)
            generation_module: 생성 모듈 (필수)
            session_module: 세션 모듈 (필수)
            self_rag_module: Self-RAG 모듈 (선택적)
            extract_topic_func: 토픽 추출 함수
            circuit_breaker_factory: Circuit Breaker Factory (필수)
            cost_tracker: 비용 추적기 (필수)
            performance_metrics: 성능 메트릭 (필수)
            sql_search_service: SQL 검색 서비스 (선택적, Phase 3)
            agent_orchestrator: Agent 오케스트레이터 (선택적, Agentic RAG)
            grok_answer_provider: Grok이 검색과 답변을 모두 맡는 provider (선택적)
        """
        self.config = config
        # SQL Source(_format_sql_row) 라벨: 출력 언어 일관성을 위해 외부화.
        # sql_search.multi_query에서 읽어 service.py의 all_category_label과 단일
        # 진실원천을 공유한다. 미설정 시 한국어 기본값(회귀 0).
        _sql_multi_query = config.get("sql_search", {}).get("multi_query", {})
        self._sql_all_category_label: str = (
            _sql_multi_query.get("all_category_label") or "전체"
        )
        self._sql_entity_name_fallback_template: str = (
            _sql_multi_query.get("entity_name_fallback_template") or "결과 {index}"
        )
        self._sql_preview_fallback: str = (
            _sql_multi_query.get("preview_fallback") or "SQL 쿼리 결과"
        )
        self.query_router = query_router
        self.query_expansion = query_expansion
        self.retrieval_module = retrieval_module
        self.generation_module = generation_module
        self.session_module = session_module
        self.self_rag_module = self_rag_module
        self.extract_topic_func = extract_topic_func
        self.circuit_breaker_factory = circuit_breaker_factory
        self.cost_tracker = cost_tracker
        self.performance_metrics = performance_metrics
        self.sql_search_service = sql_search_service  # SQL 검색 서비스 (Phase 3)
        self.agent_orchestrator = agent_orchestrator  # Agent 오케스트레이터 (Agentic RAG)
        self.grok_answer_provider = grok_answer_provider
        self.llm_factory = llm_factory  # 멀티턴 standalone query rewrite용 LLM Factory

        # YAML 설정에서 retrieval 파라미터 로드
        rag_config = config.get("rag", {})

        # 멀티턴 standalone query rewrite 설정 (기본 OFF)
        # 후속 질문이 대명사/생략/축약으로 자립적이지 않으면 직전 대화 맥락을
        # 반영한 자립적(standalone) 질문으로 재작성해 검색에 투입한다.
        # 게이트 패턴은 언어별로 다르므로 yaml에서 오버라이드 가능하게 일반화한다.
        rewrite_config = rag_config.get("multiturn_rewrite", {})
        self.multiturn_rewrite_enabled = bool(rewrite_config.get("enabled", False))
        self.multiturn_rewrite_provider = rewrite_config.get("provider", "google")
        configured_dependent = rewrite_config.get("followup_dependent_patterns")
        self.multiturn_followup_dependent_patterns: tuple[str, ...] = (
            tuple(str(p) for p in configured_dependent)
            if isinstance(configured_dependent, list) and configured_dependent
            else self._DEFAULT_FOLLOWUP_DEPENDENT_PATTERNS
        )
        configured_start = rewrite_config.get("followup_start_patterns")
        self.multiturn_followup_start_patterns: tuple[str, ...] = (
            tuple(str(p) for p in configured_start)
            if isinstance(configured_start, list) and configured_start
            else self._DEFAULT_FOLLOWUP_START_PATTERNS
        )
        try:
            self.multiturn_short_question_max_words = int(
                rewrite_config.get("short_question_max_words", 5)
            )
        except (TypeError, ValueError):
            self.multiturn_short_question_max_words = 5
        # 재작성 프롬프트 템플릿 (없으면 한국어 기본 템플릿 사용 → 출력 언어 보존)
        configured_prompt = rewrite_config.get("prompt_template")
        self.multiturn_rewrite_prompt_template: str = (
            configured_prompt
            if isinstance(configured_prompt, str) and configured_prompt.strip()
            else self._DEFAULT_MULTITURN_REWRITE_PROMPT
        )

        # 정확 식별자(exact-identifier) 검색 보강 설정 (GAP A, 기본 OFF)
        # dense·BM25가 공히 놓치는 고유 식별자(모델코드/에러코드 등) 리콜을 보완한다.
        # OFF면 쿼리 보강·candidate 확장·rescue·rerank 안정화가 모두 no-op이다.
        exact_config = rag_config.get("exact_identifier", {})
        self.exact_identifier_enabled = bool(
            exact_config.get("enabled", False)
            if isinstance(exact_config, dict)
            else False
        )

        # 환각 방지 게이트 설정 (GAP C, 기본 OFF)
        # 질문에 명시된 연도가 검색 문서 연도집합과 완전 disjoint이면 최종답변을
        # '확인 불가'로 교체한다. OFF면 generation_result를 그대로 반환(no-op).
        hallucination_config = rag_config.get("hallucination_gate", {})
        self.hallucination_gate_enabled = bool(
            hallucination_config.get("enabled", False)
            if isinstance(hallucination_config, dict)
            else False
        )
        self.hallucination_gate_require_period_match = bool(
            hallucination_config.get("require_period_match", True)
            if isinstance(hallucination_config, dict)
            else True
        )
        # 보류 메시지 외부화: config 우선, 미설정/공백이면 코드 내장 한국어 기본값(회귀 0).
        configured_gate_message = (
            hallucination_config.get("no_answer_message")
            if isinstance(hallucination_config, dict)
            else None
        )
        self.hallucination_gate_no_answer_message: str = (
            configured_gate_message
            if isinstance(configured_gate_message, str) and configured_gate_message.strip()
            else HALLUCINATION_GATE_NO_ANSWER_MESSAGE
        )

        # 생성 모듈 부재 시 답변 폴백 메시지 외부화 (config 우선, 미설정 시 코드 기본).
        generation_fallback_config = rag_config.get("generation_fallback", {})
        if not isinstance(generation_fallback_config, dict):
            generation_fallback_config = {}
        configured_missing_message = generation_fallback_config.get(
            "module_missing_message"
        )
        self.generation_module_missing_message: str = (
            configured_missing_message
            if isinstance(configured_missing_message, str)
            and configured_missing_message.strip()
            else GENERATION_MODULE_MISSING_MESSAGE
        )

        # LLM 서킷브레이커 폴백 답변 3종 외부화 (config 우선, 미설정 시 코드 기본 → 회귀 0).
        # _resolve_generation_fallback_message로 null/공백 처리를 일원화한다.
        self.generation_fallback_with_docs_message: str = (
            _resolve_generation_fallback_message(
                generation_fallback_config.get("with_docs_message"),
                GENERATION_FALLBACK_WITH_DOCS_MESSAGE,
            )
        )
        self.generation_fallback_no_docs_message: str = (
            _resolve_generation_fallback_message(
                generation_fallback_config.get("no_docs_message"),
                GENERATION_FALLBACK_NO_DOCS_MESSAGE,
            )
        )
        self.document_preview_unavailable_message: str = (
            _resolve_generation_fallback_message(
                generation_fallback_config.get("document_preview_unavailable"),
                DOCUMENT_PREVIEW_UNAVAILABLE_MESSAGE,
            )
        )
        # 프롬프트 누출 차단 메시지(통짜·Self-RAG 공용, 중복 단일화)와 타입 가드 실패
        # 메시지도 동일하게 generation_fallback로 외부화한다(미설정 시 코드 기본 → 회귀 0).
        self.prompt_leakage_blocked_message: str = (
            _resolve_generation_fallback_message(
                generation_fallback_config.get("prompt_leakage_blocked_message"),
                PROMPT_LEAKAGE_BLOCKED_MESSAGE,
            )
        )
        self.generation_type_error_message: str = (
            _resolve_generation_fallback_message(
                generation_fallback_config.get("type_error_message"),
                GENERATION_TYPE_ERROR_MESSAGE,
            )
        )

        # Self-RAG 저품질 거부 메시지 외부화 (self_rag.yaml self_rag 섹션).
        # min_quality_to_answer와 동일 섹션(self_rag_config)에서 읽어 응집도를 맞춘다.
        # answer(상세)/text(축약) 2종 모두 미설정/공백이면 코드 내장 한국어 기본값 → 회귀 0.
        self_rag_section = self.config.get("self_rag", {})
        if not isinstance(self_rag_section, dict):
            self_rag_section = {}
        self.self_rag_low_quality_reject_message: str = (
            _resolve_generation_fallback_message(
                self_rag_section.get("low_quality_reject_message"),
                SELF_RAG_LOW_QUALITY_REJECT_MESSAGE,
            )
        )
        self.self_rag_low_quality_reject_text: str = (
            _resolve_generation_fallback_message(
                self_rag_section.get("low_quality_reject_text"),
                SELF_RAG_LOW_QUALITY_REJECT_TEXT,
            )
        )

        # 멀티턴 anchor soft boost 설정 (GAP B, 기본 OFF, 보수적)
        # 직전 대화에서 인용된 문서(anchor)를 후속 질문 리랭킹 후처리에서 hard-filter
        # 없이 약하게(boost_multiplier) 우대한다. 강한 우대/하드 필터는 옛 문서 고착
        # (staleness) 위험이 커서 금지한다. 자립(주제전환) 질문이면 anchor를 폐기한다.
        anchor_config = rag_config.get("multiturn_anchor", {})
        if not isinstance(anchor_config, dict):
            anchor_config = {}
        self.multiturn_anchor_enabled = bool(anchor_config.get("enabled", False))
        # 기본 배수 1.05(=+5%). 비정상/범위 밖 값은 1.05로 보정(상한 1.10).
        raw_anchor_multiplier = anchor_config.get("boost_multiplier", 1.05)
        try:
            anchor_multiplier = float(raw_anchor_multiplier)
        except (TypeError, ValueError):
            anchor_multiplier = 1.05
        self.multiturn_anchor_boost_multiplier = (
            anchor_multiplier if 1.0 < anchor_multiplier <= 1.10 else 1.05
        )

        retrieval_config = config.get("retrieval", {})

        self.retrieval_limit = rag_config.get(
            "top_k", retrieval_config.get("top_k", self.FALLBACK_RETRIEVAL_LIMIT)
        )
        self.min_score = retrieval_config.get("min_score", self.FALLBACK_MIN_SCORE)
        self.rerank_top_n = rag_config.get("rerank_top_k", self.FALLBACK_RERANK_TOP_N)

        # 파이프라인 타임아웃 예산(SLA budget) 로드 (opt-in)
        # 각 stage에 개별 deadline을, 전체에 총 budget을 부여해 무한 대기를 막는다.
        # enabled=false면 모든 래핑을 건너뛰어 기존(무제한) 동작을 유지한다.
        # 값이 비정상(0 이하/숫자 아님)이면 해당 stage는 무제한으로 폴백한다.
        timeout_config = rag_config.get("pipeline_timeout", {})
        self.pipeline_timeout_enabled = bool(timeout_config.get("enabled", False))
        self.pipeline_total_budget_seconds = self._coerce_positive_timeout(
            timeout_config.get("total_budget_seconds")
        )
        raw_stage_budgets = timeout_config.get("stages", {}) or {}
        # stage 이름 → deadline(초). None이면 해당 stage 무제한.
        self.pipeline_stage_budgets: dict[str, float | None] = {
            str(stage): self._coerce_positive_timeout(value)
            for stage, value in raw_stage_budgets.items()
        }
        self.pipeline_stream_first_chunk_seconds = self._coerce_positive_timeout(
            timeout_config.get("stream_first_chunk_seconds")
        )
        # 스트리밍 전용 총 예산(초). 스트리밍(SSE/WS)은 프론트 HTTP 타임아웃에
        # 묶이지 않는 장수명 연결이므로, 통짜(total_budget_seconds)보다 넉넉하게
        # 둘 수 있다. 미설정이면 무제한(stage deadline만 적용).
        self.pipeline_stream_total_budget_seconds = self._coerce_positive_timeout(
            timeout_config.get("stream_total_budget_seconds")
        )

        # RRF 점수 정규화 (0~1 범위 변환)
        score_norm_config = rag_config.get("score_normalization", {})
        self.score_normalizer = RRFScoreNormalizer.from_config(score_norm_config)

        # 개인정보 마스킹 (파일명, 답변 텍스트)
        # privacy.yaml 화이트리스트 로드 (오탐 방지: 이모님, 헬퍼님, 담당 등)
        # privacy.enabled: false → 마스킹 완전 비활성화
        privacy_config = config.get("privacy", {})
        privacy_enabled = privacy_config.get("enabled", True)

        if privacy_enabled:
            from ...modules.core.privacy.masker import PrivacyMasker

            whitelist = privacy_config.get("whitelist", [])
            masking_config = privacy_config.get("masking", {})
            char_config = privacy_config.get("characters", {})

            self.privacy_masker = PrivacyMasker(
                mask_phone=masking_config.get("phone", True),
                mask_name=masking_config.get("name", True),
                mask_email=masking_config.get("email", False),
                phone_mask_char=char_config.get("phone", "*"),
                name_mask_char=char_config.get("name", "*"),
                whitelist=whitelist,  # 공용 화이트리스트 (privacy.yaml)
            )
        else:
            self.privacy_masker = None  # PII 마스킹 비활성화
            logger.info(
                "PII 마스킹 비활성화",
                extra={"config_key": "privacy.enabled", "value": False}
            )

        logger.info(
            "RAG 파라미터 설정",
            extra={
                "top_k": self.retrieval_limit,
                "rerank_top_k": self.rerank_top_n,
                "min_score": self.min_score
            }
        )

        from ..schemas.chat_schemas import Source

        self.Source = Source

        # 규칙 기반 라우터를 1회 생성해 재사용한다.
        # 기존에는 route_query()가 매 chat 요청마다 RuleBasedRouter(enabled=True)를
        # 새로 만들어 config.yaml/routing_rules_v2.yaml을 디스크에서 반복 읽었다.
        # DynamicRuleManager(auto_reload=True)가 5분마다 규칙을 자동 리로드하므로
        # 인스턴스를 공유해도 규칙 변경은 그대로 반영된다(동작 보존).
        # 생성 실패 시 None으로 두고 route_query()에서 lazy 생성으로 폴백한다.
        # (생성 로직 자체는 _create_rule_based_router 헬퍼로 단일화)
        self.rule_based_router: Any | None = None
        try:
            self.rule_based_router = self._create_rule_based_router()
        except Exception as e:
            logger.warning(
                "RuleBasedRouter 초기화 실패 (route_query에서 lazy 생성으로 폴백)",
                extra={"error": str(e)},
                exc_info=True,
            )

        logger.info(
            "RAGPipeline 초기화 완료",
            extra={
                "sql_search": "활성화" if sql_search_service else "비활성화",
                "agent": "활성화" if agent_orchestrator else "비활성화",
                "score_normalization": "활성화" if score_norm_config.get('enabled', True) else "비활성화"
            }
        )


    @staticmethod
    def _coerce_positive_timeout(value: Any) -> float | None:
        """타임아웃 설정값을 양수 float로 변환한다.

        0 이하/숫자 아님/None이면 None(=무제한)을 반환해 해당 stage·budget의
        wait_for 래핑을 건너뛰게 한다. 잘못된 설정으로 정상 요청이 끊기는
        것을 막기 위한 안전 폴백이다.

        Args:
            value: YAML에서 읽은 타임아웃 값(초)

        Returns:
            양수 float 또는 None(무제한)
        """
        if value is None:
            return None
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return None
        return seconds if seconds > 0 else None


    async def _run_stage_with_timeout(
        self,
        stage_name: str,
        coro: Awaitable[_StageT],
        *,
        remaining_budget: float | None = None,
    ) -> _StageT:
        """단일 stage 코루틴을 deadline으로 감싸 실행한다.

        - pipeline_timeout.enabled=false거나 stage 예산이 없으면 그대로 await
          한다(기존 동작 유지).
        - stage 예산과 남은 총 budget 중 "더 작은 값"을 실제 deadline으로 쓴다.
          이렇게 하면 stage 자체는 여유가 있어도 총 budget이 임박하면 즉시
          PIPE-002(총 budget 초과)로 끊긴다.
        - deadline 초과 시 무한 대기 대신 PipelineTimeoutError를 던져 "어느
          단계에서 몇 초를 초과했는지"를 명확히 전달한다.

        Args:
            stage_name: stage 이름(에러 메시지·로그용)
            coro: 실행할 stage 코루틴
            remaining_budget: 총 budget에서 남은 시간(초). None이면 미적용.

        Returns:
            stage 코루틴의 반환값

        Raises:
            PipelineTimeoutError: stage deadline(PIPE-001) 또는 총 budget(PIPE-002) 초과
        """
        if not self.pipeline_timeout_enabled:
            return await coro

        stage_budget = self.pipeline_stage_budgets.get(stage_name)

        # 총 budget이 임박하면(남은 시간이 stage 예산보다 작으면) 그 값으로 끊는다.
        effective_timeout = stage_budget
        budget_is_limiting = False
        if remaining_budget is not None:
            if effective_timeout is None or remaining_budget < effective_timeout:
                effective_timeout = remaining_budget
                budget_is_limiting = True

        if effective_timeout is None:
            # stage·총 budget 모두 무제한 → 기존 동작
            return await coro

        try:
            return await asyncio.wait_for(coro, timeout=effective_timeout)
        except TimeoutError as exc:
            if budget_is_limiting:
                logger.warning(
                    "파이프라인 총 budget 초과",
                    extra={
                        "stage": stage_name,
                        "total_budget_seconds": self.pipeline_total_budget_seconds,
                    },
                )
                raise PipelineTimeoutError(
                    ErrorCode.PIPELINE_TOTAL_TIMEOUT,
                    stage=stage_name,
                    timeout=self.pipeline_total_budget_seconds,
                ) from exc
            logger.warning(
                "파이프라인 stage deadline 초과",
                extra={"stage": stage_name, "timeout_seconds": effective_timeout},
            )
            raise PipelineTimeoutError(
                ErrorCode.PIPELINE_STAGE_TIMEOUT,
                stage=stage_name,
                timeout=effective_timeout,
            ) from exc


    def _remaining_total_budget(self, start_time: float) -> float | None:
        """총 budget에서 남은 시간(초)을 계산한다.

        Args:
            start_time: 파이프라인 시작 시각(time.time())

        Returns:
            남은 budget(초). budget 미설정/비활성화면 None.
            이미 초과했으면 0.0(다음 stage가 즉시 PIPE-002로 끊김).
        """
        if not self.pipeline_timeout_enabled or self.pipeline_total_budget_seconds is None:
            return None
        remaining = self.pipeline_total_budget_seconds - (time.time() - start_time)
        return remaining if remaining > 0 else 0.0


    def _remaining_stream_budget(self, start_time: float) -> float | None:
        """스트리밍 총 예산에서 남은 시간(초)을 계산한다.

        스트리밍 경로는 프론트 HTTP 타임아웃에 묶이지 않는 장수명 연결이므로
        통짜 총 budget과 별도의 넉넉한 예산(stream_total_budget_seconds)을 쓴다.

        Args:
            start_time: 스트리밍 시작 시각(time.time())

        Returns:
            남은 예산(초). 미설정/비활성화면 None(무제한, stage deadline만 적용).
            이미 초과했으면 0.0.
        """
        if (
            not self.pipeline_timeout_enabled
            or self.pipeline_stream_total_budget_seconds is None
        ):
            return None
        remaining = self.pipeline_stream_total_budget_seconds - (time.time() - start_time)
        return remaining if remaining > 0 else 0.0


    async def run_retrieval_phase(
        self,
        message: str,
        session_id: str,
        options: dict[str, Any],
        *,
        start_time: float,
        tracker: PipelineTracker | None = None,
        enable_debug_trace: bool = False,
        debug_trace_data: dict[str, Any] | None = None,
        budget: Callable[[], float | None] | None = None,
    ) -> RetrievalPhase:
        """검색 국면(2~4단계 + 컨텍스트 확장)을 한 번에 실행한다.

        execute()(비스트리밍)와 ChatService.stream_rag_pipeline()(스트리밍)이 같은 코드를
        공유하기 위한 진입점이다. 예전에는 스트리밍 경로가 retrieval_module.search를 직접
        호출해 세션 컨텍스트 반영, 멀티턴 재작성, 쿼리 확장, 정확 식별자/문서명 구출,
        리랭크 융합·안정화, 앵커 부스트가 전부 빠져 있었다.

        Args:
            message: 사용자 질문
            session_id: 세션 ID
            options: 요청 옵션
            start_time: 요청 시작 시각(타임아웃 예산 계산용)
            tracker: 단계 시간 기록기(None이면 내부 임시 트래커 사용)
            enable_debug_trace: 디버그 트레이스 수집 여부
            debug_trace_data: 디버그 트레이스 누적 딕셔너리
            budget: 단계 타임아웃 예산 계산 함수(None이면 전체 예산 기준)

        Returns:
            RetrievalPhase: 준비된 컨텍스트, 검색/SQL/리랭크 결과, 생성에 넘길 최종 문서 목록
        """
        tracker = tracker or PipelineTracker()
        debug_trace_data = debug_trace_data if debug_trace_data is not None else {}
        if budget is None:
            def budget() -> float | None:
                return self._remaining_total_budget(start_time)

        tracker.start_stage("prepare_context")
        prepared_context = await self._run_stage_with_timeout(
            "prepare_context",
            self.prepare_context(message, session_id),
            remaining_budget=budget(),
        )
        tracker.end_stage("prepare_context")

        if enable_debug_trace:
            debug_trace_data["query_transformation"] = {
                "original": message,
                "expanded": prepared_context.expanded_query if prepared_context.expanded_query != message else None,
                "final_query": prepared_context.expanded_query,
            }

        tracker.start_stage("retrieve_documents")
        retrieval_results, sql_search_result = await self._run_stage_with_timeout(
            "retrieve_documents",
            self._execute_parallel_search(message, prepared_context, options),
            remaining_budget=budget(),
        )
        tracker.end_stage("retrieve_documents")

        self._track_debug_documents(enable_debug_trace, debug_trace_data, retrieval_results.documents)
        self._update_retrieval_metrics(tracker, prepared_context, sql_search_result)

        tracker.start_stage("rerank_documents")
        rerank_results = await self._run_stage_with_timeout(
            "rerank_documents",
            self.rerank_documents(
                prepared_context.expanded_query, retrieval_results.documents, options
            ),
            remaining_budget=budget(),
        )
        tracker.end_stage("rerank_documents")

        # 리랭크 fusion guardrail(#33): 리랭커가 실제로 수행됐을 때만 적용한다.
        # 리랭커가 lexical/hybrid 상위 신호를 죽이는 것을 막아 recall@5/MRR을 보존한다.
        # 기본 비활성화(opt-in)이므로 reranking.fusion.enabled가 꺼져 있으면 no-op이다.
        if rerank_results.reranked:
            fused_documents = self._fuse_reranked_results_with_original_signals(
                rerank_results.documents,
                self.config.get("reranking", {}),
                options,
            )
            rerank_results = RerankResults(
                documents=fused_documents,
                count=len(fused_documents),
                reranked=True,
            )

        # 정확 식별자 rerank 안정화(GAP A, 기본 OFF): 리랭커가 정확 식별자 문서를
        # 하위로 밀어버린 경우를 NFKC 정규화 정확매칭 기준으로 상위 보정한다.
        # exact_identifier.enabled=false면 no-op. 리랭킹 미수행 시에도 검색 단계의
        # 정확매칭을 보존하기 위해 항상 적용한다(2차 신호/임계 게이트로 내부 no-op 보호).
        stabilized_documents = self._stabilize_reranked_results_with_exact_signals(
            prepared_context.expanded_query,
            rerank_results.documents,
        )
        if stabilized_documents is not rerank_results.documents:
            rerank_results = RerankResults(
                documents=stabilized_documents,
                count=len(stabilized_documents),
                reranked=rerank_results.reranked,
            )

        # 멀티턴 anchor soft boost(GAP B, 기본 OFF): 직전 인용 문서를 약하게 우대한다.
        # anchor_sources가 있고 같은 주제(후속)일 때만 의미가 있으며, 없으면 no-op.
        # hard filter가 아니므로 고착 위험을 최소화한다(stabilize 이후 최종 후처리).
        if prepared_context.anchor_sources:
            boosted_documents = self._apply_anchor_soft_boost(
                prepared_context.anchor_sources,
                rerank_results.documents,
            )
            if boosted_documents is not rerank_results.documents:
                rerank_results = RerankResults(
                    documents=boosted_documents,
                    count=len(boosted_documents),
                    reranked=rerank_results.reranked,
                )

        if enable_debug_trace and rerank_results.reranked:
            for i, doc in enumerate(rerank_results.documents):
                if i < len(debug_trace_data["retrieved_documents"]):
                    rerank_score = doc.metadata.get("rerank_score", 0.0) if hasattr(doc, "metadata") else 0.0
                    debug_trace_data["retrieved_documents"][i]["rerank_score"] = rerank_score

        tracker.start_stage("expand_context")
        # 명시 문서명 기반 보강(GAP #1, 기본 OFF): 질문에 파일명/인용구로 지목된 문서를
        # 검색이 놓쳤을 때 그 문서 청크를 결과 앞에 prepend한다. 인접 청크 확장과는
        # 별개 경로이며, 보강된 결과를 인접 청크 확장의 입력으로 넘겨 일관 처리한다.
        base_documents = await self.prepend_named_document_chunks(
            message, rerank_results.documents, options
        )
        context_documents = await self.expand_context_documents(base_documents, options)
        tracker.end_stage("expand_context")

        return RetrievalPhase(
            prepared_context=prepared_context,
            retrieval_results=retrieval_results,
            sql_search_result=sql_search_result,
            rerank_results=rerank_results,
            context_documents=context_documents,
        )

    @observe(name="RAG Pipeline", capture_input=False, capture_output=False)
    async def execute(
        self, message: str, session_id: str, options: dict[str, Any] | None = None
    ) -> RAGResultDict:
        """
        전체 RAG 파이프라인 실행 (7단계 오케스트레이션)

        Args:
            message: 사용자 쿼리
            session_id: 세션 ID
            options: 추가 옵션 (limit, min_score, top_n, enable_debug_trace 등)

        Returns:
            표준 응답 딕셔너리

        Raises:
            RoutingError: 라우팅 실패 시
            RetrievalError: 검색 실패 시
            GenerationError: 답변 생성 실패 시
        """
        start_time = time.time()
        options = options or {}
        logger.info("RAG Pipeline 시작", extra={"query": message[:50]})

        enable_debug_trace = options.get("enable_debug_trace", False)
        debug_trace_data: dict[str, Any] = {} if enable_debug_trace else {}

        tracker = PipelineTracker()
        tracker.start_pipeline()
        tracker.start_stage("route_query")
        route_decision = await self._run_stage_with_timeout(
            "route_query",
            self.route_query(message, session_id, start_time),
            remaining_budget=self._remaining_total_budget(start_time),
        )
        tracker.end_stage("route_query")

        if not route_decision.should_continue:
            logger.info("라우팅 결과: 즉시 응답 반환 (RAG 파이프라인 중단)")
            if route_decision.immediate_response is None:
                logger.error("immediate_response가 None입니다. 완전한 기본 응답 반환")
                return self._create_fallback_response(message, start_time, route_decision.metadata)
            return route_decision.immediate_response

        use_agent = options.get("use_agent", False)
        if use_agent and self.agent_orchestrator:
            logger.info("Agent 모드 활성화", extra={"orchestrator": "AgentOrchestrator"})
            return await self._execute_agent_mode(message, session_id, start_time)

        if enable_debug_trace:
            debug_trace_data["original_query"] = message

        # 라우팅 결과(data_source)를 검색 옵션에 주입한다(GAP G).
        # data_source는 질문 텍스트 기반으로 매 요청 재판단되며, filter_mappings가
        # 비어있으면 _build_retrieval_filters에서 no-op으로 처리된다(회귀 0).
        data_source = route_decision.metadata.get("data_source")
        if data_source is not None:
            options["data_source"] = data_source

        rag_mode = self._resolve_rag_mode(options)
        route_decision.metadata["rag_mode"] = rag_mode
        if rag_mode == "grok_answer":
            logger.info("Grok answer mode 실행")
            return await self._execute_grok_answer_mode(
                message=message,
                start_time=start_time,
                options=options,
                routing_metadata=route_decision.metadata,
            )

        phase = await self.run_retrieval_phase(
            message,
            session_id,
            options,
            start_time=start_time,
            tracker=tracker,
            enable_debug_trace=enable_debug_trace,
            debug_trace_data=debug_trace_data,
        )
        prepared_context = phase.prepared_context
        retrieval_results = phase.retrieval_results
        sql_search_result = phase.sql_search_result
        rerank_results = phase.rerank_results
        context_documents = phase.context_documents

        tracker.start_stage("generate_answer")
        generation_options = {**options}
        # 컨텍스트 확장/명시 문서 보강으로 문서가 늘어났을 때만 프롬프트 한도를 상향(20)해
        # 실제 검색 히트가 이웃/보강 청크에 밀려 프롬프트에서 빠지지 않게 한다(#3).
        if len(context_documents) > len(rerank_results.documents):
            generation_options.setdefault("max_context_documents", 20)
        if sql_search_result and sql_search_result.used:
            generation_options["sql_context"] = sql_search_result.formatted_context
            logger.debug(
                "SQL 컨텍스트 전달",
                extra={"context_length": len(sql_search_result.formatted_context)}
            )
        generation_result = await self._run_stage_with_timeout(
            "generate_answer",
            self.generate_answer(
                message, context_documents, prepared_context.session_context, generation_options
            ),
            remaining_budget=self._remaining_total_budget(start_time),
        )
        tracker.end_stage("generate_answer")

        tracker.start_stage("self_rag_verify")
        options_with_debug = {**options}
        if enable_debug_trace:
            options_with_debug["_debug_trace_data"] = debug_trace_data
        generation_result = await self._run_stage_with_timeout(
            "self_rag_verify",
            self.self_rag_verify(
                message, session_id, generation_result, context_documents, options_with_debug
            ),
            remaining_budget=self._remaining_total_budget(start_time),
        )
        source_documents = getattr(generation_result, "source_documents", None)
        evidence_documents = (
            source_documents if isinstance(source_documents, list) else context_documents
        )
        # 환각 방지 게이트(GAP C, 기본 OFF): 질문 기간과 문서 기간이 완전 불일치하면
        # 최종 답변을 '확인 불가'로 교체한다. self_rag_verify 이후 최종 답변 기준 1회.
        generation_result = self._apply_hallucination_gate(
            message, generation_result, evidence_documents, options
        )
        tracker.end_stage("self_rag_verify")

        tracker.start_stage("format_sources")
        formatted_sources = self.format_sources(evidence_documents, sql_search_result)
        tracker.end_stage("format_sources")

        tracker.start_stage("build_result")
        debug_trace = self._create_debug_trace(enable_debug_trace, debug_trace_data, message)
        result = self.build_result(
            answer=generation_result.answer,
            sources=formatted_sources.sources,
            tokens_used=generation_result.tokens_used,
            topic=self.extract_topic_func(message),
            processing_time=time.time() - start_time,
            search_count=retrieval_results.count,
            # 인접 청크 확장 이웃 청크와 명시 문서 digest(_generation_only)는 실제 히트가
            # 아니므로 카운트에서 제외(#4, GAP #1)
            ranked_count=sum(
                1
                for doc in evidence_documents
                if not _document_metadata(doc).get("context_expanded")
                and not _document_metadata(doc).get("_generation_only")
            ),
            model_info=generation_result.model_info,
            routing_metadata=route_decision.metadata,
            debug_trace=debug_trace,
            quality_score=getattr(generation_result, "quality_score", None),
            refusal_reason=getattr(generation_result, "refusal_reason", None),
        )
        tracker.end_stage("build_result")
        tracker.end_pipeline()
        performance_metrics = tracker.get_metrics()
        tracker.log_summary()
        result["performance_metrics"] = performance_metrics
        logger.info(
            "RAG Pipeline 완료",
            extra={"processing_time": result['processing_time']}
        )
        return result

