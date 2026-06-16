"""
WebSocket 라우터

WebSocket 기반 실시간 RAG 스트리밍 채팅 엔드포인트를 제공합니다.

흐름:
1. 클라이언트가 WebSocket 연결 (session_id 필수)
2. 클라이언트가 ClientMessage 전송
3. 서버가 ChatService.stream_rag_pipeline() 호출
4. 파이프라인 metadata 이벤트 수신 시 서버 확정 session_id로 StreamStartEvent 전송
   (비-UUID4 클라이언트 ID는 세션 서비스가 새 UUID4로 교체할 수 있으므로,
    클라이언트가 후속 메시지에 사용할 확정 ID를 stream_start로 회신한다)
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
    # stream_start.session_id(서버 확정 ID)를 이후 메시지에 사용
"""

import json
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
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
from app.lib.auth import get_api_key_auth, verify_websocket_session_token
from app.lib.errors import get_error_message, get_error_solutions
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


def _resolve_websocket_language(websocket: WebSocket) -> str:
    """WebSocket 핸드셰이크의 Accept-Language 헤더에서 에러 메시지 언어를 결정한다.

    양언어 에러 카탈로그(app.lib.errors)는 "ko"/"en"만 지원한다. 헤더가 영어를
    우선하면 "en"을, 그 외(미지정 포함)는 "ko"를 반환한다 → 한국어 기본(회귀 0).

    Args:
        websocket: FastAPI WebSocket 객체

    Returns:
        "ko" 또는 "en"
    """
    accept_language = (websocket.headers.get("accept-language") or "").lower()
    # 가장 단순·견고한 규칙: 'en'이 'ko'보다 먼저 나오거나 ko가 없으면 영어로 본다.
    en_idx = accept_language.find("en")
    ko_idx = accept_language.find("ko")
    if en_idx != -1 and (ko_idx == -1 or en_idx < ko_idx):
        return "en"
    return "ko"


def _extract_websocket_api_key(websocket: WebSocket) -> str | None:
    """Extract API key from header or OpenAI-style bearer token."""
    header_key = websocket.headers.get("x-api-key")
    if header_key:
        return header_key

    authorization = websocket.headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()

    return None


async def _authenticate_websocket(
    websocket: WebSocket,
    session_id: str,
    ws_token: str | None,
) -> bool:
    """Validate WebSocket auth with the existing FASTAPI_AUTH_KEY singleton."""
    try:
        auth = get_api_key_auth()
    except RuntimeError:
        logger.critical("WebSocket 인증 설정 오류: FASTAPI_AUTH_KEY 누락")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return False

    if not auth.api_key:
        logger.warning("FASTAPI_AUTH_KEY 미설정으로 WebSocket 인증 스킵")
        return True

    supplied_key = _extract_websocket_api_key(websocket)
    if supplied_key and secrets.compare_digest(supplied_key, auth.api_key):
        return True

    if verify_websocket_session_token(session_id, ws_token, auth.api_key):
        return True

    logger.warning("WebSocket 인증 실패: API Key 또는 세션 토큰 없음/불일치")
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    return False


async def _send_stream_start(
    websocket: WebSocket,
    message_id: str,
    session_id: str,
) -> None:
    """
    StreamStartEvent 전송 헬퍼

    Args:
        websocket: WebSocket 연결
        message_id: 메시지 ID
        session_id: 클라이언트에 회신할 세션 ID (서버 확정 ID 우선)
    """
    start_event = StreamStartEvent(
        message_id=message_id,
        session_id=session_id,
        timestamp=datetime.now(timezone.utc).isoformat(),  # noqa: UP017
    )
    await websocket.send_json(start_event.model_dump())


