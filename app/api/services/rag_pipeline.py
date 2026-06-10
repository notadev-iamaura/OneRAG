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
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar, cast

from ...lib.circuit_breaker import CircuitBreakerOpenError
from ...lib.errors import ErrorCode, GenerationError, PipelineTimeoutError, RetrievalError
from ...lib.langfuse_client import langfuse_context, observe  # Langfuse 트레이싱
from ...lib.logger import get_logger
from ...lib.metrics import CostTracker, PerformanceMetrics
from ...lib.prompt_sanitizer import contains_output_leakage, validate_document
from ...lib.score_normalizer import RRFScoreNormalizer  # RRF 점수 정규화
from ...lib.types import RAGResultDict
from ...modules.core.retrieval.interfaces import IMultiQueryRetriever, SearchResult
from .source_contract import normalize_citation_source_payload, normalize_source_payload

if TYPE_CHECKING:
    from ...modules.core.agent.orchestrator import AgentOrchestrator
    from ...modules.core.generation.generator import GenerationResult
    from ...modules.core.sql_search import SQLSearchResult, SQLSearchService
    from ..schemas.debug import DebugTrace

logger = get_logger(__name__)

# stage 타임아웃 헬퍼(_run_stage_with_timeout)의 반환 타입을 보존하기 위한 TypeVar
_StageT = TypeVar("_StageT")

# Kept as a patchable module attribute for existing tests while avoiding the
# heavy routing module import until route_query actually runs.
RuleBasedRouter: Any | None = None


def _extract_fallback_document_preview(document: Any, max_chars: int = 300) -> str:
    """Return user-safe document text for LLM outage fallback responses."""
    for attr in ("page_content", "content", "text"):
        value = getattr(document, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()[:max_chars]

    if isinstance(document, dict):
        for key in ("page_content", "content", "text"):
            value = document.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:max_chars]

    return "문서 내용 요약을 표시할 수 없습니다"


_RERANK_METADATA_KEYS = {"rerank_score", "rerank_method", "original_score"}
_CONTEXT_EXPANSION_MAX_WINDOW = 3


