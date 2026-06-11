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

from ...lib.auth import create_websocket_session_token, get_api_key_auth
from ...lib.errors import ErrorCode, GenerationError, RetrievalError, SessionError, wrap_exception
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


def _ensure_service_initialized() -> None:
    """
    ChatService 초기화 확인 (Fail-Fast 원칙)

    서버 시작 직후 또는 초기화 오류 시 요청이 들어오면
    명확한 에러 메시지와 함께 즉시 실패합니다.

    Raises:
        HTTPException: chat_service가 None인 경우 503 에러
    """
    if chat_service is None:
        logger.error("🚨 ChatService 초기화되지 않음 - 요청 거부")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "서비스 초기화 중",
                "message": "서비스가 시작 중입니다. 잠시 후 다시 시도해주세요",
                "suggestion": "30초 후 재시도하거나, 문제가 지속되면 관리자에게 문의하세요",
                "retry_after": 30,
                "support_email": "support@example.com",
            },
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
    _ensure_service_initialized()  # Fail-Fast: 서비스 초기화 확인
    start_time = time.time()
    session_id = None
    try:
        context = get_request_context(request)
        session_result = await chat_service.handle_session(chat_request.session_id, context)
        if not session_result["success"]:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "세션 처리 실패",
                    "message": session_result.get("message", "세션 요청을 처리할 수 없습니다"),
                    "suggestion": "세션 ID를 확인하거나 새로운 세션을 생성하세요",
                    "session_id": chat_request.session_id,
                },
            )
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
        # 스트리밍 경로와 동일한 인라인 저장 — read-your-writes 보장.
        # BackgroundTask로 미루면 응답 직후 후속 질문이 직전 턴 없는 세션
        # 컨텍스트를 읽는 경합(standalone rewrite 실패)이 발생하고, 저장 실패가
        # 조용히 삼켜진다. 저장 실패는 아래 except에서 에러로 전파된다.
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
    _ensure_service_initialized()  # Fail-Fast: 서비스 초기화 확인
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
                detail={
                    "error": "세션 모듈 오류",
                    "message": "세션 관리 기능을 사용할 수 없습니다",
                    "suggestion": "서비스 관리자에게 문의하세요. 세션 모듈이 초기화되지 않았습니다",
                    "technical_error": "Session module not initialized",
                    "support_email": "support@example.com",
                },
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
        auth = get_api_key_auth()
        if auth.api_key:
            ws_token = create_websocket_session_token(new_session["session_id"], auth.api_key)

        return SessionResponse(
            session_id=new_session["session_id"],
            message="Session created successfully",
            timestamp=datetime.now().isoformat(),
            ws_token=ws_token,
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
            detail={
                "error": "세션 생성 실패",
                "message": "새로운 세션을 생성할 수 없습니다",
                "suggestion": "잠시 후 다시 시도하거나 관리자에게 문의하세요",
                "retry_after": 10,
                "technical_error": f"{type(error).__name__}: {str(error)}",
                "support_email": "support@example.com",
            },
        ) from error


@router.get("/chat/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str, limit: int = 20, offset: int = 0
) -> ChatHistoryResponse:
    """
    채팅 히스토리 조회

    기존 코드: chat.py의 get_chat_history() 엔드포인트 (L1435-1461)
    """
    _ensure_service_initialized()  # Fail-Fast: 서비스 초기화 확인
    try:
        session_module = chat_service.modules.get("session")
        if not session_module:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "세션 모듈 오류",
                    "message": "세션 관리 기능을 사용할 수 없습니다",
                    "suggestion": "서비스 관리자에게 문의하세요. 세션 모듈이 초기화되지 않았습니다",
                    "technical_error": "Session module not initialized",
                    "support_email": "support@example.com",
                },
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
                detail={
                    "error": "세션을 찾을 수 없습니다",
                    "message": "요청하신 세션이 존재하지 않거나 만료되었습니다",
                    "suggestion": "새로운 세션을 시작하거나 세션 ID를 확인하세요",
                    "session_id": session_id,
                },
            ) from error
        # 일반 서버 에러 (500)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "히스토리 조회 실패",
                "message": "채팅 히스토리를 불러올 수 없습니다",
                "suggestion": "잠시 후 다시 시도하거나 관리자에게 문의하세요",
                "retry_after": 10,
                "session_id": session_id,
                "technical_error": f"{type(error).__name__}: {str(error)}",
                "support_email": "support@example.com",
            },
        ) from error


