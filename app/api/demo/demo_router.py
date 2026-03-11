"""
Demo API Router — 라이브 데모용 REST 엔드포인트

세션 관리, 문서 업로드, RAG 질문 답변을 제공합니다.
Rate Limit이 적용되어 API 비용을 보호합니다.

엔드포인트:
- POST   /sessions              세션 생성 (3/분)
- DELETE /sessions/{session_id}  세션 삭제 (30/분)
- POST   /sessions/{session_id}/upload    문서 업로드 (5/분)
- GET    /sessions/{session_id}/documents 문서 목록 (30/분)
- POST   /sessions/{session_id}/chat      RAG 질문 (5/분)
- POST   /sessions/{session_id}/chat/stream  RAG 질문 SSE (5/분)
- GET    /stats                  데모 통계 (30/분)
"""

import json
import os
import pathlib
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Body, File, HTTPException, Path, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.lib.errors.codes import ErrorCode
from app.lib.logger import get_logger

from .demo_pipeline import ALLOWED_EXTENSIONS, DemoPipeline
from .session_manager import DemoSessionManager

logger = get_logger(__name__)

# =============================================================================
# 상수
# =============================================================================

# 청크 단위 파일 읽기 크기 (1MB)
_READ_CHUNK_SIZE = 1024 * 1024

# =============================================================================
# Rate Limiter (IP 기준, 보수적 설정 — API 비용 최소화)
# =============================================================================

limiter = Limiter(key_func=get_remote_address)

# Rate Limit 수치 (환경 변수로 오버라이드 가능)
RATE_LIMIT_SESSION = os.getenv("DEMO_RATE_SESSION", "3/minute")
RATE_LIMIT_UPLOAD = os.getenv("DEMO_RATE_UPLOAD", "5/minute")
RATE_LIMIT_CHAT = os.getenv("DEMO_RATE_CHAT", "5/minute")
RATE_LIMIT_READ = os.getenv("DEMO_RATE_READ", "30/minute")

# MIME 타입 → 허용 확장자 매핑
_MIME_EXTENSION_MAP: dict[str, set[str]] = {
    "application/pdf": {"pdf"},
    "text/plain": {"txt", "md", "csv"},
    "text/markdown": {"md"},
    "text/csv": {"csv"},
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {"docx"},
    "application/octet-stream": ALLOWED_EXTENSIONS,  # 알 수 없는 타입은 확장자로 재검증
}

# =============================================================================
# 라우터 설정
# =============================================================================

router = APIRouter(tags=["Demo"])

# 전역 인스턴스 (demo_main.py에서 주입)
_session_manager: DemoSessionManager | None = None
_pipeline: DemoPipeline | None = None


def set_demo_services(
    session_manager: DemoSessionManager,
    pipeline: DemoPipeline,
) -> None:
    """
    데모 서비스 인스턴스 주입

    demo_main.py에서 초기화 후 호출합니다.

    Args:
        session_manager: 세션 관리자
        pipeline: RAG 파이프라인
    """
    global _session_manager, _pipeline
    _session_manager = session_manager
    _pipeline = pipeline
    logger.info("Demo 서비스 주입 완료")


def _get_manager() -> DemoSessionManager:
    """세션 관리자 반환 (미초기화 시 500 에러)"""
    if _session_manager is None:
        raise HTTPException(
            status_code=500,
            detail=ErrorCode.DEMO_001.value,
        )
    return _session_manager


def _get_pipeline() -> DemoPipeline:
    """파이프라인 반환 (미초기화 시 500 에러)"""
    if _pipeline is None:
        raise HTTPException(
            status_code=500,
            detail=ErrorCode.DEMO_001.value,
        )
    return _pipeline


def _get_limiter(request: Request) -> Limiter:
    """앱에 등록된 Rate Limiter 반환"""
    return request.app.state.limiter


def _validate_mime_type(file_bytes: bytes, file_ext: str) -> None:
    """
    python-magic으로 실제 파일 MIME 타입 검증

    확장자와 실제 파일 내용의 MIME 타입이 일치하는지 확인합니다.
    """
    try:
        import magic

        detected_mime = magic.from_buffer(file_bytes[:8192], mime=True)
    except ImportError:
        # python-magic 미설치 시 확장자 검증만 수행
        logger.warning("python-magic 미설치 — MIME 검증 건너뜀")
        return
    except Exception as e:
        logger.warning(f"MIME 타입 감지 실패: {e}")
        return

    # 감지된 MIME 타입에서 허용되는 확장자 확인
    allowed_exts = _MIME_EXTENSION_MAP.get(detected_mime)
    if allowed_exts is None:
        # 알려지지 않은 MIME 타입 → text/* 계열이면 텍스트 파일로 허용
        if detected_mime.startswith("text/"):
            return
        raise HTTPException(
            status_code=400,
            detail=ErrorCode.DEMO_006.value,
        )

    if file_ext not in allowed_exts:
        logger.warning(
            f"MIME 불일치: 확장자=.{file_ext}, 감지={detected_mime}"
        )
        raise HTTPException(
            status_code=400,
            detail=ErrorCode.DEMO_006.value,
        )


