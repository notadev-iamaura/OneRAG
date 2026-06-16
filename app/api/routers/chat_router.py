"""
Chat Router - FastAPI 라우팅 레이어

Phase 3.3: chat.py에서 추출한 검증된 라우팅 로직
기존 코드 기반: app/api/chat.py의 엔드포인트들

⚠️ 주의: 이 코드는 기존 검증된 라우팅을 재사용합니다.

## Router Layer의 역할
- HTTP 요청/응답 처리만 담당
- 비즈니스 로직은 ChatService에 위임
- Rate limiting, 요청 검증, 에러 핸들링
"""

import json
import os
import time
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from ...lib.auth import (
    create_upload_access_token,
    create_websocket_session_token,
    get_api_key_auth,
    get_upload_token_ttl_seconds,
)
from ...lib.errors import (
    ErrorCode,
    GenerationError,
    RetrievalError,
    SessionError,
    format_user_facing_error,
    get_error_message,
    get_error_solutions,
    wrap_exception,
)
from ...lib.logger import get_logger
from ..schemas.chat_schemas import (
    ChatHistoryResponse,
    ChatRequest,
    ChatResponse,
    SessionCreateRequest,
    SessionInfoResponse,
    SessionResponse,
    StatsResponse,
)
from ..schemas.feedback import FeedbackRequest, FeedbackResponse
from ..schemas.streaming import StreamChatRequest, StreamErrorEvent
from ..services.chat_service import ChatService

logger = get_logger(__name__)
router = APIRouter(tags=["Chat"])
limiter = Limiter(key_func=get_remote_address)
chat_service: ChatService = None  # type: ignore[assignment]
CHAT_STREAM_RATE_LIMIT = os.getenv("CHAT_STREAM_RATE_LIMIT", "100/15minutes")


def set_chat_service(service: ChatService) -> None:
    """ChatService 의존성 주입"""
    global chat_service
    chat_service = service
    logger.info("ChatService 주입 완료")


