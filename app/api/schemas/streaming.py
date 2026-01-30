"""
스트리밍 API 스키마 정의

SSE(Server-Sent Events) 기반 스트리밍 응답을 위한 Pydantic 모델.
실시간 채팅 응답 스트리밍에 사용되며, 청크 단위로 응답을 전송합니다.

주요 모델 (5개):
- StreamChatRequest: 스트리밍 채팅 요청
- StreamMetadataEvent: 세션/검색 메타데이터 이벤트
- StreamChunkEvent: 텍스트 청크 이벤트
- StreamDoneEvent: 스트리밍 완료 이벤트
- StreamErrorEvent: 에러 이벤트

SSE 형식: data: {json}\n\n
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class StreamChatRequest(BaseModel):
    """
    스트리밍 채팅 요청 모델

    SSE 스트리밍 방식으로 채팅 응답을 받기 위한 요청 스키마.
    기존 ChatRequest와 유사하나 스트리밍 전용으로 최적화됨.

    Attributes:
        message: 사용자 질문 (1-10000자)
        session_id: 세션 식별자 (없으면 서버에서 생성)
        options: 추가 옵션 (temperature, max_tokens 등)
    """

    message: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="사용자 메시지 (1-10000자)",
    )
    session_id: str | None = Field(
        None,
        description="세션 ID (없으면 새로 생성)",
    )
    options: dict[str, Any] | None = Field(
        None,
        description="추가 옵션 (temperature, max_tokens 등)",
    )


class StreamMetadataEvent(BaseModel):
    """
    SSE 메타데이터 이벤트

    스트리밍 응답 시작 시 전송되는 세션/검색 메타정보.
    chat_service에서 dict로 전송하는 메타데이터의 스키마 정의.

    SSE 형식 예시:
        data: {"event":"metadata","session_id":"...","search_results":5}

    Attributes:
        event: 이벤트 타입 (항상 "metadata")
        session_id: 세션 식별자
        search_results: 검색된 문서 수 (0 이상)
        reranking_applied: 리랭킹 적용 여부
        query_expansion: 쿼리 확장 결과 (선택적)
        timestamp: 이벤트 생성 시간 ISO 8601 형식 (선택적)
    """

    event: Literal["metadata"] = "metadata"
    session_id: str = Field(..., description="세션 ID")
    search_results: int = Field(..., ge=0, description="검색된 문서 수")
    reranking_applied: bool = Field(False, description="리랭킹 적용 여부")
    query_expansion: str | None = Field(None, description="쿼리 확장 결과")
    timestamp: str | None = Field(default=None, description="이벤트 생성 시간 (ISO 8601)")


class StreamChunkEvent(BaseModel):
    """
    스트리밍 청크 이벤트 (SSE data)

    LLM에서 생성된 텍스트를 청크 단위로 전송하는 이벤트.
    클라이언트는 청크를 순서대로 조합하여 전체 응답을 구성함.

    SSE 형식 예시:
        data: {"event":"chunk","data":"안녕","chunk_index":0}

    Attributes:
        event: 이벤트 타입 (항상 "chunk")
        data: 텍스트 청크
        chunk_index: 청크 순서 인덱스 (0부터 시작)
    """

    event: Literal["chunk"] = "chunk"
    data: str = Field(
        ...,
        description="텍스트 청크",
    )
    chunk_index: int = Field(
        ...,
        ge=0,
        description="청크 인덱스 (0부터 시작)",
    )


class StreamDoneEvent(BaseModel):
    """
    스트리밍 완료 이벤트

    모든 청크 전송이 완료되었음을 알리는 이벤트.
    메타데이터와 함께 전송되어 클라이언트가 최종 처리를 수행할 수 있음.

    SSE 형식 예시:
        data: {"event":"done","session_id":"...","message_id":"...","total_chunks":10}

    Attributes:
        event: 이벤트 타입 (항상 "done")
        session_id: 세션 식별자
        message_id: 메시지 고유 ID (평가/피드백용)
        total_chunks: 전송된 총 청크 수
        tokens_used: 사용된 토큰 수
        processing_time: 전체 처리 시간 (초)
        sources: 참조된 문서 소스 목록
    """

    event: Literal["done"] = "done"
    session_id: str = Field(
        ...,
        description="세션 ID",
    )
    message_id: str = Field(
        ...,
        description="메시지 ID (평가 시스템용)",
    )
    total_chunks: int = Field(
        ...,
        ge=0,
        description="총 청크 수",
    )
    tokens_used: int = Field(
        0,
        ge=0,
        description="사용된 토큰 수",
    )
    processing_time: float = Field(
        0.0,
        ge=0.0,
        description="처리 시간 (초)",
    )
    sources: list[Any] = Field(
        default_factory=list,
        description="참조 소스 목록",
    )


class StreamErrorEvent(BaseModel):
    """
    스트리밍 에러 이벤트

    스트리밍 중 에러 발생 시 전송되는 이벤트.
    에러 코드와 사용자 친화적 메시지를 포함함.

    SSE 형식 예시:
        data: {"event":"error","error_code":"GEN-001","message":"..."}

    Attributes:
        event: 이벤트 타입 (항상 "error")
        error_code: 에러 코드 (예: GEN-001, SEARCH-003)
        message: 사용자 친화적 에러 메시지
        suggestion: 해결 방법 제안 (선택적)
    """

    event: Literal["error"] = "error"
    error_code: str = Field(
        ...,
        description="에러 코드 (예: GEN-001, SEARCH-003)",
    )
    message: str = Field(
        ...,
        description="사용자 친화적 에러 메시지",
    )
    suggestion: str | None = Field(
        None,
        description="해결 방법 제안",
    )
