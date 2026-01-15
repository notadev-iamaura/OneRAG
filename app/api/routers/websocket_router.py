"""
WebSocket 라우터

WebSocket 기반 실시간 RAG 스트리밍 채팅 엔드포인트를 제공합니다.

흐름:
1. 클라이언트가 WebSocket 연결 (session_id 필수)
2. 클라이언트가 ClientMessage 전송
3. 서버가 StreamStartEvent 전송
4. 서버가 ChatService.stream_rag_pipeline() 호출
5. 서버가 StreamTokenEvent, StreamSourcesEvent 반복 전송
6. 서버가 StreamEndEvent 전송

사용 예시:
    # 클라이언트 측
    ws = WebSocket("wss://host/chat-ws?session_id=my-session")
    ws.send(json.dumps({
        "type": "message",
        "message_id": "uuid",
        "content": "질문입니다",
        "session_id": "my-session"
    }))
    # 서버로부터 스트리밍 이벤트 수신
"""

import json
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.schemas.websocket import (
    ClientMessage,
    StreamEndEvent,
    StreamSourcesEvent,
    StreamStartEvent,
    StreamTokenEvent,
    WSStreamErrorEvent,
)
from app.api.services.websocket_manager import WebSocketManager
from app.lib.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)

# 전역 WebSocket 매니저
ws_manager = WebSocketManager()

# ChatService 의존성 주입용
_chat_service: Any = None


def set_chat_service(service: Any) -> None:
    """
    ChatService 의존성 주입

    애플리케이션 시작 시 ChatService 인스턴스를 주입합니다.

    Args:
        service: ChatService 인스턴스 (None으로 해제 가능)
    """
    global _chat_service
    _chat_service = service
    if service:
        logger.info("ChatService 주입 완료")
    else:
        logger.debug("ChatService 해제됨")


async def _send_error(
    websocket: WebSocket,
    message_id: str,
    error_code: str,
    message: str,
    solutions: list[str] | None = None,
) -> None:
    """
    에러 이벤트 전송 헬퍼

    Args:
        websocket: WebSocket 연결
        message_id: 메시지 ID
        error_code: 에러 코드
        message: 에러 메시지
        solutions: 해결 방법 목록
    """
    error_event = WSStreamErrorEvent(
        message_id=message_id,
        error_code=error_code,
        message=message,
        solutions=solutions or ["잠시 후 다시 시도해주세요."],
    )
    await websocket.send_json(error_event.model_dump())


@router.websocket("/chat-ws")
async def websocket_chat(
    websocket: WebSocket,
    session_id: str = Query(..., description="세션 ID"),
) -> None:
    """
    WebSocket 실시간 채팅 엔드포인트

    session_id를 쿼리 파라미터로 받아 WebSocket 연결을 수립하고,
    클라이언트 메시지를 받아 RAG 파이프라인 결과를 스트리밍합니다.

    Args:
        websocket: FastAPI WebSocket 객체
        session_id: 세션 식별자 (필수)

    WebSocket 프로토콜:
        1. 연결: wss://host/chat-ws?session_id={session_id}
        2. 클라이언트 → 서버: ClientMessage (JSON)
        3. 서버 → 클라이언트: StreamStartEvent, StreamTokenEvent, StreamSourcesEvent, StreamEndEvent
    """
    # WebSocket 연결 수락 및 등록
    await ws_manager.connect(session_id, websocket)

    logger.info(
        "WebSocket 연결 수립",
        session_id=session_id,
    )

    try:
        while True:
            # 클라이언트 메시지 수신
            try:
                raw_data = await websocket.receive_text()
            except WebSocketDisconnect:
                logger.info("WebSocket 연결 종료", session_id=session_id)
                break

            # JSON 파싱
            message_id = "unknown"
            try:
                data = json.loads(raw_data)
                message_id = data.get("message_id", "unknown")
            except json.JSONDecodeError as e:
                logger.warning(
                    "WebSocket 잘못된 JSON",
                    session_id=session_id,
                    error=str(e),
                )
                await _send_error(
                    websocket=websocket,
                    message_id=message_id,
                    error_code="WS-001-INVALID_JSON",
                    message="잘못된 JSON 형식입니다.",
                    solutions=["올바른 JSON 형식으로 메시지를 전송해주세요."],
                )
                continue

            # ClientMessage 검증
            try:
                client_message = ClientMessage.model_validate(data)
            except ValidationError as e:
                logger.warning(
                    "WebSocket 메시지 검증 실패",
                    session_id=session_id,
                    error=str(e),
                )
                await _send_error(
                    websocket=websocket,
                    message_id=message_id,
                    error_code="WS-002-VALIDATION_ERROR",
                    message="메시지 형식이 올바르지 않습니다.",
                    solutions=[
                        "type, message_id, content, session_id 필드를 확인해주세요.",
                        "content는 1자 이상 10000자 이하여야 합니다.",
                    ],
                )
                continue

            # ChatService 초기화 확인
            if _chat_service is None:
                logger.error(
                    "ChatService 미초기화",
                    session_id=session_id,
                )
                await _send_error(
                    websocket=websocket,
                    message_id=client_message.message_id,
                    error_code="WS-003-SERVICE_NOT_INITIALIZED",
                    message="채팅 서비스가 초기화되지 않았습니다.",
                    solutions=["서버 관리자에게 문의해주세요."],
                )
                continue

            # 스트리밍 처리
            await _process_streaming(
                websocket=websocket,
                client_message=client_message,
                session_id=session_id,
            )

    except Exception as e:
        logger.error(
            "WebSocket 처리 중 예외 발생",
            session_id=session_id,
            error=str(e),
            exc_info=True,
        )
    finally:
        # 연결 해제
        ws_manager.disconnect(session_id)
        logger.info("WebSocket 연결 해제", session_id=session_id)