def get_real_client_ip(request: Request) -> str:
    """
    Railway 환경에서 실제 클라이언트 IP 추출

    기존 코드: chat.py의 get_real_client_ip() 함수 (L182-206)
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        real_ip = forwarded_for.split(",")[0].strip()
        logger.debug(f"Real client IP from X-Forwarded-For: {real_ip}")
        return real_ip
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        logger.debug(f"Real client IP from CF-Connecting-IP: {cf_ip}")
        return cf_ip
    real_ip = request.headers.get("X-Real-IP")  # type: ignore[assignment]
    if real_ip:
        logger.debug(f"Real client IP from X-Real-IP: {real_ip}")
        return real_ip  # type: ignore[return-value]
    fallback_ip = request.client.host if request.client else "unknown"
    logger.debug(f"Using fallback client IP: {fallback_ip}")
    return fallback_ip


def _resolve_request_language(request: Request) -> str:
    """요청 Accept-Language 헤더에서 에러 메시지 언어를 결정한다(ko|en, 기본 ko).

    양언어 에러 카탈로그(app.lib.errors)는 "ko"/"en"만 지원한다. 헤더가 영어를
    우선하면 "en"을, 그 외(미지정 포함)는 "ko"를 반환한다 → 한국어 기본(회귀 0).
    """
    accept_language = (request.headers.get("accept-language") or "").lower()
    en_idx = accept_language.find("en")
    ko_idx = accept_language.find("ko")
    if en_idx != -1 and (ko_idx == -1 or en_idx < ko_idx):
        return "en"
    return "ko"


def get_request_context(request: Request) -> dict[str, Any]:
    """
    요청 컨텍스트 추출

    기존 코드: chat.py의 get_request_context() 함수 (L209-218)
    """
    real_ip = get_real_client_ip(request)
    return {
        "ip_address": real_ip,
        "user_agent": request.headers.get("user-agent"),
        "referrer": request.headers.get("referer"),
    }


def _ensure_service_initialized(lang: str = "ko") -> None:
    """
    ChatService 초기화 확인 (Fail-Fast 원칙)

    서버 시작 직후 또는 초기화 오류 시 요청이 들어오면
    명확한 에러 메시지와 함께 즉시 실패합니다.

    Args:
        lang: 에러 메시지 언어("ko"|"en", 기본 ko). 호출부에서
            _resolve_request_language(request)로 결정해 전달한다. 미전달 시
            한국어(회귀 0).

    Raises:
        HTTPException: chat_service가 None인 경우 503 에러
    """
    if chat_service is None:
        logger.error("🚨 ChatService 초기화되지 않음 - 요청 거부")
        # 사용자 노출 3-필드는 양언어 카탈로그(SERVICE-001)에서 lang별로 가져오고,
        # retry_after/support_email 등 보존 필드는 preserve로 그대로 병합한다.
        raise HTTPException(
            status_code=503,
            detail=format_user_facing_error(
                ErrorCode.SERVICE_001.value,
                lang,
                retry_after=30,
                support_email="support@example.com",
            ),
        )


def _get_confidence_level(score: float) -> str:
    """
    품질 점수 → 신뢰도 레벨 변환

    Args:
        score: 품질 점수 (0.0-1.0 범위 필수)

    Returns:
        신뢰도 레벨 ("low" | "medium" | "high")

    Raises:
        ValueError: score가 0.0-1.0 범위를 벗어남
    """
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"Invalid quality score: {score}. Must be in [0.0, 1.0]")

    if score >= 0.8:
        return "high"
    elif score >= 0.6:
        return "medium"
    else:
        return "low"


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    chat_request: ChatRequest,
) -> ChatResponse:
    """
    채팅 처리 엔드포인트

    기존 코드: chat.py의 chat() 엔드포인트 (L1269-1408)
    """
    # 에러 메시지 언어를 요청 Accept-Language로 결정(기본 ko → 회귀 0)
    lang = _resolve_request_language(request)
    _ensure_service_initialized(lang)  # Fail-Fast: 서비스 초기화 확인
    start_time = time.time()
    session_id = None
    try:
        context = get_request_context(request)
        session_result = await chat_service.handle_session(chat_request.session_id, context)
        if not session_result["success"]:
            # 카탈로그(SESSION-001) 기반 3-필드 + 세션 ID 보존. message는
            # 동적 폴백(session_result["message"])이 있으면 그것으로 덮어쓰고,
            # 없으면 카탈로그 ko 폴백("세션 요청을 처리할 수 없습니다")을 유지한다.
            session_detail = format_user_facing_error(
                ErrorCode.SESSION_001.value,
                lang,
                session_id=chat_request.session_id,
            )
            dynamic_message = session_result.get("message")
            if dynamic_message:
                session_detail["message"] = dynamic_message
            raise HTTPException(status_code=400, detail=session_detail)
        session_id = session_result["session_id"]
        # Self-RAG는 RAGPipeline 내부에서 자동으로 처리됨 (중복 실행 제거)
        # Agent 모드 옵션 병합 (use_agent 필드를 options에 포함)
        options = chat_request.options or {}
        if chat_request.use_agent:
            options["use_agent"] = True
        if chat_request.enable_debug_trace:
            options["enable_debug_trace"] = True
        rag_result = await chat_service.execute_rag_pipeline(
            chat_request.message, session_id, options
        )
        message_id = str(uuid4())
        # 저장 순서는 양 경로(비스트리밍/스트리밍) 모두 인라인 await —
        # read-your-writes 보장. BackgroundTask로 미루면 응답 직후 후속 질문이
        # 직전 턴 없는 세션 컨텍스트를 읽는 경합(standalone rewrite 실패)이 발생한다.
        # 단, 저장 실패 의미론은 두 경로가 의도적으로 다르다:
        # - 비스트리밍(여기): 응답 전송 전 실패이므로 예외를 전파해 500으로
        #   처리한다 — 클라이언트가 실패를 인지하고 재시도할 수 있다.
        # - 스트리밍(chat_service.stream_rag_pipeline): 이미 답변 토큰을 전송한
        #   뒤의 저장이므로 중간에 500을 보낼 수 없다 — 예외를 로그로 남기고
        #   계속 진행한다(에러 숨김이 아니라 프로토콜상 불가피한 선택).
        await chat_service.add_conversation_to_session(
            session_id,
            chat_request.message,
            rag_result["answer"],
            {
                "tokens_used": rag_result["tokens_used"],
                "processing_time": time.time() - start_time,
                "sources": rag_result["sources"],
                "topic": rag_result["topic"],
                "model_info": rag_result.get("model_info"),
                "message_id": message_id,
                "can_evaluate": True,
                "debug_trace": rag_result.get("debug_trace"),  # E2E 테스트용 디버그 추적
            },
        )
        # Self-RAG 메타데이터는 model_info에 포함되어 있음
        self_rag_metadata = None
        if rag_result.get("model_info", {}).get("self_rag_applied"):
            self_rag_metadata = {
                "used_self_rag": True,
                "complexity_score": rag_result["model_info"].get("complexity_score"),
                "initial_quality": rag_result["model_info"].get("initial_quality"),
                "final_quality": rag_result["model_info"].get("final_quality"),
                "regenerated": rag_result["model_info"].get("self_rag_regenerated", False),
            }

        # ⭐ 품질 메타데이터 구성 (Self-RAG Phase 3.1)
        metadata: dict[str, Any] = {"total_time": time.time() - start_time}

        # Self-RAG 품질 점수가 있는 경우 quality 객체 추가
        quality_score = rag_result.get("quality_score")
        if quality_score is not None:
            quality_metadata = {
                "score": round(quality_score, 2),
                "confidence": _get_confidence_level(quality_score),
                "self_rag_applied": rag_result.get("model_info", {}).get(
                    "self_rag_applied", False
                ),
            }

            # 저품질 거부 사유가 있으면 추가
            refusal_reason = rag_result.get("refusal_reason")
            if refusal_reason:
                quality_metadata["refusal_reason"] = refusal_reason

            metadata["quality"] = quality_metadata

        response = ChatResponse(
            answer=rag_result["answer"],
            sources=rag_result["sources"],
            session_id=session_id,
            message_id=message_id,
            processing_time=time.time() - start_time,
            tokens_used=rag_result["tokens_used"],
            timestamp=datetime.now().isoformat(),
            model_info=rag_result.get("model_info"),
            can_evaluate=True,
            self_rag_metadata=self_rag_metadata,
            metadata=metadata,  # ⭐ 품질 메타데이터 추가
        )
        chat_service.update_stats(
            {
                "tokens_used": rag_result["tokens_used"],
                "latency": time.time() - start_time,
                "success": True,
            }
        )
        logger.debug(
            "Chat request completed successfully",
            session_id=session_id,
            message_length=len(chat_request.message),
            processing_time=time.time() - start_time,
            tokens_used=rag_result["tokens_used"],
            sources_count=len(rag_result["sources"]),
        )
        return response
    except GenerationError as e:
        logger.debug(
            "Generation error in chat API (business context)",
            error_code=e.error_code.value,
            message=e.message,
            context=e.context,
            session_id=session_id,
        )
        chat_service.update_stats({"success": False})
        raise
    except RetrievalError as e:
        logger.debug(
            "Retrieval error in chat API (business context)",
            error_code=e.error_code.value,
            message=e.message,
            context=e.context,
            session_id=session_id,
        )
        chat_service.update_stats({"success": False})
        raise
    except SessionError as e:
        logger.debug(
            "Session error in chat API (business context)",
            error_code=e.error_code.value,
            message=e.message,
            context=e.context,
            session_id=session_id,
        )
        chat_service.update_stats({"success": False})
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.debug(
            "Unknown error in chat API (business context)",
            error=str(e),
            error_type=type(e).__name__,
            session_id=session_id,
        )
        chat_service.update_stats({"success": False})
        wrapped_error = wrap_exception(
            e,
            default_message="요청 처리 중 오류가 발생했습니다",
            error_code=ErrorCode.GENERAL_001,
            context={
                "session_id": session_id,
                "endpoint": "/api/chat",
                "processing_time": time.time() - start_time,
            },
        )
        raise wrapped_error from e


@router.post("/chat/session", response_model=SessionResponse)
async def create_session(
    request: Request, session_request: SessionCreateRequest
) -> SessionResponse:
    """
    새 세션 생성

    기존 코드: chat.py의 create_session() 엔드포인트 (L1411-1432)
    """
    # 에러 메시지 언어를 요청 Accept-Language로 결정(기본 ko → 회귀 0)
    lang = _resolve_request_language(request)
    _ensure_service_initialized(lang)  # Fail-Fast: 서비스 초기화 확인
    start_time = time.time()  # ⏱️ 성능 측정 시작
    logger.info("🔵 세션 생성 요청 시작")

    try:
        # Step 1: 요청 컨텍스트 추출
        context_start = time.time()
        logger.info("📍 Step 1: 요청 컨텍스트 추출 시작")
        context = get_request_context(request)
        logger.info(
            f"✅ Step 1 완료: 컨텍스트 추출 ({(time.time() - context_start)*1000:.2f}ms)",
            extra={"context": context},
        )

        # Step 2: 메타데이터 병합
        if session_request.metadata:
            logger.info("📍 Step 2: 메타데이터 병합")
            context.update(session_request.metadata)

        # Step 3: 세션 모듈 가져오기
        module_start = time.time()
        logger.info("📍 Step 3: 세션 모듈 가져오기")
        session_module = chat_service.modules.get("session")
        logger.info(f"✅ Step 3 완료: 모듈 가져오기 ({(time.time() - module_start)*1000:.2f}ms)")

        if not session_module:
            logger.error("❌ 세션 모듈 없음")
            raise HTTPException(
                status_code=500,
                detail=format_user_facing_error(
                    ErrorCode.SESSION_002.value,
                    lang,
                    technical_error="Session module not initialized",
                    support_email="support@example.com",
                ),
            )

        # Step 4: 세션 생성 (성능 측정)
        session_start = time.time()
        logger.info("📍 Step 4: 세션 생성 호출 시작")
        new_session = await session_module.create_session({"metadata": context})
        session_duration = time.time() - session_start
        logger.info(f"✅ Step 4 완료: 세션 생성 ({session_duration*1000:.2f}ms)")

        total_duration = time.time() - start_time
        logger.info(
            f"✅ 세션 생성 완료: {new_session['session_id']}",
            extra={
                "session_creation_time": f"{session_duration:.3f}s",
                "total_time": f"{total_duration:.3f}s",
                "context_size": len(str(context)),
            },
        )
        ws_token = None
        upload_token = None
        upload_token_expires_at = None
        upload_token_ttl_seconds = None
        auth = get_api_key_auth()
        if auth.api_key:
            ws_token = create_websocket_session_token(new_session["session_id"], auth.api_key)
            # 브라우저가 서버 API 키를 보유하지 않고도 업로드할 수 있도록
            # 세션에 바인딩된 단기 업로드 토큰을 함께 발급한다(#22).
            upload_token_ttl_seconds = get_upload_token_ttl_seconds()
            upload_token_expires_at = int(time.time()) + upload_token_ttl_seconds
            upload_token = create_upload_access_token(
                new_session["session_id"],
                auth.api_key,
                ttl_seconds=upload_token_ttl_seconds,
            )

        return SessionResponse(
            session_id=new_session["session_id"],
            message="Session created successfully",
            timestamp=datetime.now().isoformat(),
            ws_token=ws_token,
            upload_token=upload_token,
            upload_token_expires_at=upload_token_expires_at,
            upload_token_ttl_seconds=upload_token_ttl_seconds,
        )
    except HTTPException:
        logger.error(f"❌ HTTPException 발생 ({(time.time() - start_time)*1000:.2f}ms)")
        raise
    except Exception as error:
        logger.error(
            f"❌ Create session error: {type(error).__name__}: {str(error)}",
            extra={
                "total_time": f"{time.time() - start_time:.3f}s",
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=format_user_facing_error(
                ErrorCode.SESSION_003.value,
                lang,
                retry_after=10,
                technical_error=f"{type(error).__name__}: {str(error)}",
                support_email="support@example.com",
            ),
        ) from error


@router.get("/chat/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    request: Request, session_id: str, limit: int = 20, offset: int = 0
) -> ChatHistoryResponse:
    """
    채팅 히스토리 조회

    기존 코드: chat.py의 get_chat_history() 엔드포인트 (L1435-1461)
    """
    # 에러 메시지 언어를 요청 Accept-Language로 결정(기본 ko → 회귀 0)
    lang = _resolve_request_language(request)
    _ensure_service_initialized(lang)  # Fail-Fast: 서비스 초기화 확인
    try:
        session_module = chat_service.modules.get("session")
        if not session_module:
            raise HTTPException(
                status_code=500,
                detail=format_user_facing_error(
                    ErrorCode.SESSION_004.value,
                    lang,
                    technical_error="Session module not initialized",
                    support_email="support@example.com",
                ),
            )
        history = await session_module.get_chat_history(session_id)
        start = offset
        end = start + limit
        paginated_messages = history["messages"][start:end]
        return ChatHistoryResponse(
            session_id=session_id,
            messages=paginated_messages,
            total_messages=history["message_count"],
            limit=limit,
            offset=offset,
            has_more=end < history["message_count"],
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Get chat history error", error=str(error))
        # 세션 없음 에러 (404)
        if "not found" in str(error).lower():
            raise HTTPException(
                status_code=404,
                detail=format_user_facing_error(
                    ErrorCode.SESSION_005.value,
                    lang,
                    session_id=session_id,
                ),
            ) from error
        # 일반 서버 에러 (500)
        raise HTTPException(
            status_code=500,
            detail=format_user_facing_error(
                ErrorCode.SESSION_006.value,
                lang,
                retry_after=10,
                session_id=session_id,
                technical_error=f"{type(error).__name__}: {str(error)}",
                support_email="support@example.com",
            ),
        ) from error


@router.delete("/chat/session/{session_id}")
async def delete_session(request: Request, session_id: str) -> dict[str, str]:
    """
    세션 삭제

    기존 코드: chat.py의 delete_session() 엔드포인트 (L1464-1481)
    """
    # 에러 메시지 언어를 요청 Accept-Language로 결정(기본 ko → 회귀 0)
    lang = _resolve_request_language(request)
    _ensure_service_initialized(lang)  # Fail-Fast: 서비스 초기화 확인
    try:
        session_module = chat_service.modules.get("session")
        if not session_module:
            raise HTTPException(
                status_code=500,
                detail=format_user_facing_error(
                    ErrorCode.SESSION_007.value,
                    lang,
                    technical_error="Session module not initialized",
                    support_email="support@example.com",
                ),
            )
        await session_module.delete_session(session_id)
        return {
            "message": "Session deleted successfully",
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Delete session error", error=str(error))
        # 세션 없음 에러 (404)
        if "not found" in str(error).lower():
            raise HTTPException(
                status_code=404,
                detail=format_user_facing_error(
                    ErrorCode.SESSION_008.value,
                    lang,
                    session_id=session_id,
                ),
            ) from error
        # 일반 서버 에러 (500)
        raise HTTPException(
            status_code=500,
            detail=format_user_facing_error(
                ErrorCode.SESSION_009.value,
                lang,
                retry_after=10,
                session_id=session_id,
                technical_error=f"{type(error).__name__}: {str(error)}",
                support_email="support@example.com",
            ),
        ) from error


@router.get("/chat/stats", response_model=StatsResponse)
async def get_stats(request: Request) -> StatsResponse:
    """
    통계 조회

    기존 코드: chat.py의 get_stats() 엔드포인트 (L1484-1494)
    """
    # 에러 메시지 언어를 요청 Accept-Language로 결정(기본 ko → 회귀 0)
    lang = _resolve_request_language(request)
    _ensure_service_initialized(lang)  # Fail-Fast: 서비스 초기화 확인
    try:
        session_module = chat_service.modules.get("session")
        session_stats = await session_module.get_stats() if session_module else {}
        return StatsResponse(
            chat=chat_service.get_stats(),
            session=session_stats,
            timestamp=datetime.now().isoformat(),
        )
    except Exception as error:
        logger.error("Get stats error", error=str(error))
        raise HTTPException(
            status_code=500,
            detail=format_user_facing_error(
                ErrorCode.SESSION_010.value,
                lang,
                retry_after=10,
                technical_error=f"{type(error).__name__}: {str(error)}",
                support_email="support@example.com",
            ),
        ) from error


@router.get("/chat/session/{session_id}/info", response_model=SessionInfoResponse)
async def get_session_info(request: Request, session_id: str) -> SessionInfoResponse:
    """
    세션 상세 정보 조회

    기존 코드: chat.py의 get_session_info() 엔드포인트 (L1497-1551)
    """
    # 에러 메시지 언어를 요청 Accept-Language로 결정(기본 ko → 회귀 0)
    lang = _resolve_request_language(request)
    _ensure_service_initialized(lang)  # Fail-Fast: 서비스 초기화 확인
    try:
        info = await chat_service.get_session_info(session_id)
        return SessionInfoResponse(
            session_id=info["session_id"],
            messageCount=info["message_count"],
            tokensUsed=info["tokens_used"],
            processingTime=info["processing_time"],
            modelInfo=info["model_info"],
            timestamp=info["timestamp"],
        )
    except HTTPException:
        raise
    except Exception as error:
        # 세션 없음 에러 (404)
        if "not found" in str(error).lower():
            raise HTTPException(
                status_code=404,
                detail=format_user_facing_error(
                    ErrorCode.SESSION_011.value,
                    lang,
                    session_id=session_id,
                ),
            ) from error
        # 일반 서버 에러 (500)
        logger.error("Get session info error", error=str(error))
        raise HTTPException(
            status_code=500,
            detail=format_user_facing_error(
                ErrorCode.SESSION_012.value,
                lang,
                retry_after=10,
                session_id=session_id,
                technical_error=f"{type(error).__name__}: {str(error)}",
                support_email="support@example.com",
            ),
        ) from error


@router.post("/chat/feedback", response_model=FeedbackResponse)
async def process_feedback(
    request: Request, feedback_request: FeedbackRequest
) -> FeedbackResponse:
    """
    사용자 피드백 처리

    사용자가 답변에 대한 평가(좋아요/싫어요)를 제출할 때 호출됩니다.
    피드백 데이터는 저장되어 품질 개선 및 Golden Dataset 구축에 활용됩니다.

    Args:
        feedback_request: 피드백 요청 데이터
            - session_id: 세션 ID
            - message_id: 평가 대상 메시지 ID
            - rating: 1 (좋아요) 또는 -1 (싫어요)
            - comment: 추가 코멘트 (선택)
            - query: 원본 질문 (Golden 후보용)
            - response: 원본 답변 (Golden 후보용)

    Returns:
        FeedbackResponse: 피드백 저장 결과
            - success: 저장 성공 여부
            - feedback_id: 저장된 피드백 ID
            - message: 결과 메시지
            - golden_candidate: Golden Dataset 후보 등록 여부
    """
    try:
        # 피드백 서비스를 통해 저장 (향후 구현)
        # 현재는 로깅만 수행하고 성공 응답 반환
        feedback_id = str(uuid4())

        logger.info(
            "피드백 수신",
            session_id=feedback_request.session_id,
            message_id=feedback_request.message_id,
            rating=feedback_request.rating,
            has_comment=bool(feedback_request.comment),
        )

        # Golden Dataset 후보 등록 여부 결정
        # 긍정 피드백 + 쿼리/응답 데이터가 있는 경우 후보로 등록
        golden_candidate = (
            feedback_request.rating == 1
            and feedback_request.query is not None
            and feedback_request.response is not None
        )

        if golden_candidate:
            logger.info(
                "Golden Dataset 후보 등록",
                feedback_id=feedback_id,
                session_id=feedback_request.session_id,
            )

        return FeedbackResponse(
            success=True,
            feedback_id=feedback_id,
            message="피드백이 저장되었습니다",
            golden_candidate=golden_candidate,
        )
    except Exception as error:
        logger.error("피드백 처리 오류", error=str(error), exc_info=True)
        # 실패 메시지는 양언어 카탈로그(FEEDBACK-001)에서 Accept-Language별로 조회한다.
        # 기본 ko 카탈로그 값은 기존 하드코딩 문자열과 동일하다 → 회귀 0.
        lang = _resolve_request_language(request)
        return FeedbackResponse(
            success=False,
            feedback_id=None,
            message=get_error_message(ErrorCode.FEEDBACK_001.value, lang),
            golden_candidate=False,
        )


@router.post("/chat/stream")
@limiter.limit(CHAT_STREAM_RATE_LIMIT)
async def chat_stream(request: Request, chat_request: StreamChatRequest) -> StreamingResponse:
    """
    스트리밍 채팅 엔드포인트 (SSE)

    Server-Sent Events 형식으로 실시간 채팅 응답을 스트리밍합니다.
    검색, 리랭킹은 비스트리밍으로 처리하고, 답변 생성만 스트리밍합니다.

    SSE 이벤트 형식:
    - metadata: 검색 결과 메타데이터 (세션 ID, 문서 수 등)
    - chunk: LLM 응답 텍스트 청크
    - done: 스트리밍 완료 이벤트
    - error: 에러 이벤트

    Args:
        request: FastAPI 요청 객체
        chat_request: 스트리밍 채팅 요청
            - message: 사용자 메시지 (필수)
            - session_id: 세션 ID (선택, 없으면 새로 생성)
            - options: 추가 옵션 (temperature, max_tokens 등)

    Returns:
        StreamingResponse: text/event-stream 형식의 SSE 응답
    """
    # 에러 메시지 언어를 요청 Accept-Language로 결정(기본 ko → 회귀 0)
    error_lang = _resolve_request_language(request)

    _ensure_service_initialized(error_lang)  # Fail-Fast: 서비스 초기화 확인

    async def event_generator():
        """
        SSE 이벤트 생성기

        ChatService.stream_rag_pipeline()에서 반환하는 이벤트를
        SSE 형식(event: {type}\ndata: {json}\n\n)으로 변환합니다.
        """
        try:
            async for event in chat_service.stream_rag_pipeline(
                message=chat_request.message,
                session_id=chat_request.session_id,
                options=chat_request.options,
            ):
                # 이벤트 타입 추출 (기본값: chunk)
                event_type = event.get("event", "chunk")

                # JSON으로 직렬화 (한글 유니코드 유지)
                event_data = json.dumps(event, ensure_ascii=False)

                # SSE 형식으로 yield
                yield f"event: {event_type}\ndata: {event_data}\n\n"

        except Exception as e:
            # 스트리밍 중 에러 발생 시 에러 이벤트 전송
            logger.error("스트리밍 에러", exc_info=True, error=str(e))

            # 사용자 노출 메시지/해결방법을 양언어 에러 카탈로그(ErrorCode.STREAM_001)
            # 에서 lang별로 조회한다 → Accept-Language 기반 한/영 자동 전환. 기본 ko
            # 카탈로그 값은 기존 하드코딩 문자열과 동일하다 → 회귀 0.
            stream_solutions = get_error_solutions(
                ErrorCode.STREAM_001.value, lang=error_lang
            )
            error_event = StreamErrorEvent(
                error_code=ErrorCode.STREAM_001.value,
                message=get_error_message(ErrorCode.STREAM_001.value, lang=error_lang),
                suggestion=stream_solutions[0] if stream_solutions else None,
            )

            # 에러 이벤트를 SSE 형식으로 전송
            yield f"event: error\ndata: {error_event.model_dump_json()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Encoding": "identity",
            "X-Accel-Buffering": "no",
        },
    )
