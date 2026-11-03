"""RAG 파이프라인 단계 간 전달 모델과 성능 트래커 (rag_pipeline.py에서 분리)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ....lib.logger import get_logger
from ....lib.types import RAGResultDict

logger = get_logger(__name__)

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
                session_context="User: Hello
    Bot: Hello! How can I help you?",
                expanded_query="expanded query with synonyms and related terms",
                original_query="original user query",
                expanded_queries=["query variant A", "query variant B", ...],
                query_weights=[1.0, 0.8, 0.6, 0.4, 0.2]
            )
    """

    session_context: str | None
    expanded_query: str
    original_query: str
    expanded_queries: list[str] = field(default_factory=list)  # Multi-Query RRF용
    query_weights: list[float] = field(default_factory=list)  # 쿼리 가중치
    # 멀티턴 anchor soft boost(GAP B)용 직전 인용 문서. 기본 OFF면 항상 빈 리스트.
    anchor_sources: list[dict[str, Any]] = field(default_factory=list)


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

    def __init__(self) -> None:
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