def _is_numeric_score(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _document_metadata(document: Any) -> dict[str, Any]:
    metadata = (
        document.get("metadata")
        if isinstance(document, dict)
        else getattr(document, "metadata", None)
    )
    return metadata if isinstance(metadata, dict) else {}


def _ensure_document_metadata(document: Any) -> dict[str, Any]:
    if isinstance(document, dict):
        metadata = document.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            document["metadata"] = metadata
        return metadata

    metadata = getattr(document, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
        try:
            document.metadata = metadata
        except Exception:
            return {}
    return metadata


def _document_identity(document: Any) -> Any:
    if isinstance(document, dict):
        metadata = _document_metadata(document)
        return (
            document.get("id")
            or document.get("document_id")
            or metadata.get("document_id")
            or metadata.get("source_id")
            or metadata.get("source_file")
            or id(document)
        )

    metadata = _document_metadata(document)
    return (
        getattr(document, "id", None)
        or getattr(document, "document_id", None)
        or metadata.get("document_id")
        or metadata.get("source_id")
        or metadata.get("source_file")
        or id(document)
    )


def _document_score(document: Any) -> float | None:
    score = document.get("score") if isinstance(document, dict) else getattr(document, "score", None)
    if _is_numeric_score(score):
        return float(score)

    metadata = _document_metadata(document)
    for key in ("score", "rerank_score", "retrieval_score"):
        metadata_score = metadata.get(key)
        if _is_numeric_score(metadata_score):
            return float(metadata_score)
    return None


def _snapshot_rerank_inputs(documents: list[Any]) -> list[tuple[Any, float | None]]:
    return [(_document_identity(document), _document_score(document)) for document in documents]


def _has_rerank_metadata(document: Any) -> bool:
    metadata = _document_metadata(document)
    return any(key in metadata for key in _RERANK_METADATA_KEYS)


def _same_score(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return abs(left - right) < 1e-12


def _is_noop_rerank(
    original_snapshot: list[tuple[Any, float | None]],
    ranked_results: list[Any],
) -> bool:
    if len(original_snapshot) != len(ranked_results):
        return False
    if any(_has_rerank_metadata(document) for document in ranked_results):
        return False

    ranked_snapshot = _snapshot_rerank_inputs(ranked_results)
    return all(
        original_identity == ranked_identity and _same_score(original_score, ranked_score)
        for (original_identity, original_score), (ranked_identity, ranked_score) in zip(
            original_snapshot, ranked_snapshot, strict=True
        )
    )


def _annotate_rerank_scores(
    original_snapshot: list[tuple[Any, float | None]],
    ranked_results: list[Any],
    *,
    reranked: bool,
) -> None:
    original_scores_by_identity = {
        identity: score
        for identity, score in original_snapshot
        if score is not None
    }
    for document in ranked_results:
        metadata = _ensure_document_metadata(document)
        identity = _document_identity(document)
        retrieval_score = original_scores_by_identity.get(identity)
        if retrieval_score is not None:
            metadata.setdefault("retrieval_score", retrieval_score)
        if reranked:
            rerank_score = _document_score(document)
            if rerank_score is not None:
                metadata.setdefault("rerank_score", rerank_score)


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default
    return bool(value)


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _document_value(document: Any, *keys: str) -> Any:
    if isinstance(document, dict):
        for key in keys:
            value = document.get(key)
            if value not in (None, ""):
                return value

    metadata = _document_metadata(document)
    for key in keys:
        value = metadata.get(key)
        if value not in (None, ""):
            return value

    for key in keys:
        value = getattr(document, key, None)
        if value not in (None, ""):
            return value
    return None


def _document_content(document: Any) -> str:
    value = _document_value(document, "content", "page_content", "text")
    return value if isinstance(value, str) else ""


def _context_document_id(document: Any) -> str | None:
    value = _document_value(document, "document_id", "doc_id")
    return str(value) if value not in (None, "") else None


def _context_chunk_index(document: Any) -> int | None:
    return _coerce_optional_int(_document_value(document, "chunk_index"))


def _context_chunk_identity(document: Any) -> tuple[str, str, int] | tuple[str, str] | tuple[str, int]:
    document_id = _context_document_id(document)
    chunk_index = _context_chunk_index(document)
    if document_id is not None and chunk_index is not None:
        return ("chunk", document_id, chunk_index)

    document_id = _document_value(document, "id")
    if document_id not in (None, ""):
        return ("id", str(document_id))
    return ("object", id(document))


def _chunk_to_search_result(
    chunk: dict[str, Any],
    *,
    source_document: Any,
    source_chunk_index: int,
) -> SearchResult | None:
    content = _document_content(chunk)
    if not content.strip():
        return None

    metadata = dict(_document_metadata(chunk))
    document_id = _context_document_id(chunk) or _context_document_id(source_document)
    chunk_index = _context_chunk_index(chunk)
    source_score = _document_score(source_document)
    chunk_score = _document_score(chunk)
    base_score = source_score if source_score is not None else (chunk_score or 0.0)
    # 이웃 청크는 실제 히트가 아니므로 앵커 점수보다 약간 낮춰 정렬/표기 오염을 방지(#4)
    score = base_score * 0.96 if base_score > 0 else 0.0

    if document_id is not None:
        metadata.setdefault("document_id", document_id)
        metadata["context_expanded_from_document_id"] = document_id
    if chunk_index is not None:
        metadata.setdefault("chunk_index", chunk_index)
    metadata.setdefault("score", score)
    metadata.setdefault("retrieval_score", score)
    metadata["context_expanded"] = True
    metadata["context_expanded_from_chunk_index"] = source_chunk_index

    chunk_id = _document_value(chunk, "id")
    if chunk_id in (None, "") and document_id is not None and chunk_index is not None:
        chunk_id = f"{document_id}:{chunk_index}"

    return SearchResult(
        id=str(chunk_id or id(chunk)),
        content=content,
        score=score,
        metadata=metadata,
    )


@dataclass
class RouteDecision:
    """
    쿼리 라우팅 결정 결과

    Attributes:
        should_continue: RAG 파이프라인 계속 진행 여부
        immediate_response: 즉시 응답 (direct_answer/blocked인 경우)
        metadata: 라우팅 메타데이터 (route, confidence, intent, domain 등)

    Examples:
        # 즉시 응답 (파이프라인 중단)
        RouteDecision(
            should_continue=False,
            immediate_response={"answer": "안녕하세요!", ...},
            metadata={"route": "direct_answer", "confidence": 0.95}
        )

        # RAG 계속 진행
        RouteDecision(
            should_continue=True,
            immediate_response=None,
            metadata={"route": "rag", "domain": "document_query"}
        )
    """

    should_continue: bool
    immediate_response: RAGResultDict | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreparedContext:
    """
        세션 컨텍스트 + 쿼리 확장 결과 (Multi-Query RRF 지원)

        Attributes:
            session_context: 세션 컨텍스트 문자열 (최근 5개 대화)
            expanded_query: 확장된 쿼리 (첫 번째 쿼리, 하위 호환성)
            original_query: 원본 쿼리 (참조용)
            expanded_queries: 확장된 쿼리 리스트 (Multi-Query RRF용, 기본 5개)
            query_weights: 쿼리 가중치 리스트 (1.0, 0.8, 0.6, 0.4, 0.2)

        Examples:
            # Multi-Query RRF
            PreparedContext(
                session_context="사용자: 안녕하세요
    봇: 안녕하세요! 무엇을 도와드릴까요?",
                expanded_query="부산시 주민등록 발급 방법 및 필요 서류",
                original_query="주민등록 발급",
                expanded_queries=["부산시 주민등록 발급 방법", "주민등록등본 신청", ...],
                query_weights=[1.0, 0.8, 0.6, 0.4, 0.2]
            )
    """

    session_context: str | None
    expanded_query: str
    original_query: str
    expanded_queries: list[str] = field(default_factory=list)  # Multi-Query RRF용
    query_weights: list[float] = field(default_factory=list)  # 쿼리 가중치


@dataclass
class RetrievalResults:
    """
    문서 검색 결과

    Attributes:
        documents: Document 객체 리스트 (langchain_core.documents.Document)
        count: 검색된 문서 수

    Examples:
        RetrievalResults(
            documents=[
                Document(page_content="...", metadata={"source": "doc1.pdf", "score": 0.89}),
                Document(page_content="...", metadata={"source": "doc2.pdf", "score": 0.76})
            ],
            count=2
        )
    """

    documents: list[Any]
    count: int


@dataclass
class RerankResults:
    """
    리랭킹 결과

    Attributes:
        documents: 리랭킹된 Document 객체 리스트
        count: 리랭킹된 문서 수
        reranked: 실제로 리랭킹이 수행되었는지 여부

    Examples:
        # 리랭킹 성공
        RerankResults(documents=[...], count=10, reranked=True)

        # 리랭킹 실패 (원본 반환)
        RerankResults(documents=[...], count=15, reranked=False)
    """

    documents: list[Any]
    count: int
    reranked: bool


# GenerationResult는 generator.py에서 import (L30)


@dataclass
class FormattedSources:
    """
    포맷팅된 소스 리스트

    Attributes:
        sources: Source 객체 리스트 (app.models.prompts.Source)
        count: 소스 개수

    Examples:
        FormattedSources(
            sources=[Source(id=0, document="doc1.pdf", relevance=0.89, ...), ...],
            count=5
        )
    """

    sources: list[Any]
    count: int


class PipelineTracker:
    """
    RAG 파이프라인 단계별 타이밍 추적 클래스

    8개 단계 각각의 실행 시간을 기록하고, 병목 지점을 식별.

    사용법:
        tracker = PipelineTracker()
        tracker.start_pipeline()

        tracker.start_stage("route_query")
        # ... 작업 수행 ...
        tracker.end_stage("route_query")

        tracker.end_pipeline()
        metrics = tracker.get_metrics()

    메트릭 형식:
        {
            'total_duration_ms': 1250.5,
            'stages': {
                'route_query': {'duration_ms': 45.2, 'percentage': 3.6},
                'retrieve_documents': {'duration_ms': 823.1, 'percentage': 65.8},
                ...
            },
            'slowest_stage': 'retrieve_documents'
        }
    """

    def __init__(self):
        """PipelineTracker 초기화"""
        self.stages: dict[str, dict[str, Any]] = {}  # Multi-Query RRF 메타데이터를 위해 Any 허용
        self.start_time: float = 0.0
        self.end_time: float = 0.0

    def start_pipeline(self) -> None:
        """파이프라인 시작 시간 기록"""
        self.start_time = time.time()
        logger.debug("Pipeline tracking 시작")

    def start_stage(self, stage_name: str) -> None:
        """
        단계 시작 시간 기록

        Args:
            stage_name: 단계 이름 (예: "route_query", "retrieve_documents")
        """
        if stage_name not in self.stages:
            self.stages[stage_name] = {}
        self.stages[stage_name]["start"] = time.time()

    def end_stage(self, stage_name: str) -> None:
        """
        단계 종료 시간 기록 및 duration 계산

        Args:
            stage_name: 단계 이름
        """
        if stage_name in self.stages and "start" in self.stages[stage_name]:
            self.stages[stage_name]["end"] = time.time()
            self.stages[stage_name]["duration"] = (
                self.stages[stage_name]["end"] - self.stages[stage_name]["start"]
            )
        else:
            logger.warning(
                "Stage가 시작되지 않았거나 이미 종료됨",
                extra={"stage_name": stage_name}
            )

    def end_pipeline(self) -> None:
        """파이프라인 종료 시간 기록"""
        self.end_time = time.time()
        logger.debug("Pipeline tracking 종료")

    def get_metrics(self) -> dict[str, Any]:
        """
        성능 메트릭 반환

        Returns:
            메트릭 딕셔너리:
            - total_duration_ms: 전체 실행 시간 (밀리초)
            - stages: 각 단계별 실행 시간 및 비율
            - slowest_stage: 가장 느린 단계 이름
        """
        total_duration = self.end_time - self.start_time if self.end_time > 0 else 0
        stage_metrics = {}
        for stage, times in self.stages.items():
            duration = times.get("duration", 0)
            percentage = duration / total_duration * 100 if total_duration > 0 else 0
            stage_metrics[stage] = {
                "duration_ms": round(duration * 1000, 1),
                "percentage": round(percentage, 1),
            }
        slowest_stage = None
        if self.stages:
            slowest_stage = max(self.stages.items(), key=lambda x: x[1].get("duration", 0))[0]
        return {
            "total_duration_ms": round(total_duration * 1000, 1),
            "stages": stage_metrics,
            "slowest_stage": slowest_stage,
        }

    def log_summary(self) -> None:
        """성능 메트릭 요약 로그 출력"""
        metrics = self.get_metrics()
        logger.info("=" * 60)
        logger.info("Pipeline Performance Summary")
        logger.info(
            "총 실행 시간",
            extra={"total_duration_ms": metrics['total_duration_ms']}
        )
        logger.info(
            "가장 느린 단계",
            extra={"slowest_stage": metrics.get('slowest_stage', 'N/A')}
        )
        logger.info("-" * 60)
        for stage, data in metrics["stages"].items():
            logger.info(
                "단계별 성능",
                extra={
                    "stage": stage,
                    "duration_ms": data['duration_ms'],
                    "percentage": data['percentage']
                }
            )
        logger.info("=" * 60)


class RAGPipeline:
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
        logger.info(
            "RAGPipeline 초기화 완료",
            extra={
                "sql_search": "활성화" if sql_search_service else "비활성화",
                "agent": "활성화" if agent_orchestrator else "비활성화",
                "score_normalization": "활성화" if score_norm_config.get('enabled', True) else "비활성화"
            }
        )

    def _create_fallback_response(
        self, message: str, start_time: float, routing_metadata: dict[str, Any]
    ) -> RAGResultDict:
        """라우팅 실패 시 기본 응답 생성"""
        processing_time = time.time() - start_time
        return cast(
            RAGResultDict,
            {
                "answer": "응답을 생성할 수 없습니다.",
                "sources": [],
                "tokens_used": 0,
                "topic": self.extract_topic_func(message),
                "processing_time": processing_time,
                "search_results": 0,
                "ranked_results": 0,
                "model_info": {"provider": "system", "model": "fallback"},
                "routing_metadata": routing_metadata,
            },
        )

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
            from ..schemas.debug import DebugTrace

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

    def _build_retrieval_filters(self, options: dict[str, Any]) -> dict[str, Any] | None:
        """요청 옵션에서 검색 메타데이터 필터를 구성한다(#12).

        options['filters'](dict)를 그대로 사용하고, 비어있으면 None을 반환해
        기존 무필터 동작과 100% 동일하게 동작한다(회귀 방지).
        """
        raw_filters = options.get("filters")
        filters = dict(raw_filters) if isinstance(raw_filters, dict) else {}
        return filters or None

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

                chunk = chunks_by_index.get(index)
                if not chunk:
                    continue
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

    def _resolve_rag_mode(self, options: dict[str, Any]) -> str:
        """Resolve local/grok_search/grok_answer without changing default local flow."""
        explicit_mode = options.get("rag_mode") or options.get("grok_mode")
        if explicit_mode:
            return self._normalize_rag_mode(str(explicit_mode))

        vector_db_config = self.config.get("vector_db", {})
        vector_provider = (
            vector_db_config.get("provider")
            or self.config.get("vector_store", {}).get("provider")
            or os.getenv("VECTOR_DB_PROVIDER", "")
        )
        if str(vector_provider).lower() != "grok":
            return "local"

        grok_config = self.config.get("grok", {})
        return self._normalize_rag_mode(str(grok_config.get("mode", "search")))

    @staticmethod
    def _normalize_rag_mode(mode: str) -> str:
        normalized = mode.strip().lower().replace("-", "_")
        aliases = {
            "local": "local",
            "standard": "local",
            "grok": "grok_search",
            "grok_search": "grok_search",
            "search": "grok_search",
            "grok_answer": "grok_answer",
            "answer": "grok_answer",
        }
        return aliases.get(normalized, "local")

    def _format_grok_citations(self, citations: list[Any]) -> list[Any]:
        """Convert Grok citation payloads into OneRAG Source objects."""
        sources: list[Any] = []
        for idx, citation in enumerate(citations):
            source_data = normalize_citation_source_payload(idx, citation, source_type="grok")
            sources.append(self.Source(**source_data))
        return sources

    async def _execute_grok_answer_mode(
        self,
        message: str,
        start_time: float,
        options: dict[str, Any],
        routing_metadata: dict[str, Any],
    ) -> RAGResultDict:
        """Execute Grok managed RAG answer mode as a narrow fast path."""
        provider = self.grok_answer_provider
        if asyncio.iscoroutine(provider) or isinstance(provider, asyncio.Future):
            provider = await provider

        if provider is None:
            raise RetrievalError(
                ErrorCode.GROK_003,
                reason="Grok answer mode requested but GrokAnswerProvider is not configured",
            )

        result = await provider.answer(
            question=message,
            collection_ids=options.get("collection_ids") or options.get("grok_collection_ids"),
            system_prompt=options.get("system_prompt"),
            top_k=options.get("top_k") or options.get("limit"),
            temperature=float(options.get("temperature", 0.0)),
            include_code_interpreter=bool(options.get("include_code_interpreter", False)),
        )
        sources = self._format_grok_citations(result.citations)
        model_info = {
            "provider": result.provider,
            "model": result.model_used,
            "model_used": result.model_used,
            "mode": "grok_answer",
            "tool_usage": result.tool_usage,
            "citations_count": len(result.citations),
        }
        routing_metadata = {
            **routing_metadata,
            "rag_mode": "grok_answer",
            "source": routing_metadata.get("source", "grok"),
        }
        return self.build_result(
            answer=result.answer,
            sources=sources,
            tokens_used=result.tokens_used,
            topic=self.extract_topic_func(message),
            processing_time=time.time() - start_time,
            search_count=len(result.citations),
            ranked_count=len(result.citations),
            model_info=model_info,
            routing_metadata=routing_metadata,
        )

    # ========================================
    # 멀티턴 standalone query rewrite
    # ========================================

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

    def _needs_standalone_rewrite(self, message: str) -> bool:
        """
        멀티턴 standalone rewrite가 필요한지 판정하는 게이트.

        후속 질문이 대명사/지시어/생략 표현에 의존하거나 너무 짧아
        그 자체로는 검색 맥락이 불충분한 경우에만 True를 반환한다.
        이미 자립적(충분히 길고 구체적)인 질문은 False를 반환해 불필요한
        LLM 호출과 지연을 막는다.

        Args:
            message: 후속 사용자 질문(원본)

        Returns:
            True면 재작성 필요(LLM 호출 대상), False면 게이트에서 건너뜀.
        """
        stripped = message.strip()
        if not stripped:
            return False

        # (1) 대명사/지시어/생략 표현 포함 → 자립 불가로 간주
        if any(pattern in stripped for pattern in self.multiturn_followup_dependent_patterns):
            return True

        # (1-b) 문장 시작 위치의 접속사만 후속 신호로 취급
        #       (문장 중간 "A 그리고 B"는 자립 질문이므로 제외)
        if any(stripped.startswith(pattern) for pattern in self.multiturn_followup_start_patterns):
            return True

        # (2) 짧은 후속 질문(맥락 생략형). 어절(공백 분리) 기준으로 판단.
        #     예: "정규직 요건은?" 처럼 핵심 대상(프로그램명 등)이 생략된 형태.
        #     충분히 긴 질문은 자립적으로 보고 건너뛴다.
        word_count = len(stripped.split())
        if word_count <= self.multiturn_short_question_max_words:
            return True

        # (3) 그 외 길고 구체적인 질문은 자립적으로 간주 → 재작성 불필요
        return False

    # 재작성 결과 정제용: 모델이 흔히 붙이는 라벨 접두어
    _REWRITE_LABEL_PATTERN = re.compile(
        r"^\s*(재작성(된)?\s*(질문|쿼리)?|standalone(\s*query)?|질문|rewritten\s*query)\s*[:：]\s*",
        re.IGNORECASE,
    )

    def _postprocess_rewritten_query(self, content: str | None) -> str:
        """
        LLM 재작성 결과를 검색에 안전하게 투입하도록 경량 정제한다.

        모델이 프롬프트 지시를 어기고 여러 줄/머리말 라벨/따옴표를 붙이는 경우를
        방어한다. 첫 번째 비어있지 않은 줄만 취하고, "재작성: " 같은 라벨과
        앞뒤 따옴표를 제거한다.

        Args:
            content: LLM 원본 응답 텍스트(None 가능)

        Returns:
            정제된 한 줄 질문 문자열(정제 후 비면 빈 문자열).
        """
        if not content:
            return ""

        # 첫 번째 비어있지 않은 줄만 사용 (여러 줄 방어)
        first_line = ""
        for line in content.splitlines():
            if line.strip():
                first_line = line.strip()
                break
        if not first_line:
            return ""

        # 라벨 접두어 제거 (예: "재작성된 질문: ...")
        first_line = self._REWRITE_LABEL_PATTERN.sub("", first_line).strip()

        # 앞뒤 따옴표 제거 (직선/곡선 따옴표 모두)
        first_line = first_line.strip("\"'“”‘’").strip()

        return first_line

    async def _rewrite_standalone_query(
        self, message: str, session_context: str | None
    ) -> str:
        """
        직전 대화 맥락을 반영해 후속 질문을 자립적(standalone) 질문으로 재작성.

        게이트(`_needs_standalone_rewrite`)와 사전 조건(설정 활성화, 세션 맥락,
        llm_factory 존재)을 모두 통과한 경우에만 LLM을 호출한다. 재작성에
        실패하면(예외/빈 결과) 원본 질문으로 graceful 폴백하여 검색을 계속한다.

        Args:
            message: 후속 사용자 질문(원본)
            session_context: 직전 대화 컨텍스트 문자열(없으면 재작성 생략)

        Returns:
            재작성된 standalone 질문, 또는 폴백 시 원본 질문.
        """
        # 사전 조건 확인 (어느 하나라도 불충족이면 원본 반환)
        if not self.multiturn_rewrite_enabled:
            return message
        if not session_context or not session_context.strip():
            return message
        if self.llm_factory is None:
            logger.debug("standalone rewrite 생략: llm_factory 없음")
            return message

        # 게이트: 자립적 질문이면 LLM 호출 없이 건너뜀
        if not self._needs_standalone_rewrite(message):
            logger.debug(
                "standalone rewrite 게이트 통과(자립적 질문), 재작성 생략",
                extra={"message": message[:40]},
            )
            return message

        # LLM 재작성 프롬프트 구성
        prompt = (
            "당신은 멀티턴 대화의 후속 질문을 검색에 적합한 자립적(standalone) "
            "질문으로 재작성하는 전문가입니다.\n\n"
            "아래 [직전 대화 맥락]을 참고하여, [후속 질문]에서 생략되거나 "
            "대명사/지시어로 표현된 핵심 대상(프로그램명, 제도명, 주체 등)을 "
            "명시적으로 복원해 하나의 완결된 질문으로 다시 쓰세요.\n"
            "- 맥락에 없는 정보를 새로 추가하지 마세요.\n"
            "- 후속 질문의 의도를 바꾸지 마세요.\n"
            "- 설명 없이 재작성된 질문 한 문장만 출력하세요.\n\n"
            f"[직전 대화 맥락]\n{session_context}\n\n"
            f"[후속 질문]\n{message}\n\n"
            "[재작성된 자립적 질문]"
        )

        try:
            # 결정적(temperature=0.0) 호출로 재작성의 비결정성을 차단.
            # max_tokens는 thinking(추론) 모델이 추론에 토큰을 소진해 출력이
            # 빈 채 truncate되는 회귀(실가동 관측)를 막기 위해 넉넉히 둔다.
            content, provider = await self.llm_factory.generate_with_fallback(
                prompt=prompt,
                system_prompt=None,
                preferred_provider=self.multiturn_rewrite_provider,
                temperature=0.0,
                max_tokens=2048,
            )
            rewritten = self._postprocess_rewritten_query(content)
            # 빈 결과/비정상적으로 긴 결과는 신뢰하지 않고 폴백
            if not rewritten or len(rewritten) > len(message) + 200:
                logger.warning(
                    "standalone rewrite 결과 비정상, 원본 사용",
                    extra={"original": message[:40]},
                )
                return message

            logger.info(
                "standalone rewrite 성공",
                extra={
                    "provider": provider,
                    "original": message[:40],
                    "rewritten": rewritten[:60],
                },
            )
            return rewritten
        except Exception as e:
            # LLM 실패는 채팅을 깨뜨리지 않고 원본으로 폴백
            logger.warning(
                "standalone rewrite 실패, 원본 사용",
                extra={"error": str(e), "original": message[:40]},
                exc_info=True,
            )
            return message

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

    @observe(name="RAG Pipeline", capture_input=True, capture_output=True)
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

        use_agent = options.get("use_agent", False)
        if use_agent and self.agent_orchestrator:
            logger.info("Agent 모드 활성화", extra={"orchestrator": "AgentOrchestrator"})
            return await self._execute_agent_mode(message, session_id, start_time)

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

        if enable_debug_trace:
            debug_trace_data["original_query"] = message

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

        tracker.start_stage("prepare_context")
        prepared_context = await self._run_stage_with_timeout(
            "prepare_context",
            self.prepare_context(message, session_id),
            remaining_budget=self._remaining_total_budget(start_time),
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
            remaining_budget=self._remaining_total_budget(start_time),
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
            remaining_budget=self._remaining_total_budget(start_time),
        )
        tracker.end_stage("rerank_documents")

        if enable_debug_trace and rerank_results.reranked:
            for i, doc in enumerate(rerank_results.documents):
                if i < len(debug_trace_data["retrieved_documents"]):
                    rerank_score = doc.metadata.get("rerank_score", 0.0) if hasattr(doc, "metadata") else 0.0
                    debug_trace_data["retrieved_documents"][i]["rerank_score"] = rerank_score

        tracker.start_stage("expand_context")
        context_documents = await self.expand_context_documents(rerank_results.documents, options)
        tracker.end_stage("expand_context")

        tracker.start_stage("generate_answer")
        generation_options = {**options}
        # 인접 청크 확장으로 문서가 늘어났을 때만 프롬프트 한도를 상향(20)해
        # 실제 검색 히트가 이웃 청크에 밀려 프롬프트에서 빠지지 않게 한다(#3).
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
        tracker.end_stage("self_rag_verify")

        tracker.start_stage("format_sources")
        formatted_sources = self.format_sources(context_documents, sql_search_result)
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
            # 인접 청크 확장으로 추가된 이웃 청크는 실제 히트가 아니므로 카운트에서 제외(#4)
            ranked_count=sum(
                1
                for doc in context_documents
                if not _document_metadata(doc).get("context_expanded")
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

    async def route_query(self, message: str, session_id: str, start_time: float) -> RouteDecision:
        """
        1단계: 쿼리 라우팅 (규칙 기반 + LLM 폴백)

        - 규칙 기반 라우터 우선 시도 (YAML 규칙)
        - LLM 라우터 폴백 (규칙 실패 시)
        - direct_answer/blocked 처리

        Args:
            message: 사용자 쿼리
            session_id: 세션 ID
            start_time: 파이프라인 시작 시간

        Returns:
            RouteDecision: 라우팅 결정 (계속 진행 여부 + 즉시 응답)

        Raises:
            RoutingError: 라우팅 실패 시
        """
        logger.debug("[1단계] 쿼리 라우팅 시작")
        routing_metadata = {}
        session_context = None
        if self.session_module:
            try:
                conversation = await self.session_module.get_conversation(
                    session_id, max_exchanges=5
                )
                if conversation and isinstance(conversation, list):
                    session_context = "\n".join(
                        [
                            f"User: {ex.get('user', '')}\nAssistant: {ex.get('assistant', '')}"
                            for ex in conversation
                        ]
                    )
            except Exception as e:
                logger.warning(
                    "세션 컨텍스트 조회 실패",
                    extra={"error": str(e)},
                    exc_info=True
                )
        try:
            global RuleBasedRouter
            if RuleBasedRouter is None:
                from ...modules.core.routing.rule_based_router import (
                    RuleBasedRouter as _RuleBasedRouter,
                )

                RuleBasedRouter = _RuleBasedRouter

            rule_router = RuleBasedRouter(enabled=True)
            rule_match = await rule_router.check_rules(message)
            if rule_match:
                routing_metadata = {
                    "route": rule_match.route,
                    "intent": rule_match.intent,
                    "domain": rule_match.domain,
                    "confidence": rule_match.confidence,
                    "source": "rule_based",
                    "rule_name": rule_match.rule_name,
                }
                logger.info(
                    "[규칙 기반 라우터] 매칭",
                    extra={
                        "rule_name": rule_match.rule_name,
                        "route": rule_match.route,
                        "domain": rule_match.domain
                    }
                )
                if rule_match.route == "direct_answer" and rule_match.direct_answer:
                    processing_time = time.time() - start_time
                    immediate_response = {
                        "answer": rule_match.direct_answer,
                        "sources": [],
                        "tokens_used": 0,
                        "topic": self.extract_topic_func(message),
                        "processing_time": processing_time,
                        "search_count": 0,
                        "ranked_count": 0,
                        "model_info": {"provider": "rule_based", "model": "N/A"},
                        "routing_metadata": routing_metadata,
                    }

                    logger.info(
                        "[즉시 응답] 규칙 기반 답변 반환",
                        extra={"processing_time": processing_time}
                    )
                    return RouteDecision(
                        should_continue=False,
                        immediate_response=cast(RAGResultDict, immediate_response),
                        metadata=routing_metadata,
                    )
                return RouteDecision(
                    should_continue=True, immediate_response=None, metadata=routing_metadata
                )
        except Exception as rule_error:
            logger.warning(
                "[RuleBasedRouter] 오류",
                extra={"error": str(rule_error)},
                exc_info=True
            )
        if not self.query_router or not self.query_router.enabled:
            logger.info("[LLM 라우터] 비활성화 - RAG 계속 진행")
            return RouteDecision(
                should_continue=True, immediate_response=None, metadata=routing_metadata
            )
        try:
            profile, routing = await self.query_router.analyze_and_route(
                message, session_context=session_context
            )

            # 🆕 dataclass 속성 접근으로 수정 (Oracle 권장사항)
            routing_metadata.update(
                {
                    "llm_route": routing.primary_route,  # ✅ .get() → 속성 접근
                    "llm_intent": profile.intent.value if profile.intent else "unknown",  # ✅
                    "llm_domain": profile.domain,  # ✅
                    "llm_confidence": routing.confidence,  # ✅
                    "llm_reasoning": routing.notes or "",  # ✅
                    "data_source": getattr(profile, "data_source", "general"),  # 🆕 신규 필드
                    "source": routing_metadata.get("source", "llm"),
                    "profile": profile,
                }
            )
            logger.info(
                "[LLM 라우터] 라우팅 완료",
                extra={
                    "route": routing.primary_route,
                    "data_source": routing_metadata['data_source'],
                    "intent": profile.intent.value if profile.intent else 'unknown',
                    "confidence": routing.confidence
                }
            )
            if routing.primary_route == "blocked":
                processing_time = time.time() - start_time
                immediate_response = {
                    "answer": "죄송합니다. 해당 질문은 처리할 수 없습니다.",
                    "sources": [],
                    "tokens_used": 0,
                    "topic": self.extract_topic_func(message),
                    "processing_time": processing_time,
                    "search_count": 0,
                    "ranked_count": 0,
                    "model_info": {"provider": "query_router", "model": "N/A"},
                    "routing_metadata": routing_metadata,
                }
                logger.warning(
                    "[차단] 쿼리가 차단됨",
                    extra={"reason": routing.notes}
                )
                return RouteDecision(
                    should_continue=False,
                    immediate_response=cast(RAGResultDict, immediate_response),
                    metadata=routing_metadata,
                )
        except Exception as llm_error:
            logger.warning(
                "[LLM 라우터] 오류",
                extra={"error": str(llm_error)},
                exc_info=True
            )
            routing_metadata["fallback_reason"] = str(llm_error)
        logger.info("[라우팅 완료] RAG 파이프라인 계속 진행")
        return RouteDecision(
            should_continue=True, immediate_response=None, metadata=routing_metadata
        )

    # NOTE: _get_score_multipliers() 함수 제거됨 (2026-01-02)
    # 스코어 가중치는 ScoringService(rag.yaml의 scoring 섹션)에서 관리됩니다.
    # 마이그레이션 가이드: DOMAIN_CUSTOMIZATION_GUIDE.md 참조

    @observe(name="Query Expansion & Context Preparation")
    async def prepare_context(self, message: str, session_id: str) -> PreparedContext:
        """
        2단계: 세션 컨텍스트 조회 + 쿼리 확장

        - 세션 모듈에서 최근 5개 대화 조회
        - 쿼리 확장 모듈로 쿼리 확장 (선택적)

        Args:
            message: 원본 쿼리
            session_id: 세션 ID

        Returns:
            PreparedContext: 세션 컨텍스트 + 확장된 쿼리
        """
        logger.debug("[3단계] 컨텍스트 준비 시작")
        session_context = None
        if self.session_module:
            try:
                context_string = await self.session_module.get_context_string(session_id)
                if context_string:
                    session_context = context_string
                    logger.debug(
                        "세션 컨텍스트 로드 성공",
                        extra={"context_length": len(context_string)}
                    )
                else:
                    logger.debug("세션 컨텍스트 비어있음")
            except Exception as e:
                logger.warning(
                    "세션 컨텍스트 조회 실패",
                    extra={"error": str(e)},
                    exc_info=True
                )

        # 멀티턴 standalone query rewrite (검색 측 맥락 보강, 기본 OFF)
        # 직전 대화가 있고 후속 질문이 자립적이지 않으면(대명사/생략/축약),
        # 직전 맥락을 반영한 standalone 질문으로 재작성해 검색에 투입한다.
        # 원본 질문(message)은 PreparedContext.original_query로 보존된다.
        search_message = await self._rewrite_standalone_query(message, session_context)

        # Multi-Query RRF: 모든 확장 쿼리와 가중치 추출
        expanded_query = search_message
        expanded_queries: list[str] = []
        query_weights: list[float] = []

        if self.query_expansion:
            try:
                logger.debug("쿼리 확장 시도")
                expansion_result = await self.query_expansion.expand_query(
                    query=search_message, context=session_context
                )

                if expansion_result and hasattr(expansion_result, "expansions"):
                    if expansion_result.expansions:
                        # metadata에서 raw_expanded_queries 추출 (weight 정보 포함)
                        raw_queries = expansion_result.metadata.get("raw_expanded_queries", [])

                        if raw_queries:
                            # 원본 데이터에서 쿼리와 가중치 추출
                            for item in raw_queries:
                                if isinstance(item, dict):
                                    query = item.get("query", "")
                                    weight = item.get("weight", 1.0)
                                    if query:
                                        expanded_queries.append(query)
                                        query_weights.append(weight)

                        # raw_queries가 없으면 expansions에서 추출 (가중치는 동일하게)
                        if not expanded_queries:
                            expanded_queries = expansion_result.expansions
                            query_weights = [1.0] * len(expanded_queries)

                        expanded_query = expanded_queries[0]  # 첫 번째 쿼리 (하위 호환성)
                        logger.info(
                            "쿼리 확장 성공",
                            extra={
                                "query_count": len(expanded_queries),
                                "weights": [f'{w:.1f}' for w in query_weights],
                                "original": message[:30],
                                "expanded": expanded_query[:30]
                            }
                        )
                    else:
                        logger.debug("쿼리 확장 결과 없음, 원본 사용")
                        expanded_queries = [search_message]
                        query_weights = [1.0]
                else:
                    logger.debug("쿼리 확장 결과 없음, 원본 사용")
                    expanded_queries = [search_message]
                    query_weights = [1.0]
            except Exception as e:
                logger.warning(
                    "쿼리 확장 실패, 원본 사용",
                    extra={"error": str(e)},
                    exc_info=True
                )
                expanded_queries = [search_message]
                query_weights = [1.0]
        else:
            # query_expansion 모듈 없음
            expanded_queries = [search_message]
            query_weights = [1.0]

        logger.debug(
            "[3단계] 컨텍스트 준비 완료",
            extra={"expanded_query": expanded_query[:50]}
        )
        return PreparedContext(
            session_context=session_context,
            expanded_query=expanded_query,
            original_query=message,
            expanded_queries=expanded_queries,
            query_weights=query_weights,
        )

    @observe(name="Document Retrieval (Hybrid Search)")
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

        cb = self.circuit_breaker_factory.get("document_retrieval")

        async def _search() -> list[SearchResult]:
            """실제 검색 로직 (Circuit Breaker 내부) - Multi-Query RRF"""
            # ✅ #12 수정: 요청 옵션의 메타데이터 필터를 실제 검색에 연결한다.
            # 필터가 없으면 None을 반환해 기존 무필터 동작과 100% 동일하다(회귀 방지).
            retrieval_filters = self._build_retrieval_filters(options)
            search_options = {
                "limit": options.get("limit", self.retrieval_limit),
                "min_score": options.get("min_score", self.min_score),
                "context": context,
                "filters": retrieval_filters,
            }

            # Multi-Query 검색: IMultiQueryRetriever Protocol 체크
            # RetrievalOrchestrator 직접 사용 (프로덕션)
            if isinstance(retrieval_module, IMultiQueryRetriever):
                return await retrieval_module._search_and_merge(
                    queries=search_queries,
                    top_k=search_options["limit"],
                    filters=retrieval_filters,
                    weights=query_weights,
                    use_rrf=True,  # RRF 활성화
                )
            # 하위 호환성: orchestrator를 속성으로 갖는 경우
            elif hasattr(retrieval_module, "orchestrator"):
                orchestrator = retrieval_module.orchestrator
                if isinstance(orchestrator, IMultiQueryRetriever):
                    # orchestrator._search_and_merge 직접 호출 (RRF 병합)
                    return await orchestrator._search_and_merge(
                        queries=search_queries,
                        top_k=search_options["limit"],
                        filters=retrieval_filters,
                        weights=query_weights,
                        use_rrf=True,  # RRF 활성화
                    )

            # Fallback: 단일 쿼리 검색 (기존 방식)
            # orchestrator.search(query, options) 시그니처를 그대로 사용한다.
            # search_options에 filters가 포함되며, 어댑터가 지원하면 활용한다.
            return cast(
                list[SearchResult], await retrieval_module.search(search_queries[0], search_options)
            )

        try:
            start_time = time.time()
            search_results = await cb.call(_search, fallback=lambda: [])
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

    async def rerank_documents(
        self, search_query: str, search_results: list[Any], options: dict[str, Any]
    ) -> RerankResults:
        """
        4단계: 검색 결과 리랭킹 (선택적)

        - 리랭킹 설정 확인 (config.reranking.enabled)
        - Jina/Cohere/LLM 리랭커 호출
        - 실패 시 원본 반환

        Args:
            search_query: 검색 쿼리
            search_results: 검색 결과 (Document 리스트)
            options: 리랭킹 옵션 (top_n 등)

        Returns:
            RerankResults: 리랭킹된 문서 리스트 (reranked=True/False)
        """
        logger.debug("[5단계] 리랭킹 시작")
        if not search_results:
            logger.debug("검색 결과 없음, 리랭킹 스킵")
            return RerankResults(documents=[], count=0, reranked=False)
        reranking_config = self.config.get("reranking", {})
        retrieval_config = self.config.get("retrieval", {})
        reranking_enabled = reranking_config.get("enabled", False) or retrieval_config.get(
            "enable_reranking", False
        )
        if not reranking_enabled:
            logger.debug("리랭킹 비활성화 - 원본 사용")
            return RerankResults(
                documents=search_results, count=len(search_results), reranked=False
            )
        # Future 객체 해결
        retrieval_module = self.retrieval_module
        if asyncio.iscoroutine(retrieval_module) or isinstance(retrieval_module, asyncio.Future):
            retrieval_module = await retrieval_module

        if not retrieval_module or not hasattr(retrieval_module, "rerank"):
            logger.warning("리랭킹 모듈 없음 - 원본 사용")
            return RerankResults(
                documents=search_results, count=len(search_results), reranked=False
            )
        try:
            original_snapshot = _snapshot_rerank_inputs(search_results)
            logger.debug(
                "리랭킹 실행",
                extra={"document_count": len(search_results)}
            )
            ranked_results = await retrieval_module.rerank(
                query=search_query,
                results=search_results,
                top_n=options.get("top_n", self.rerank_top_n),
            )
            if _is_noop_rerank(original_snapshot, ranked_results):
                _annotate_rerank_scores(original_snapshot, ranked_results, reranked=False)
                logger.warning(
                    "[5단계] 리랭커가 원본 결과를 그대로 반환 - 리랭킹 미수행 처리",
                    extra={"document_count": len(ranked_results)}
                )
                return RerankResults(
                    documents=ranked_results,
                    count=len(ranked_results),
                    reranked=False,
                )

            _annotate_rerank_scores(original_snapshot, ranked_results, reranked=True)

            # 리랭킹 후 min_score 필터링
            min_score = reranking_config.get("min_score", 0.05)
            if min_score > 0:
                before_count = len(ranked_results)
                ranked_results = [
                    doc
                    for doc in ranked_results
                    if (hasattr(doc, "score") and doc.score >= min_score)
                    or (hasattr(doc, "metadata") and doc.metadata.get("score", 0) >= min_score)
                ]
                if before_count > len(ranked_results):
                    logger.info(
                        "min_score 필터링",
                        extra={
                            "before_count": before_count,
                            "after_count": len(ranked_results),
                            "threshold": min_score
                        }
                    )
            logger.info(
                "[5단계] 리랭킹 완료",
                extra={"document_count": len(ranked_results)}
            )
            return RerankResults(documents=ranked_results, count=len(ranked_results), reranked=True)
        except Exception as e:
            logger.warning(
                "[5단계] 리랭킹 실패, 원본 사용",
                extra={"error": str(e)},
                exc_info=True
            )
            return RerankResults(
                documents=search_results, count=len(search_results), reranked=False
            )

    @observe(name="Answer Generation (LLM)")
    async def generate_answer(
        self, message: str, ranked_results: list[Any], context: str | None, options: dict[str, Any]
    ) -> GenerationResult:
        """
        5단계: LLM 답변 생성

        - LLM 답변 생성 (Gemini/OpenAI/Claude)
        - Circuit Breaker 보호
        - Fallback 답변 처리 (LLM 실패 시)
        - 비용 추적 (CostTracker)

        Args:
            message: 사용자 질문
            ranked_results: 리랭킹된 문서
            context: 세션 컨텍스트
            options: 생성 옵션

        Returns:
            GenerationResult: 답변 + 토큰 수 + 모델 정보

        Raises:
            GenerationError: 답변 생성 실패 시
        """
        from ...modules.core.generation.generator import GenerationResult

        logger.debug("[6단계] 답변 생성 시작")
        if not self.generation_module:
            logger.error("생성 모듈 없음")
            return GenerationResult(
                answer="죄송합니다. 답변을 생성할 수 없습니다.",
                text="죄송합니다. 답변을 생성할 수 없습니다.",
                tokens_used=0,
                model_used="none",
                provider="none",
                generation_time=0.0,
            )
        cb = self.circuit_breaker_factory.get("answer_generation")
        safe_docs = []
        dropped_count = 0
        for doc in ranked_results or []:
            if validate_document(doc):
                safe_docs.append(doc)
            else:
                dropped_count += 1
                logger.warning(
                    "문서 인젝션 패턴 감지 - 차단",
                    extra={"total_dropped": dropped_count}
                )
        if dropped_count > 0:
            logger.info(
                "안전 문서 필터링 완료",
                extra={"safe_count": len(safe_docs), "dropped_count": dropped_count}
            )
        context_documents = safe_docs

        async def _generate() -> GenerationResult:
            """실제 답변 생성 로직 (Circuit Breaker 내부)"""
            # session_context를 options에 포함시켜 전달
            generation_options = {**options, "session_context": context}
            return cast(
                GenerationResult,
                await self.generation_module.generate_answer(
                    query=message, context_documents=context_documents, options=generation_options
                ),
            )

        def _fallback() -> dict[str, Any]:
            """LLM 실패 시 Fallback 답변"""
            if context_documents:
                top_doc = context_documents[0]
                content = _extract_fallback_document_preview(top_doc)
                return {
                    "answer": f"관련 정보를 찾았습니다:\n\n{content}...\n\n(현재 AI 서비스 일시 장애로 상세 답변이 어렵습니다. 잠시 후 다시 시도해주세요.)",
                    "tokens_used": 0,
                    "model_info": {"provider": "fallback", "model": "document_summary"},
                }
            else:
                return {
                    "answer": "죄송합니다. 관련 정보를 찾을 수 없으며, 현재 AI 서비스도 일시적으로 이용할 수 없습니다. 다른 방식으로 질문해 주시겠어요?",
                    "tokens_used": 0,
                    "model_info": {"provider": "fallback", "model": "none"},
                }

        try:
            start_time = time.time()
            generation_result: GenerationResult | dict[str, Any] = await cb.call(
                _generate, fallback=_fallback
            )
            latency_ms = (time.time() - start_time) * 1000
            self.performance_metrics.record_latency("generate_integrated_answer", latency_ms)

            # 타입 가드: GenerationResult 또는 dict 처리
            # GenerationResult 객체인지 확인 (hasattr로도 체크하여 더 안전하게)
            if isinstance(generation_result, GenerationResult):
                tokens = generation_result.tokens_used
                provider = generation_result.provider
                answer = generation_result.answer
                model_info = generation_result.model_info
            elif isinstance(generation_result, dict):
                # fallback이 dict를 반환한 경우 (Circuit Breaker 내부 fallback)
                tokens = generation_result.get("tokens_used", 0)
                provider = generation_result.get("model_info", {}).get("provider", "google")
                answer = generation_result.get("answer", "답변을 생성할 수 없습니다.")
                model_info = generation_result.get("model_info", {})
            else:
                # 예상치 못한 타입 (안전 장치)
                logger.error(f"⚠️ 예상치 못한 generation_result 타입: {type(generation_result)}")
                tokens = 0
                provider = "unknown"
                answer = "답변 생성 중 오류가 발생했습니다."
                model_info = {"provider": "error", "model": "unknown"}

            if tokens > 0 and provider in ["google", "openai", "anthropic"]:
                self.cost_tracker.track_usage(provider, tokens, is_input=False)

            if contains_output_leakage(answer):
                logger.error(
                    "프롬프트 누출 감지 - 답변 차단",
                    extra={"preview": answer[:100]}
                )
                answer = "보안 정책에 따라 내부 지시사항은 공개되지 않습니다. 문서 기반 답변이 필요한 내용을 다시 질문해주세요."
                self.performance_metrics.record_error("prompt_leakage_blocked")

            logger.info(
                "[6단계] 답변 생성 완료",
                extra={
                    "answer_length": len(answer),
                    "latency_ms": latency_ms,
                    "tokens": tokens
                }
            )
            return GenerationResult(
                answer=answer,
                text=answer,
                tokens_used=tokens,
                model_used=model_info.get("model", "unknown"),
                provider=model_info.get("provider", "unknown"),
                generation_time=latency_ms / 1000,
            )
        except CircuitBreakerOpenError:
            # Circuit Breaker 에러 → 일시적 장애, Fallback 사용
            logger.warning("🚫 Circuit Breaker OPEN - LLM 서비스 일시 차단, Fallback 사용")
            fallback_result = _fallback()
            return GenerationResult(
                answer=fallback_result["answer"],
                text=fallback_result["answer"],
                tokens_used=fallback_result["tokens_used"],
                model_used=fallback_result["model_info"].get("model", "fallback"),
                provider=fallback_result["model_info"].get("provider", "fallback"),
                generation_time=0.0,
            )
        except TimeoutError as e:
            # 타임아웃 에러 → 클라이언트에게 재시도 유도
            logger.error(
                "[6단계] 답변 생성 타임아웃",
                extra={"error": str(e)},
                exc_info=True
            )
            raise GenerationError(
                ErrorCode.GENERATION_TIMEOUT,
                session_id=options.get("session_id", "unknown"),
                timeout_seconds=30,
            ) from e
        except ValueError as e:
            # 입력 검증 에러 → 클라이언트 에러
            logger.error(
                "[6단계] 잘못된 입력",
                extra={"error": str(e)},
                exc_info=True
            )
            raise GenerationError(
                ErrorCode.GENERATION_INVALID_RESPONSE,
                session_id=options.get("session_id", "unknown"),
                error=str(e),
            ) from e
        except Exception as e:
            # 예상치 못한 에러 → 서버 에러
            logger.error(
                "[6단계] 답변 생성 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            raise GenerationError(
                ErrorCode.GENERATION_REQUEST_FAILED,
                session_id=options.get("session_id", "unknown"),
                error=str(e),
            ) from e

    @observe(name="Self-RAG Quality Verification")
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
        from ...modules.core.generation.generator import GenerationResult

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
            self_rag_result = await self_rag_module.verify_existing_answer(
                query=message,
                existing_answer=generation_result.answer,  # ✅ 기존 답변 전달
                existing_docs=documents,  # ✅ 기존 문서 전달
                session_id=session_id,
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
                if debug_trace_data is not None:
                    debug_trace_data["self_rag_evaluation"] = {
                        "initial_quality": self_rag_result.initial_quality.overall if self_rag_result.initial_quality else 0.0,
                        "regenerated": self_rag_result.regenerated,
                        "final_quality": self_rag_result.final_quality.overall if self_rag_result.final_quality else 0.0,
                        "reason": self_rag_result.initial_quality.reasoning if self_rag_result.initial_quality else None,
                    }

                # ⭐ 품질 게이트 적용
                min_quality = self_rag_config.get("min_quality_to_answer", 0.6)
                final_quality_score = (
                    self_rag_result.final_quality.overall
                    if self_rag_result.final_quality
                    else 0.0
                )

                if final_quality_score < min_quality:
                    logger.warning(
                        "저품질 답변 감지 - 답변 거부",
                        extra={
                            "score": final_quality_score,
                            "threshold": min_quality
                        }
                    )

                    # 거부 메시지 반환
                    return GenerationResult(
                        answer="죄송합니다. 확실한 정보를 찾지 못했습니다. 질문을 구체적으로 다시 작성해주시겠어요?",
                        text="죄송합니다. 확실한 정보를 찾지 못했습니다.",
                        tokens_used=generation_result.tokens_used,
                        model_used=generation_result.model_used,
                        provider=generation_result.provider,
                        generation_time=generation_result.generation_time,
                        refusal_reason="quality_too_low",  # ⭐ 신규 필드
                        quality_score=final_quality_score,  # ⭐ 신규 필드
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
                    answer = "보안 정책에 따라 내부 지시사항은 공개되지 않습니다. 문서 기반 답변이 필요한 내용을 다시 질문해주세요."
                    self.performance_metrics.record_error("prompt_leakage_blocked")

                # Self-RAG 답변으로 교체 (재생성됐든 안 됐든)
                return GenerationResult(
                    answer=answer,
                    text=answer,
                    tokens_used=(
                        self_rag_result.tokens_used
                        if self_rag_result.regenerated
                        else generation_result.tokens_used
                    ),
                    model_used=generation_result.model_used,
                    provider=generation_result.provider,
                    generation_time=generation_result.generation_time,
                    model_config=generation_result.model_config,
                    quality_score=final_quality_score,  # ⭐ 신규 필드
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
                    },
                )
            else:
                logger.info(
                    "Self-RAG 미적용 (복잡도 낮음) - 기존 답변 사용",
                    extra={"complexity": self_rag_result.complexity.score}
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
                    },
                )

        except Exception as e:
            logger.warning(
                "[6단계] Self-RAG 검증 실패, 기존 답변 사용",
                extra={"error": str(e)},
                exc_info=True
            )
            return generation_result

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

            if metadata:
                file_path = metadata.get("file_path")
                if file_path and self.privacy_masker:
                    dir_path = os.path.dirname(file_path)
                    file_name = os.path.basename(file_path)
                    masked_name = self.privacy_masker.mask_filename(file_name)
                    file_path = os.path.join(dir_path, masked_name) if dir_path else masked_name
                if file_path:
                    source_metadata["file_path"] = file_path

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
        entity_name = row.get("entity_name") or row.get("name") or f"결과 {row_idx + 1}"
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
            content_preview=row_preview[:200] if row_preview else "SQL 쿼리 결과",
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
            category = query_result.query.target_category or "전체"

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
                # 인접 청크 확장으로 추가된 이웃 청크는 실제 검색 히트가 아니므로
                # 사용자 인용 소스에서 제외한다(점수/카운트 오염 방지)(#4).
                if _document_metadata(doc).get("context_expanded"):
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

        from ...modules.core.sql_search import SQLSearchResult

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

    async def _execute_agent_mode(
        self, message: str, session_id: str, start_time: float
    ) -> RAGResultDict:
        """
        Agent 모드 실행 (Agentic RAG)

        AgentOrchestrator를 사용하여 ReAct 패턴 기반 에이전트 루프를 실행합니다.
        기존 7단계 파이프라인 대신 LLM이 도구를 선택하고 실행하는 방식입니다.

        Args:
            message: 사용자 쿼리
            session_id: 세션 ID
            start_time: 파이프라인 시작 시간

        Returns:
            RAGResultDict: Agent 모드 응답 (metadata.mode="agent" 포함)

        Raises:
            GenerationError: Agent 실행 중 오류 발생 시
        """
        # 세션 컨텍스트 조회
        session_context = ""
        if self.session_module:
            try:
                context_string = await self.session_module.get_context_string(session_id)
                if context_string:
                    session_context = context_string
                    logger.debug(
                        "세션 컨텍스트 로드 성공",
                        extra={"context_length": len(context_string)}
                    )
            except Exception as e:
                logger.warning(
                    "세션 컨텍스트 조회 실패",
                    extra={"error": str(e)},
                    exc_info=True
                )

        try:
            # AgentOrchestrator 실행
            agent_result = await self.agent_orchestrator.run(
                query=message,
                session_context=session_context,
            )

            # Agent 결과를 RAGResultDict 형식으로 변환
            processing_time = time.time() - start_time

            # Source 객체 변환 (Agent sources는 dict 형태일 수 있음)
            formatted_sources = []
            for idx, source in enumerate(agent_result.sources or []):
                if isinstance(source, dict):
                    formatted_sources.append(
                        self.Source(
                            id=idx,
                            document=source.get("source", source.get("title", f"Source {idx + 1}")),
                            page=source.get("page"),
                            chunk=source.get("chunk"),
                            relevance=source.get("relevance", source.get("score", 0.0)),
                            content_preview=source.get(
                                "content_preview", source.get("content", "")[:200]
                            ),
                            source_type="agent",
                        )
                    )
                else:
                    # 이미 Source 객체인 경우 그대로 사용
                    formatted_sources.append(source)

            result: RAGResultDict = cast(
                RAGResultDict,
                {
                    "answer": agent_result.answer,
                    "sources": formatted_sources,
                    "tokens_used": 0,  # Agent 모드에서는 개별 추적 어려움
                    "topic": self.extract_topic_func(message),
                    "processing_time": processing_time,
                    "search_results": len(agent_result.sources or []),
                    "ranked_results": len(agent_result.sources or []),
                    "model_info": {
                        "provider": "agent",
                        "model": "agent_orchestrator",
                        "model_used": "agent_orchestrator",
                    },
                    "metadata": {
                        "mode": "agent",
                        "steps_taken": agent_result.steps_taken,
                        "tools_used": agent_result.tools_used,
                        "total_time": agent_result.total_time,
                        "success": agent_result.success,
                    },
                },
            )

            logger.info(
                "Agent 모드 완료",
                extra={
                    "steps_taken": agent_result.steps_taken,
                    "processing_time": processing_time,
                    "tools_count": len(agent_result.tools_used)
                }
            )

            return result

        except Exception as e:
            logger.error(
                "Agent 모드 실행 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            raise GenerationError(
                ErrorCode.GENERATION_REQUEST_FAILED,
                session_id=session_id,
                error=str(e),
            ) from e