@router.delete("/chat/session/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    """
    세션 삭제

    기존 코드: chat.py의 delete_session() 엔드포인트 (L1464-1481)
    """
    _ensure_service_initialized()  # Fail-Fast: 서비스 초기화 확인
    try:
        session_module = chat_service.modules.get("session")
        if not session_module:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "세션 모듈 오류",
                    "message": "세션 관리 기능을 사용할 수 없습니다",
                    "suggestion": "서비스 관리자에게 문의하세요. 세션 모듈이 초기화되지 않았습니다",
                    "technical_error": "Session module not initialized",
                    "support_email": "support@example.com",
                },
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
                detail={
                    "error": "세션을 찾을 수 없습니다",
                    "message": "삭제하려는 세션이 존재하지 않거나 이미 삭제되었습니다",
                    "suggestion": "세션 ID를 확인하세요",
                    "session_id": session_id,
                },
            ) from error
        # 일반 서버 에러 (500)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "세션 삭제 실패",
                "message": "세션을 삭제할 수 없습니다",
                "suggestion": "잠시 후 다시 시도하거나 관리자에게 문의하세요",
                "retry_after": 10,
                "session_id": session_id,
                "technical_error": f"{type(error).__name__}: {str(error)}",
                "support_email": "support@example.com",
            },
        ) from error


@router.get("/chat/stats", response_model=StatsResponse)
async def get_stats() -> StatsResponse:
    """
    통계 조회

    기존 코드: chat.py의 get_stats() 엔드포인트 (L1484-1494)
    """
    _ensure_service_initialized()  # Fail-Fast: 서비스 초기화 확인
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
            detail={
                "error": "통계 조회 실패",
                "message": "시스템 통계를 불러올 수 없습니다",
                "suggestion": "잠시 후 다시 시도하거나 관리자에게 문의하세요",
                "retry_after": 10,
                "technical_error": f"{type(error).__name__}: {str(error)}",
                "support_email": "support@example.com",
            },
        ) from error


@router.get("/chat/session/{session_id}/info", response_model=SessionInfoResponse)
async def get_session_info(session_id: str) -> SessionInfoResponse:
    """
    세션 상세 정보 조회

    기존 코드: chat.py의 get_session_info() 엔드포인트 (L1497-1551)
    """
    _ensure_service_initialized()  # Fail-Fast: 서비스 초기화 확인
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
                detail={
                    "error": "세션을 찾을 수 없습니다",
                    "message": "요청하신 세션이 존재하지 않거나 만료되었습니다",
                    "suggestion": "새로운 세션을 시작하거나 세션 ID를 확인하세요",
                    "session_id": session_id,
                },
            ) from error
        # 일반 서버 에러 (500)
        logger.error("Get session info error", error=str(error))
        raise HTTPException(
            status_code=500,
            detail={
                "error": "세션 정보 조회 실패",
                "message": "세션 정보를 불러올 수 없습니다",
                "suggestion": "잠시 후 다시 시도하거나 관리자에게 문의하세요",
                "retry_after": 10,
                "session_id": session_id,
                "technical_error": f"{type(error).__name__}: {str(error)}",
                "support_email": "support@example.com",
            },
        ) from error


@router.post("/chat/feedback", response_model=FeedbackResponse)
async def process_feedback(feedback_request: FeedbackRequest) -> FeedbackResponse:
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
        return FeedbackResponse(
            success=False,
            feedback_id=None,
            message="피드백 저장에 실패했습니다",
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
    _ensure_service_initialized()  # Fail-Fast: 서비스 초기화 확인

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

            error_event = StreamErrorEvent(
                error_code=ErrorCode.STREAM_001.value,
                message="스트리밍 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
                suggestion="문제가 지속되면 관리자에게 문의하세요.",
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