# =============================================================================
# 요청/응답 스키마
# =============================================================================


class CreateSessionResponse(BaseModel):
    """세션 생성 응답"""

    session_id: str
    collection_name: str
    ttl_seconds: int
    max_documents: int
    max_file_size_mb: int


class ChatRequest(BaseModel):
    """채팅 요청"""

    question: str = Field(..., min_length=1, max_length=1000)


class ChatResponse(BaseModel):
    """채팅 응답"""

    answer: str
    sources: list[dict[str, str]]
    chunks_used: int


class DocumentInfo(BaseModel):
    """문서 정보"""

    filename: str
    index: int


class DocumentListResponse(BaseModel):
    """문서 목록 응답"""

    session_id: str
    documents: list[DocumentInfo]
    total: int
    max_documents: int


class UploadResponse(BaseModel):
    """업로드 응답"""

    filename: str
    chunks: int
    collection: str


class StatsResponse(BaseModel):
    """통계 응답"""

    active_sessions: int
    max_sessions: int
    ttl_seconds: int
    total_sessions_created: int
    total_sessions_expired: int
    total_documents_uploaded: int
    daily_api_calls: int
    daily_api_limit: int
    allowed_file_types: list[str]


# =============================================================================
# 엔드포인트
# =============================================================================


@router.post("/sessions", response_model=CreateSessionResponse)
@limiter.limit(RATE_LIMIT_SESSION)
async def create_session(request: Request) -> CreateSessionResponse:
    """
    새 데모 세션을 생성합니다.

    세션 수 제한 초과 시 가장 오래된 세션이 자동 정리됩니다.
    """
    manager = _get_manager()
    session = await manager.create_session()

    return CreateSessionResponse(
        session_id=session.session_id,
        collection_name=session.collection_name,
        ttl_seconds=manager.ttl_seconds,
        max_documents=manager.max_docs_per_session,
        max_file_size_mb=manager.max_file_size_mb,
    )


@router.delete("/sessions/{session_id}")
@limiter.limit(RATE_LIMIT_READ)
async def delete_session(
    request: Request,
    session_id: str = Path(..., min_length=1, max_length=200),
) -> dict[str, str]:
    """세션을 수동으로 삭제합니다."""
    manager = _get_manager()
    deleted = await manager.delete_session(session_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=ErrorCode.DEMO_002.value,
        )

    # 호환 라우터의 인메모리 히스토리도 정리 (메모리 누수 방지)
    # 콜백 패턴으로 session_manager 내부에서 자동 호출되지만,
    # 명시적 삭제 경로에서도 직접 정리하여 이중 안전장치 확보
    try:
        from app.api.demo.compat_router import cleanup_session_history

        cleanup_session_history(session_id)
    except ImportError:
        logger.debug("compat_router 미로드 — 히스토리 정리 건너뜀")

    return {"message": "세션이 삭제되었습니다.", "session_id": session_id}


