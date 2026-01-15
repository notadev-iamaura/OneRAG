"""
WebSocket 메시지 스키마 정의

WebSocket 기반 실시간 스트리밍 통신을 위한 Pydantic 모델.
양방향 통신 프로토콜을 정의하며, 토큰 단위 스트리밍에 최적화되어 있습니다.

클라이언트 → 서버 메시지:
- ClientMessage: 사용자 질문 메시지

서버 → 클라이언트 이벤트:
- StreamStartEvent: 스트리밍 시작 알림
- StreamTokenEvent: 토큰 단위 스트리밍
- StreamSourcesEvent: 검색 소스 전송
- StreamEndEvent: 스트리밍 종료 알림
- WSStreamErrorEvent: 에러 이벤트

WebSocket 형식: JSON 직렬화된 메시지
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ClientMessage(BaseModel):
    """
    클라이언트 → 서버 메시지 모델

    WebSocket을 통해 클라이언트가 서버로 전송하는 메시지 스키마.
    사용자 질문과 세션 정보를 포함합니다.

    Attributes:
        type: 메시지 타입 (항상 "message")
        message_id: 메시지 고유 식별자 (클라이언트 생성)
        content: 사용자 질문 내용 (1-10000자)
        session_id: 세션 식별자
    """

    type: Literal["message"] = Field(
        default="message",
        description="메시지 타입 (항상 'message')",
    )
    message_id: str = Field(
        ...,
        description="메시지 고유 식별자",
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="사용자 질문 내용 (1-10000자)",
    )
    session_id: str = Field(
        ...,
        description="세션 식별자",
    )


class StreamStartEvent(BaseModel):
    """
    스트리밍 시작 이벤트 모델

    서버에서 스트리밍 응답을 시작할 때 전송하는 이벤트.
    클라이언트가 스트리밍 수신 준비를 할 수 있도록 알립니다.

    Attributes:
        type: 이벤트 타입 (항상 "stream_start")
        message_id: 메시지 고유 식별자
        session_id: 세션 식별자
        timestamp: 스트리밍 시작 시각 (ISO 8601 형식)
    """

    type: Literal["stream_start"] = Field(
        default="stream_start",
        description="이벤트 타입 (항상 'stream_start')",
    )
    message_id: str = Field(
        ...,
        description="메시지 고유 식별자",
    )
    session_id: str = Field(
        ...,
        description="세션 식별자",
    )
    timestamp: str = Field(
        ...,
        description="스트리밍 시작 시각 (ISO 8601 형식)",
    )


class StreamTokenEvent(BaseModel):
    """
    토큰 스트리밍 이벤트 모델

    LLM에서 생성된 텍스트를 토큰 단위로 전송하는 이벤트.
    클라이언트는 토큰을 순서대로 조합하여 전체 응답을 구성합니다.

    Attributes:
        type: 이벤트 타입 (항상 "stream_token")
        message_id: 메시지 고유 식별자
        token: 텍스트 토큰 (빈 문자열 가능)
        index: 토큰 순서 인덱스 (0부터 시작)
    """

    type: Literal["stream_token"] = Field(
        default="stream_token",
        description="이벤트 타입 (항상 'stream_token')",
    )
    message_id: str = Field(
        ...,
        description="메시지 고유 식별자",
    )
    token: str = Field(
        ...,
        description="텍스트 토큰",
    )
    index: int = Field(
        ...,
        ge=0,
        description="토큰 인덱스 (0부터 시작)",
    )


class StreamSourcesEvent(BaseModel):
    """
    검색 소스 전송 이벤트 모델

    RAG 검색 결과로 찾은 문서 소스를 전송하는 이벤트.
    응답 생성에 참조된 문서 정보를 클라이언트에 제공합니다.

    Attributes:
        type: 이벤트 타입 (항상 "stream_sources")
        message_id: 메시지 고유 식별자
        sources: 검색 소스 목록 (딕셔너리 리스트)
    """

    type: Literal["stream_sources"] = Field(
        default="stream_sources",
        description="이벤트 타입 (항상 'stream_sources')",
    )
    message_id: str = Field(
        ...,
        description="메시지 고유 식별자",
    )
    sources: list[dict[str, Any]] = Field(
        ...,
        description="검색 소스 목록",
    )


class StreamEndEvent(BaseModel):
    """
    스트리밍 종료 이벤트 모델

    모든 토큰 전송이 완료되었음을 알리는 이벤트.
    처리 통계 정보를 포함하여 클라이언트가 최종 처리를 수행할 수 있게 합니다.

    Attributes:
        type: 이벤트 타입 (항상 "stream_end")
        message_id: 메시지 고유 식별자
        total_tokens: 전송된 총 토큰 수
        processing_time_ms: 전체 처리 시간 (밀리초)
    """

    type: Literal["stream_end"] = Field(
        default="stream_end",
        description="이벤트 타입 (항상 'stream_end')",
    )
    message_id: str = Field(
        ...,
        description="메시지 고유 식별자",
    )
    total_tokens: int = Field(
        ...,
        ge=0,
        description="총 토큰 수",
    )
    processing_time_ms: int = Field(
        ...,
        ge=0,
        description="처리 시간 (밀리초)",
    )


class WSStreamErrorEvent(BaseModel):
    """
    WebSocket 스트리밍 에러 이벤트 모델

    스트리밍 중 에러 발생 시 전송되는 이벤트.
    에러 코드, 메시지, 해결 방법을 포함합니다.

    Note:
        기존 SSE StreamErrorEvent와 구분하기 위해 WS 접두사 사용

    Attributes:
        type: 이벤트 타입 (항상 "stream_error")
        message_id: 메시지 고유 식별자
        error_code: 에러 코드 (예: GEN-001, SEARCH-003)
        message: 사용자 친화적 에러 메시지
        solutions: 해결 방법 목록
    """

    type: Literal["stream_error"] = Field(
        default="stream_error",
        description="이벤트 타입 (항상 'stream_error')",
    )
    message_id: str = Field(
        ...,
        description="메시지 고유 식별자",
    )
    error_code: str = Field(
        ...,
        description="에러 코드 (예: GEN-001, SEARCH-003)",
    )
    message: str = Field(
        ...,
        description="사용자 친화적 에러 메시지",
    )
    solutions: list[str] = Field(
        ...,
        description="해결 방법 목록",
    )