async def _send_error(
    websocket: WebSocket,
    message_id: str,
    error_code: str,
    message: str | None = None,
    solutions: list[str] | None = None,
    lang: str = "ko",
) -> None:
    """
    에러 이벤트 전송 헬퍼

    message/solutions가 명시되지 않으면 양언어 에러 카탈로그(app.lib.errors)에서
    error_code를 키로 lang별 메시지/해결방법을 조회한다. 카탈로그에 없는 코드
    (예: 파이프라인에서 포워딩된 코드)는 명시값 또는 한국어 폴백을 사용한다 → 회귀 0.

    Args:
        websocket: WebSocket 연결
        message_id: 메시지 ID
        error_code: 에러 코드 (와이어 계약 그대로, 카탈로그 키로도 사용)
        message: 에러 메시지 명시값(None이면 카탈로그 조회)
        solutions: 해결 방법 목록 명시값(None이면 카탈로그 조회)
        lang: 메시지 언어("ko"|"en", 기본 ko → 회귀 0)
    """
    resolved_message = message
    resolved_solutions = solutions

    # 명시값이 없으면 카탈로그에서 lang별 메시지/해결방법을 조회(양언어 자동 전환).
    # 카탈로그에 없는 코드는 KeyError → 폴백 유지(기존 동작 보존).
    if resolved_message is None:
        try:
            resolved_message = get_error_message(error_code, lang=lang)
        except KeyError:
            resolved_message = "스트리밍 처리 중 오류가 발생했습니다."
    if resolved_solutions is None:
        try:
            resolved_solutions = get_error_solutions(error_code, lang=lang)
        except KeyError:
            resolved_solutions = None

    error_event = WSStreamErrorEvent(
        message_id=message_id,
        error_code=error_code,
        message=resolved_message,
        solutions=resolved_solutions or ["잠시 후 다시 시도해주세요."],
    )
    await websocket.send_json(error_event.model_dump())


@router.websocket("/chat-ws")
async def websocket_chat(
    websocket: WebSocket,
    session_id: str = Query(..., description="세션 ID"),
    ws_token: str | None = Query(None, description="Session-scoped WebSocket token"),
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
    if not await _authenticate_websocket(websocket, session_id, ws_token):
        return

    # 핸드셰이크 Accept-Language로 에러 메시지 언어를 결정(기본 ko → 회귀 0)
    lang = _resolve_websocket_language(websocket)

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
                    lang=lang,
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
                    lang=lang,
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
                    lang=lang,
                )
                continue

            # 메시지별 세션 ID 채택: 각 메시지 payload의 session_id를 사용한다.
            # 문서/스키마 프로토콜상 클라이언트는 stream_start로 회신된 서버 확정
            # ID를 후속 메시지의 session_id에 담아 보내므로, 쿼리 파라미터(연결
            # 수립 시점 ID)가 아닌 payload ID로 파이프라인을 호출해야 비-UUID4
            # 커스텀 ID 클라이언트의 멀티턴 대화 컨텍스트가 유지된다.
            #
            # 보안 검토(IDOR): REST /chat도 요청 payload의 session_id를 수용하는
            # capability 모델이다. 약한(비-UUID4) ID는 세션 서비스가 거부하고
            # 새 UUID4를 재발급하므로(session_service.create_session 참조),
            # payload 채택이 IDOR를 재도입하지 않는다 — 추측 불가능한 UUID4
            # 자체가 접근 권한(capability)이다.
            #
            # 보안 검토(ws_token): ws_token은 쿼리 파라미터 session_id에 바인딩된
            # "연결 수립 게이트"다(_authenticate_websocket). 연결 수립 후 메시지별
            # 세션 접근은 위 capability 모델(세션 UUID 지식 = 권한)이 통제하므로,
            # payload ID 채택은 ws_token의 보안 전제를 깨지 않는다. 서버가 교체
            # 발급한 확정 ID를 같은 연결에서 사용하는 것은 정상 프로토콜이다.
            message_session_id = client_message.session_id
            if message_session_id != session_id:
                logger.debug(
                    "payload session_id가 연결 쿼리 파라미터와 다름 (서버 확정 ID 사용 추정)",
                    connection_session_id=session_id,
                    message_session_id=message_session_id,
                )

            # 스트리밍 처리
            await _process_streaming(
                websocket=websocket,
                client_message=client_message,
                session_id=message_session_id,
                lang=lang,
            )

    except Exception as e:
        logger.error(
            "WebSocket 처리 중 예외 발생",
            session_id=session_id,
            error=str(e),
            exc_info=True,
        )
    finally:
        # 연결 해제 (이 핸들러의 websocket과 동일할 때만 삭제 → 재연결 경합 방지)
        # 같은 session_id로 새 연결이 이미 등록되었다면 구 연결 정리는 무시됨
        ws_manager.disconnect(session_id, websocket)
        logger.info("WebSocket 연결 해제", session_id=session_id)