@router.post(
    "/sessions/{session_id}/upload",
    response_model=UploadResponse,
)
@limiter.limit(RATE_LIMIT_UPLOAD)
async def upload_document(
    request: Request,
    session_id: str = Path(..., min_length=1, max_length=200),
    file: UploadFile = File(...),
) -> UploadResponse:
    """
    세션에 문서를 업로드합니다.

    지원 형식: pdf, txt, md, csv, docx
    크기 제한: 10MB (기본)
    세션당 최대 5개 문서
    """
    manager = _get_manager()
    pipeline = _get_pipeline()

    # 일일 API 예산 확인 (임베딩 API 1회 소비)
    if not await manager.check_and_increment_api_calls(count=1):
        raise HTTPException(
            status_code=429,
            detail=ErrorCode.DEMO_008.value,
        )

    # 세션 존재 확인
    session = await manager.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorCode.DEMO_002.value,
        )

    # 파일 이름 검증
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail=ErrorCode.DEMO_004.value,
        )

    # Content-Length 헤더 선검증 (있는 경우)
    max_bytes = manager.max_file_size_mb * 1024 * 1024
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=ErrorCode.DEMO_003.value,
        )

    # 청크 단위 파일 읽기 (OOM 방지)
    chunks: list[bytes] = []
    total_size = 0
    while True:
        chunk = await file.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > max_bytes:
            raise HTTPException(
                status_code=400,
                detail=ErrorCode.DEMO_003.value,
            )
        chunks.append(chunk)

    file_bytes = b"".join(chunks)

    # MIME 타입 검증 (실제 파일 내용 기반)
    safe_filename = pathlib.Path(file.filename).name
    file_ext = pathlib.Path(safe_filename).suffix.lstrip(".").lower()
    _validate_mime_type(file_bytes, file_ext)

    try:
        result = await pipeline.ingest_document(
            session_id=session_id,
            file_bytes=file_bytes,
            filename=file.filename,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return UploadResponse(**result)


@router.get(
    "/sessions/{session_id}/documents",
    response_model=DocumentListResponse,
)
@limiter.limit(RATE_LIMIT_READ)
async def list_documents(
    request: Request,
    session_id: str = Path(..., min_length=1, max_length=200),
) -> DocumentListResponse:
    """세션에 업로드된 문서 목록을 반환합니다."""
    manager = _get_manager()
    session = await manager.get_session(session_id)

    if session is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorCode.DEMO_002.value,
        )

    docs = [
        DocumentInfo(filename=name, index=i)
        for i, name in enumerate(session.document_names)
    ]

    return DocumentListResponse(
        session_id=session_id,
        documents=docs,
        total=session.document_count,
        max_documents=manager.max_docs_per_session,
    )


@router.post(
    "/sessions/{session_id}/chat",
    response_model=ChatResponse,
)
@limiter.limit(RATE_LIMIT_CHAT)
async def chat(
    request: Request,
    session_id: str = Path(..., min_length=1, max_length=200),
    body: ChatRequest = Body(...),
) -> ChatResponse:
    """
    RAG 기반 질문 답변 (비스트리밍)

    세션에 업로드된 문서를 검색하여 답변을 생성합니다.
    """
    manager = _get_manager()
    pipeline = _get_pipeline()

    # 일일 API 예산 확인 (임베딩 검색 1 + LLM 생성 1 = 2회)
    if not await manager.check_and_increment_api_calls(count=2):
        raise HTTPException(
            status_code=429,
            detail=ErrorCode.DEMO_008.value,
        )

    try:
        result = await pipeline.query(session_id, body.question)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return ChatResponse(**result)


@router.post("/sessions/{session_id}/chat/stream")
@limiter.limit(RATE_LIMIT_CHAT)
async def chat_stream(
    request: Request,
    session_id: str = Path(..., min_length=1, max_length=200),
    body: ChatRequest = Body(...),
) -> StreamingResponse:
    """
    RAG 기반 질문 답변 (SSE 스트리밍)

    Server-Sent Events 형식으로 실시간 답변을 스트리밍합니다.
    """
    manager = _get_manager()
    pipeline = _get_pipeline()

    # 일일 API 예산 확인 (임베딩 검색 1 + LLM 생성 1 = 2회)
    if not await manager.check_and_increment_api_calls(count=2):
        raise HTTPException(
            status_code=429,
            detail=ErrorCode.DEMO_008.value,
        )

    # 세션 존재 확인 (스트리밍 시작 전 검증)
    session = await manager.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorCode.DEMO_002.value,
        )

    async def event_generator() -> AsyncGenerator[str, None]:
        """SSE 이벤트 생성기"""
        try:
            async for event in pipeline.stream_query(session_id, body.question):
                event_type = event["event"]
                data = json.dumps(event["data"], ensure_ascii=False)
                yield f"event: {event_type}\ndata: {data}\n\n"
        except Exception as e:
            logger.error(f"스트리밍 오류: {e}", exc_info=True)
            error_data = json.dumps(
                {"error": ErrorCode.DEMO_005.value}, ensure_ascii=False
            )
            yield f"event: error\ndata: {error_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/stats", response_model=StatsResponse)
@limiter.limit(RATE_LIMIT_READ)
async def get_stats(request: Request) -> StatsResponse:
    """데모 서비스 통계를 반환합니다."""
    manager = _get_manager()
    stats = await manager.get_stats()

    return StatsResponse(
        active_sessions=stats.active_sessions,
        max_sessions=stats.max_sessions,
        ttl_seconds=stats.ttl_seconds,
        total_sessions_created=stats.total_sessions_created,
        total_sessions_expired=stats.total_sessions_expired,
        total_documents_uploaded=stats.total_documents_uploaded,
        daily_api_calls=stats.daily_api_calls,
        daily_api_limit=stats.daily_api_limit,
        allowed_file_types=sorted(ALLOWED_EXTENSIONS),
    )