async def _process_streaming(
    websocket: WebSocket,
    client_message: ClientMessage,
    session_id: str,
) -> None:
    """
    스트리밍 처리 로직

    ChatService.stream_rag_pipeline()을 호출하고 결과를 WebSocket으로 전송합니다.

    Args:
        websocket: WebSocket 연결
        client_message: 클라이언트 메시지
        session_id: 세션 ID
    """
    message_id = client_message.message_id
    start_time = time.time()
    token_index = 0
    sources: list[dict[str, Any]] = []

    try:
        # 1. StreamStartEvent 전송
        start_event = StreamStartEvent(
            message_id=message_id,
            session_id=session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),  # noqa: UP017
        )
        await websocket.send_json(start_event.model_dump())

        logger.debug(
            "스트리밍 시작",
            message_id=message_id,
            session_id=session_id,
        )

        # 2. RAG 파이프라인 스트리밍 호출
        async for event in _chat_service.stream_rag_pipeline(
            message=client_message.content,
            session_id=session_id,
            options={},
        ):
            event_type = event.get("event")

            if event_type == "metadata":
                # 메타데이터는 내부 처리용 (클라이언트에 직접 전송하지 않음)
                metadata = event.get("data", {})
                logger.debug(
                    "스트리밍 메타데이터",
                    message_id=message_id,
                    search_results=metadata.get("search_results"),
                )

            elif event_type == "chunk":
                # 3. StreamTokenEvent 전송
                token = event.get("data", "")
                token_event = StreamTokenEvent(
                    message_id=message_id,
                    token=token,
                    index=token_index,
                )
                await websocket.send_json(token_event.model_dump())
                token_index += 1

            elif event_type == "done":
                # done 이벤트에서 sources 추출
                done_data = event.get("data", {})
                sources = done_data.get("sources", [])

            elif event_type == "error":
                # 스트리밍 중 에러 발생
                await _send_error(
                    websocket=websocket,
                    message_id=message_id,
                    error_code=event.get("error_code", "GEN-999"),
                    message=event.get("message", "스트리밍 중 오류가 발생했습니다."),
                )
                return

        # 4. StreamSourcesEvent 전송
        sources_event = StreamSourcesEvent(
            message_id=message_id,
            sources=sources,
        )
        await websocket.send_json(sources_event.model_dump())

        # 5. StreamEndEvent 전송
        processing_time_ms = int((time.time() - start_time) * 1000)
        end_event = StreamEndEvent(
            message_id=message_id,
            total_tokens=token_index,
            processing_time_ms=processing_time_ms,
        )
        await websocket.send_json(end_event.model_dump())

        logger.info(
            "스트리밍 완료",
            message_id=message_id,
            session_id=session_id,
            total_tokens=token_index,
            processing_time_ms=processing_time_ms,
        )

    except WebSocketDisconnect:
        logger.info(
            "스트리밍 중 WebSocket 연결 종료",
            message_id=message_id,
            session_id=session_id,
        )
        raise

    except Exception as e:
        logger.error(
            "스트리밍 처리 중 예외 발생",
            message_id=message_id,
            session_id=session_id,
            error=str(e),
            exc_info=True,
        )
        await _send_error(
            websocket=websocket,
            message_id=message_id,
            error_code="WS-999-INTERNAL_ERROR",
            message="스트리밍 처리 중 오류가 발생했습니다.",
            solutions=["잠시 후 다시 시도해주세요.", "문제가 지속되면 관리자에게 문의해주세요."],
        )
