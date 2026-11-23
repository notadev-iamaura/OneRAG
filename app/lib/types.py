"""
타입 정의 파일
공통으로 사용되는 TypedDict 및 타입 정의
"""

from typing import Any, TypedDict


class LLMConfig(TypedDict, total=False):
    """LLM 설정 타입"""

    api_key: str
    model: str
    temperature: float
    max_tokens: int
    timeout: int
    default_provider: str
    auto_fallback: bool
    fallback_order: list[str]


class ModuleConfig(TypedDict, total=False):
    """모듈 설정 딕셔너리 타입"""

    retrieval: str  # 모듈 타입만 문자열로 (실제 객체는 런타임 타입)
    generation: str
    session: str
    query_router: str
    query_expansion: str
    self_rag: str


class SessionResult(TypedDict, total=False):
    """세션 처리 결과 타입"""

    success: bool
    session_id: str | None
    is_new: bool
    message: str | None
    validation_result: dict[str, str] | None


class StatsDict(TypedDict, total=False):
    """통계 딕셔너리 타입"""

    total_chats: int
    total_tokens: int
    average_latency: float
    error_rate: float
    errors: int


class SessionInfoDict(TypedDict, total=False):
    """세션 정보 딕셔너리 타입"""

    session_id: str
    message_count: int
    tokens_used: int
    processing_time: float
    model_info: dict[str, Any] | None
    timestamp: str


class RAGResultDict(TypedDict, total=False):
    """RAG 파이프라인 결과 딕셔너리 타입"""

    answer: str
    sources: list[dict[str, Any]]
    cited_sources: list[dict[str, Any]]
    grounding_status: str
    tokens_used: int
    topic: str
    processing_time: float
    search_results: int
    ranked_results: int
    model_info: dict[str, Any]
    routing_metadata: dict[str, Any] | None
    performance_metrics: dict[str, Any] | None


class HealthCheckDict(TypedDict, total=False):
    """헬스 체크 결과 타입"""

    status: str
    timestamp: float
    error: str | None
    retriever: bool | str | None
    reranker: bool | str | None
    cache: bool | str | None


class OrchestratorStatsDict(TypedDict, total=False):
    """오케스트레이터 통계 타입"""

    orchestrator: dict[str, Any]
    retriever: dict[str, Any] | None
    reranker: dict[str, Any] | None
    cache: dict[str, Any] | None
    query_expansion: dict[str, Any] | None
