"""
Chat API Schemas - Pydantic 데이터 검증 모델

Phase 3.1: chat.py에서 추출한 검증된 스키마들
기존 코드 기반: app/api/chat.py (L64-158)

⚠️ 주의: 이 코드는 기존 검증된 스키마를 재사용합니다.
"""

from typing import Any

from pydantic import BaseModel, Field, validator


class ChatRequest(BaseModel):
    """채팅 요청 모델"""

    message: str = Field(..., min_length=1, max_length=1000, description="사용자 메시지")
    session_id: str | None = Field(None, description="세션 ID")
    stream: bool = Field(False, description="스트리밍 응답 여부")
    use_agent: bool = Field(False, description="Agent 모드 사용 여부 (Agentic RAG)")
    options: dict[str, Any] | None = Field(default_factory=dict, description="추가 옵션")
    enable_debug_trace: bool = Field(False, description="디버깅 추적 활성화")

    @validator("message")
    def validate_message(cls, v):
        if not v or not v.strip():
            raise ValueError("Message cannot be empty")
        return v.strip()


class Source(BaseModel):
    """소스 정보 모델 - 확장된 메타데이터 지원"""

    id: int
    document: str
    page: int | None = None
    chunk: int | None = None
    relevance: float
    content_preview: str

    # 소스 타입 구분 (rag: 벡터/BM25 검색, sql: SQL 메타데이터 검색)
    source_type: str = "rag"  # "rag" | "sql"

    # SQL 검색 관련 필드 (source_type="sql"인 경우)
    sql_query: str | None = None  # 실행된 SQL 쿼리
    sql_result_summary: str | None = None  # SQL 결과 요약

    # 확장된 메타데이터 필드들
    file_type: str | None = None
    file_path: str | None = None
    file_size: int | None = None
    total_chunks: int | None = None
    file_hash: str | None = None
    load_timestamp: float | None = None

    # 파일별 특수 메타데이터
    sheet_name: str | None = None  # Excel 시트명
    format: str | None = None  # 파일 포맷 정보
    json_type: str | None = None  # JSON 타입
    item_index: int | None = None  # JSON 아이템 인덱스

    # 리랭킹 관련 메타데이터
    rerank_method: str | None = None
    original_score: float | None = None

    # 추가 메타데이터 (동적 필드)
    additional_metadata: dict[str, Any] | None = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """채팅 응답 모델"""

    answer: str
    sources: list[Source]
    session_id: str
    message_id: str  # 평가 시스템을 위한 메시지 고유 ID
    processing_time: float
    tokens_used: int
    timestamp: str
    model_info: dict[str, Any] | None = None
    can_evaluate: bool = True  # 평가 가능 여부
    self_rag_metadata: dict[str, Any] | None = None  # Self-RAG 메타데이터

    # ⭐ Self-RAG 품질 게이트 메타데이터 (Phase 3.1)
    metadata: dict[str, Any] = Field(default_factory=dict, description="품질 점수 및 추가 메타데이터")


class SessionCreateRequest(BaseModel):
    """세션 생성 요청 모델"""

    metadata: dict[str, Any] | None = Field(default_factory=dict)


class SessionResponse(BaseModel):
    """세션 응답 모델"""

    session_id: str
    message: str
    timestamp: str


class ChatHistoryResponse(BaseModel):
    """채팅 히스토리 응답 모델"""

    session_id: str
    messages: list[dict[str, Any]]
    total_messages: int
    limit: int
    offset: int
    has_more: bool


class SessionInfoResponse(BaseModel):
    """세션 상세 정보 응답 모델"""

    session_id: str
    messageCount: int
    tokensUsed: int
    processingTime: float
    modelInfo: dict[str, Any] | None = None
    timestamp: str


class StatsResponse(BaseModel):
    """통계 응답 모델"""

    chat: dict[str, Any]
    session: dict[str, Any]
    timestamp: str