async def _process_streaming(
    websocket: WebSocket,
    client_message: ClientMessage,
    session_id: str,
    lang: str = "ko",
) -> None:
    """
    스트리밍 처리 로직

    ChatService.stream_rag_pipeline()을 호출하고 결과를 WebSocket으로 전송합니다.

    Args:
        websocket: WebSocket 연결
        client_message: 클라이언트 메시지
        session_id: 메시지별 세션 ID (payload의 session_id — 후속 메시지에서는
            stream_start로 회신된 서버 확정 ID가 담겨 멀티턴 컨텍스트를 유지)
        lang: 에러 메시지 언어("ko"|"en", 기본 ko → 회귀 0)
    """
    message_id = client_message.message_id
    start_time = time.time()
    token_index = 0
    sources: list[dict[str, Any]] = []
    # stream_start 전송 여부 추적 — metadata 수신 시점에 서버 확정 ID로 1회 전송
    stream_started = False

    try:
        # 1. RAG 파이프라인 스트리밍 호출
        # StreamStartEvent는 선전송하지 않는다. 세션 서비스가 비-UUID4 클라이언트
        # ID를 새 UUID4로 교체할 수 있으므로, 파이프라인 metadata 이벤트의
        # 서버 확정 session_id(final_session_id)를 받아 그 시점에 전송한다.
        # (stream_rag_pipeline은 metadata를 모든 chunk보다 먼저 yield하며,
        #  metadata 이전 실패 경로는 error 이벤트만 yield한다)
        async for event in _chat_service.stream_rag_pipeline(
            message=client_message.content,
            session_id=session_id,
            options={},
        ):
            event_type = event.get("event")

            if event_type == "metadata":
                # 2. 서버 확정 세션 ID 추출 후 StreamStartEvent 전송
                #    클라이언트는 이 ID를 후속 메시지의 session_id로 사용해야
                #    대화 컨텍스트(멀티턴)가 유지된다.
                metadata = event.get("data", {})
                confirmed_session_id = metadata.get("session_id") or session_id
                if not stream_started:
                    await _send_stream_start(websocket, message_id, confirmed_session_id)
                    stream_started = True
                logger.debug(
                    "스트리밍 시작 (서버 확정 세션 ID 회신)",
                    message_id=message_id,
                    session_id=confirmed_session_id,
                    search_results=metadata.get("search_results"),
                )

            elif event_type == "chunk":
                # 방어적 폴백: metadata 없이 토큰이 먼저 도착하는 비정상 경로에서도
                # 프로토콜 순서(stream_start → stream_token)를 원본 ID로 보장한다.
                if not stream_started:
                    await _send_stream_start(websocket, message_id, session_id)
                    stream_started = True

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
                # 스트리밍 중 에러 발생: 파이프라인이 전달한 error_code/message를
                # 그대로 포워딩한다(상위 단계에서 이미 메시지가 확정된 경로).
                # message가 비면 한국어 기본 폴백을 유지한다 → 회귀 0.
                await _send_error(
                    websocket=websocket,
                    message_id=message_id,
                    error_code=event.get("error_code", "GEN-999"),
                    message=event.get("message", "스트리밍 중 오류가 발생했습니다."),
                    lang=lang,
                )
                return

        # 방어적 폴백: metadata/chunk 없이 종료된 경우에도 프로토콜 순서
        # (stream_start → stream_sources → stream_end)를 원본 ID로 보장한다.
        if not stream_started:
            await _send_stream_start(websocket, message_id, session_id)
            stream_started = True

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
            lang=lang,
        )
