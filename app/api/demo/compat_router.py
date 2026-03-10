"""
프론트엔드 호환 채팅 API 라우터

기존 demo_router의 세션 기반 채팅을 프론트엔드 ChatAPIResponse 형식으로 변환합니다.

엔드포인트:
- POST /api/chat                          프론트엔드 호환 채팅 (스키마 변환 + 히스토리 기록)
- POST /api/chat/stream                   프론트엔드 호환 SSE 스트리밍 (키 변환 + 메타 보강)
- POST /api/chat/session                  세션 생성
- GET  /api/chat/history/{session_id}     인메모리 히스토리 조회
- GET  /api/chat/session/{session_id}/info 세션 메타데이터 조회

의존성:
- demo_router: _get_manager(), _get_pipeline(), limiter 공유
- ErrorCode: 에러 코드 정의
"""

import json
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.lib.errors.codes import ErrorCode
from app.lib.logger import get_logger

from .demo_router import (
    RATE_LIMIT_CHAT,
    RATE_LIMIT_READ,
    RATE_LIMIT_SESSION,
    _get_manager,
    _get_pipeline,
    limiter,
)

logger = get_logger(__name__)

# =============================================================================
# 라우터 설정
# =============================================================================

compat_router = APIRouter(prefix="/api", tags=["Compat"])

# 인메모리 채팅 히스토리 (세션별 질문/답변 기록)
_chat_history: dict[str, list[dict[str, str]]] = {}

# 히스토리 크기 제한 — 세션당 최대 메시지 수 (메모리 누수 방지)
_MAX_HISTORY_PER_SESSION = 100


def cleanup_session_history(session_id: str) -> None:
    """세션 삭제 시 인메모리 히스토리 정리 (메모리 누수 방지)

    demo_router.py의 delete_session 엔드포인트에서 호출됩니다.
    TTL/LRU 퇴거 시에도 DemoSessionManager 콜백을 통해 호출됩니다.
    """
    _chat_history.pop(session_id, None)


# =============================================================================
# 요청/응답 스키마
# =============================================================================


class CompatChatRequest(BaseModel):
    """프론트엔드 호환 채팅 요청"""

    message: str = Field(..., min_length=1, max_length=1000)
    session_id: str = Field(..., min_length=1)


class CompatSource(BaseModel):
    """프론트엔드 호환 소스 정보"""

    id: int
    document: str
    content_preview: str
    relevance: float


class CompatChatResponse(BaseModel):
    """프론트엔드 호환 채팅 응답 (ChatAPIResponse 형식)"""

    answer: str
    session_id: str
    sources: list[CompatSource]
    processing_time: float
    tokens_used: int
    timestamp: str


# =============================================================================
# 엔드포인트
# =============================================================================


@compat_router.post("/chat", response_model=CompatChatResponse)
@limiter.limit(RATE_LIMIT_CHAT)
async def compat_chat(
    request: Request, body: CompatChatRequest
) -> CompatChatResponse:
    """
    프론트엔드 호환 채팅 엔드포인트

    프론트엔드 {message, session_id} 요청을 내부 pipeline.query()로 변환하고,
    ChatAPIResponse 형식으로 응답합니다. 채팅 히스토리도 자동 기록됩니다.
    """
    manager = _get_manager()
    pipeline = _get_pipeline()

    # 세션 존재 확인
    session = await manager.get_session(body.session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorCode.DEMO_002.value,
        )

    # 일일 API 예산 확인 (임베딩 검색 1 + LLM 생성 1 = 2회)
    if not await manager.check_and_increment_api_calls(count=2):
        raise HTTPException(
            status_code=429,
            detail=ErrorCode.DEMO_008.value,
        )

    # 파이프라인 질의 및 처리 시간 측정
    start_time = time.time()
    try:
        result = await pipeline.query(body.session_id, question=body.message)
    except ValueError:
        raise HTTPException(status_code=404, detail=ErrorCode.DEMO_002.value)

    processing_time = time.time() - start_time

    # sources 변환: [{content, source}] → [{id, document, content_preview, relevance}]
    sources = [
        CompatSource(
            id=i,
            document=src.get("source", ""),
            content_preview=src.get("content", "")[:200],
            relevance=0.8,
        )
        for i, src in enumerate(result.get("sources", []))
    ]

    answer = result.get("answer", "")

    # 인메모리 히스토리에 질문/답변 기록 (크기 제한 적용)
    history = _chat_history.setdefault(body.session_id, [])
    history.append({
        "question": body.message,
        "answer": answer,
    })
    # 최대 크기 초과 시 오래된 항목 제거
    if len(history) > _MAX_HISTORY_PER_SESSION:
        _chat_history[body.session_id] = history[-_MAX_HISTORY_PER_SESSION:]

    return CompatChatResponse(
        answer=answer,
        session_id=body.session_id,
        sources=sources,
        processing_time=processing_time,
        tokens_used=0,
        timestamp=datetime.now(tz=UTC).isoformat(),
    )


@compat_router.post("/chat/stream")
@limiter.limit(RATE_LIMIT_CHAT)
async def compat_chat_stream(
    request: Request, body: CompatChatRequest
) -> StreamingResponse:
    """
    프론트엔드 호환 SSE 스트리밍 엔드포인트

    pipeline.stream_query() 이벤트를 프론트엔드 형식으로 변환합니다.
    - chunk 이벤트: "token" 키 → "data" 키로 변환
    - done 이벤트: message_id, processing_time, tokens_used, sources 추가

    Note: 스트리밍 응답은 _chat_history에 기록하지 않습니다.
    프론트엔드가 스트리밍 완료 후 POST /api/chat 으로 별도 저장하거나,
    자체 로컬 상태에서 히스토리를 관리합니다.
    """
    manager = _get_manager()
    pipeline = _get_pipeline()

    # 세션 존재 확인 (스트리밍 시작 전 검증)
    session = await manager.get_session(body.session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorCode.DEMO_002.value,
        )

    # 일일 API 예산 확인
    if not await manager.check_and_increment_api_calls(count=2):
        raise HTTPException(
            status_code=429,
            detail=ErrorCode.DEMO_008.value,
        )

    # 스트리밍 시작 시간 및 메시지 ID 생성
    start_time = time.time()
    message_id = str(uuid.uuid4())

    async def event_generator() -> AsyncGenerator[str, None]:
        """SSE 이벤트 생성기 — 프론트엔드 호환 키 변환 적용"""
        # metadata에서 sources를 캡처하여 done 이벤트에 포함
        captured_sources: list[dict[str, str]] = []

        try:
            async for event in pipeline.stream_query(
                body.session_id, body.message
            ):
                event_type = event["event"]
                data = event["data"]

                if event_type == "metadata":
                    # sources 캡처 (done 이벤트에 포함하기 위해)
                    captured_sources.extend(data.get("sources", []))
                    yield _format_sse(event_type, data)

                elif event_type == "chunk":
                    # "token" → "data" 키 변환
                    transformed = {
                        "data": data.get("token", ""),
                        "chunk_index": data.get("chunk_index", 0),
                    }
                    yield _format_sse(event_type, transformed)

                elif event_type == "done":
                    # done 이벤트 보강: message_id, processing_time, sources 추가
                    enriched = {
                        **data,
                        "message_id": message_id,
                        "processing_time": time.time() - start_time,
                        "tokens_used": 0,
                        "sources": captured_sources,
                    }
                    yield _format_sse(event_type, enriched)

                else:
                    yield _format_sse(event_type, data)

        except Exception as e:
            logger.error(f"호환 스트리밍 오류: {e}", exc_info=True)
            error_data = {"error": ErrorCode.DEMO_005.value}
            yield _format_sse("error", error_data)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_sse(event_type: str, data: dict[str, Any]) -> str:
    """SSE 이벤트 포맷팅 — event: {type}\ndata: {json}\n\n"""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# =============================================================================
# 세션 관리 엔드포인트
# =============================================================================


@compat_router.post("/chat/session")
@limiter.limit(RATE_LIMIT_SESSION)
async def create_compat_session(request: Request) -> dict[str, Any]:
    """
    프론트엔드 호환 세션 생성

    DemoSessionManager.create_session()을 래핑하여
    프론트엔드가 필요한 최소 정보를 반환합니다.
    """
    manager = _get_manager()

    try:
        session = await manager.create_session()
    except Exception as e:
        logger.error(f"세션 생성 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=ErrorCode.DEMO_005.value,
        )

    return {
        "session_id": session.session_id,
        "created_at": datetime.fromtimestamp(
            session.created_at, tz=UTC
        ).isoformat(),
        "message_count": 0,
        "last_activity": datetime.fromtimestamp(
            session.last_accessed, tz=UTC
        ).isoformat(),
    }


# =============================================================================
# 히스토리 조회 엔드포인트
# =============================================================================


@compat_router.get("/chat/history/{session_id}")
@limiter.limit(RATE_LIMIT_READ)
async def get_chat_history(
    request: Request,
    session_id: str = Path(..., min_length=1, max_length=200),
) -> dict[str, Any]:
    """
    인메모리 채팅 히스토리 조회

    세션 존재 여부를 확인한 뒤, 해당 세션의 질문/답변 기록을 반환합니다.
    """
    manager = _get_manager()

    # 세션 존재 확인
    session = await manager.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorCode.DEMO_002.value,
        )

    entries = _chat_history.get(session_id, [])

    return {
        "session_id": session_id,
        "messages": entries,
    }


# =============================================================================
# 세션 정보 조회 엔드포인트
# =============================================================================


@compat_router.get("/chat/session/{session_id}/info")
@limiter.limit(RATE_LIMIT_READ)
async def get_session_info(
    request: Request,
    session_id: str = Path(..., min_length=1, max_length=200),
) -> dict[str, Any]:
    """
    세션 메타데이터 조회

    DemoSessionManager.get_session_info()를 호출하여
    세션 생성 시각, 메시지 수, 마지막 활동 시각을 반환합니다.
    """
    manager = _get_manager()

    info = await manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorCode.DEMO_002.value,
        )

    # message_count를 실제 히스토리 길이로 보정
    # (session_manager는 _chat_history에 접근할 수 없으므로 라우터에서 보정)
    info["message_count"] = len(_chat_history.get(session_id, []))

    return info
