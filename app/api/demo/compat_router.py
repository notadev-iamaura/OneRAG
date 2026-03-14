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

async def _resolve_session(request: Request) -> str:
    """X-Session-Id 헤더 기반 세션 반환 (없으면 생성)

    유저별 독립 ChromaDB 컬렉션을 보장합니다.
    동일 브라우저(=동일 X-Session-Id)는 항상 같은 컬렉션을 사용합니다.
    서버 재시작 후 세션이 유실되면 자동으로 새 세션을 생성합니다.
    """
    manager = _get_manager()

    session_id = request.headers.get("x-session-id", "")
    if session_id:
        session = await manager.get_session(session_id)
        if session is not None:
            return session_id

    # 세션 미존재 또는 헤더 없음 → 새 세션 생성
    session = await manager.create_session()
    logger.info(f"세션 자동 생성: {session.session_id[:8]}")
    return session.session_id


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

    # 일일 API 예산 확인 (임베딩 검색 1 + LLM 생성 1 = 2회)
    if not await manager.check_and_increment_api_calls(count=2):
        raise HTTPException(
            status_code=429,
            detail=ErrorCode.DEMO_008.value,
        )

    # body.session_id로 파이프라인 질의 (세션 생성 시 재사용되므로 업로드 컬렉션과 동일)
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
            relevance=src.get("relevance", 0.8),
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

    # X-Session-Id 헤더가 있고 해당 세션이 존재하면 재사용
    # → 업로드된 문서가 있는 세션을 유지하여 채팅에서 검색 가능
    existing_session_id = request.headers.get("x-session-id", "")
    if existing_session_id:
        session = await manager.get_session(existing_session_id)
        if session is not None:
            logger.info(f"기존 세션 재사용: {existing_session_id[:8]}")
            return {
                "session_id": session.session_id,
                "created_at": datetime.fromtimestamp(
                    session.created_at, tz=UTC
                ).isoformat(),
                "message_count": len(
                    _chat_history.get(session.session_id, [])
                ),
                "last_activity": datetime.fromtimestamp(
                    session.last_accessed, tz=UTC
                ).isoformat(),
            }

    # 기존 세션 없으면 새로 생성
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


# =============================================================================
# 프롬프트 관리 엔드포인트 (인메모리)
# =============================================================================

# 인메모리 프롬프트 저장소
_prompts: dict[str, dict[str, Any]] = {}


def _default_prompts() -> list[dict[str, Any]]:
    """기본 시스템 프롬프트 (서버 시작 시 초기화)"""
    now = datetime.now(tz=UTC).isoformat()
    return [
        {
            "id": str(uuid.uuid4()),
            "name": "default-system",
            "content": (
                "당신은 RAG 기반 질문 답변 시스템입니다. "
                "제공된 문서를 기반으로 정확하고 도움이 되는 답변을 작성하세요."
            ),
            "description": "기본 시스템 프롬프트",
            "category": "system",
            "is_active": True,
            "metadata": {},
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "concise-style",
            "content": "핵심만 간결하게 답변하세요. 불필요한 설명은 생략합니다.",
            "description": "간결한 답변 스타일",
            "category": "style",
            "is_active": False,
            "metadata": {},
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "detailed-style",
            "content": (
                "상세하고 포괄적으로 답변하세요. "
                "관련 배경 지식과 예시를 포함하여 설명합니다."
            ),
            "description": "상세한 답변 스타일",
            "category": "style",
            "is_active": False,
            "metadata": {},
            "created_at": now,
            "updated_at": now,
        },
    ]


def _init_prompts() -> None:
    """프롬프트 초기화 (빈 경우만)"""
    if not _prompts:
        for p in _default_prompts():
            _prompts[p["id"]] = p


class PromptCreateRequest(BaseModel):
    """프롬프트 생성 요청"""

    name: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    description: str = Field(default="")
    category: str = Field(default="custom")
    is_active: bool = Field(default=False)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptUpdateRequest(BaseModel):
    """프롬프트 수정 요청"""

    name: str | None = None
    content: str | None = None
    description: str | None = None
    category: str | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


@compat_router.get("/prompts")
@limiter.limit(RATE_LIMIT_READ)
async def list_prompts(
    request: Request,
    category: str | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """프롬프트 목록 조회 (인메모리)"""
    _init_prompts()

    results = list(_prompts.values())

    # 필터링
    if category:
        results = [p for p in results if p["category"] == category]
    if is_active is not None:
        results = [p for p in results if p["is_active"] == is_active]
    if search:
        q = search.lower()
        results = [
            p for p in results
            if q in p["name"].lower() or q in p.get("description", "").lower()
        ]

    total = len(results)
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "prompts": results[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@compat_router.get("/prompts/export/all")
@limiter.limit(RATE_LIMIT_READ)
async def export_prompts(request: Request) -> dict[str, Any]:
    """프롬프트 전체 내보내기"""
    _init_prompts()
    all_prompts = list(_prompts.values())
    return {
        "prompts": all_prompts,
        "exported_at": datetime.now(tz=UTC).isoformat(),
        "total": len(all_prompts),
    }


@compat_router.get("/prompts/by-name/{name}")
@limiter.limit(RATE_LIMIT_READ)
async def get_prompt_by_name(
    request: Request,
    name: str = Path(..., min_length=1),
) -> dict[str, Any]:
    """이름으로 프롬프트 조회"""
    _init_prompts()
    for p in _prompts.values():
        if p["name"] == name:
            return p
    raise HTTPException(status_code=404, detail="프롬프트를 찾을 수 없습니다.")


@compat_router.get("/prompts/{prompt_id}")
@limiter.limit(RATE_LIMIT_READ)
async def get_prompt(
    request: Request,
    prompt_id: str = Path(..., min_length=1),
) -> dict[str, Any]:
    """프롬프트 상세 조회"""
    _init_prompts()
    prompt = _prompts.get(prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="프롬프트를 찾을 수 없습니다.")
    return prompt


@compat_router.post("/prompts")
@limiter.limit(RATE_LIMIT_SESSION)
async def create_prompt(
    request: Request, body: PromptCreateRequest
) -> dict[str, Any]:
    """프롬프트 생성"""
    _init_prompts()

    # 이름 중복 검사
    for p in _prompts.values():
        if p["name"] == body.name:
            raise HTTPException(
                status_code=409, detail="같은 이름의 프롬프트가 이미 존재합니다."
            )

    now = datetime.now(tz=UTC).isoformat()

    # 활성화 요청 시 기존 활성 프롬프트 비활성화
    if body.is_active:
        for p in _prompts.values():
            p["is_active"] = False

    prompt: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": body.name,
        "content": body.content,
        "description": body.description,
        "category": body.category,
        "is_active": body.is_active,
        "metadata": body.metadata,
        "created_at": now,
        "updated_at": now,
    }
    _prompts[prompt["id"]] = prompt
    return prompt


@compat_router.put("/prompts/{prompt_id}")
@limiter.limit(RATE_LIMIT_SESSION)
async def update_prompt(
    request: Request,
    body: PromptUpdateRequest,
    prompt_id: str = Path(..., min_length=1),
) -> dict[str, Any]:
    """프롬프트 수정"""
    _init_prompts()

    prompt = _prompts.get(prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="프롬프트를 찾을 수 없습니다.")

    # 활성화 토글: 새로 활성화하면 나머지 비활성화
    if body.is_active is True and not prompt["is_active"]:
        for p in _prompts.values():
            p["is_active"] = False

    # 필드 업데이트 (None이 아닌 값만)
    update_fields = body.model_dump(exclude_none=True)
    prompt.update(update_fields)
    prompt["updated_at"] = datetime.now(tz=UTC).isoformat()

    return prompt


@compat_router.delete("/prompts/{prompt_id}")
@limiter.limit(RATE_LIMIT_SESSION)
async def delete_prompt(
    request: Request,
    prompt_id: str = Path(..., min_length=1),
) -> dict[str, str]:
    """프롬프트 삭제"""
    _init_prompts()

    if prompt_id not in _prompts:
        raise HTTPException(status_code=404, detail="프롬프트를 찾을 수 없습니다.")

    del _prompts[prompt_id]
    return {"message": "프롬프트가 삭제되었습니다."}


@compat_router.post("/prompts/import")
@limiter.limit(RATE_LIMIT_SESSION)
async def import_prompts(
    request: Request,
    overwrite: bool = False,
) -> dict[str, Any]:
    """프롬프트 가져오기"""
    _init_prompts()

    raw_body = await request.json()
    imported_prompts = raw_body.get("prompts", [])

    if overwrite:
        _prompts.clear()

    count = 0
    now = datetime.now(tz=UTC).isoformat()
    for p in imported_prompts:
        new_id = str(uuid.uuid4())
        _prompts[new_id] = {
            "id": new_id,
            "name": p.get("name", "imported"),
            "content": p.get("content", ""),
            "description": p.get("description", ""),
            "category": p.get("category", "custom"),
            "is_active": False,
            "metadata": p.get("metadata", {}),
            "created_at": now,
            "updated_at": now,
        }
        count += 1

    return {"message": f"{count}개 프롬프트를 가져왔습니다.", "imported": count}


# =============================================================================
# 문서 관리 엔드포인트 (인메모리)
# =============================================================================

# 인메모리 문서 저장소 (업로드된 문서 메타데이터)
_documents: dict[str, dict[str, Any]] = {}

# 업로드 작업 상태 저장소
_upload_jobs: dict[str, dict[str, Any]] = {}


@compat_router.get("/upload/documents")
@limiter.limit(RATE_LIMIT_READ)
async def list_documents(
    request: Request,
    page: int = 1,
    limit: int = 50,
    search: str = "",
    status: str | None = None,
) -> dict[str, Any]:
    """문서 목록 조회 (인메모리)"""
    results = list(_documents.values())

    # 검색 필터
    if search:
        q = search.lower()
        results = [d for d in results if q in d["filename"].lower()]

    # 상태 필터
    if status:
        results = [d for d in results if d["status"] == status]

    # 최신순 정렬
    results.sort(key=lambda d: d["upload_date"], reverse=True)

    total = len(results)
    start = (page - 1) * limit
    end = start + limit

    return {"documents": results[start:end], "total": total}


@compat_router.get("/upload/documents/{doc_id}")
@limiter.limit(RATE_LIMIT_READ)
async def get_document(
    request: Request,
    doc_id: str = Path(..., min_length=1),
) -> dict[str, Any]:
    """문서 상세 조회"""
    doc = _documents.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return doc


@compat_router.post("/upload")
@limiter.limit(RATE_LIMIT_SESSION)
async def upload_document_compat(request: Request) -> dict[str, Any]:
    """
    문서 업로드 (파이프라인 인제스트 + 인메모리 메타데이터 저장)

    프론트엔드가 X-Session-Id 헤더로 전송하는 세션 ID를 사용하여
    실제 RAG 파이프라인에 문서를 인제스트합니다.
    텍스트 추출 → 청킹 → 임베딩 → ChromaDB 저장까지 수행하여
    이후 채팅에서 검색 가능하게 합니다.
    """
    pipeline = _get_pipeline()
    manager = _get_manager()

    form = await request.form()
    file = form.get("file")

    if file is None:
        raise HTTPException(status_code=400, detail="파일이 필요합니다.")

    # X-Session-Id 기반 유저별 세션 사용 (업로드/채팅 동일 컬렉션 보장)
    session_id = await _resolve_session(request)

    # 일일 API 예산 확인 (임베딩 API 1회 소비)
    if not await manager.check_and_increment_api_calls(count=1):
        raise HTTPException(
            status_code=429, detail=ErrorCode.DEMO_008.value
        )

    # 파일 메타데이터 추출
    filename = getattr(file, "filename", "unknown")
    content_type = getattr(file, "content_type", "application/octet-stream")

    # 파일 바이트 읽기
    file_bytes = await file.read()  # type: ignore[union-attr]
    file_size = len(file_bytes)

    # 파이프라인에 실제 인제스트 (텍스트 추출 → 청킹 → 임베딩 → ChromaDB 저장)
    start_time = time.time()
    try:
        result = await pipeline.ingest_document(
            session_id=session_id,
            file_bytes=file_bytes,
            filename=filename,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    processing_time = time.time() - start_time
    chunk_count = result["chunks"]

    # 인메모리 문서 메타데이터 등록 (프론트엔드 문서 관리 탭용)
    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    now = datetime.now(tz=UTC).isoformat()

    _documents[doc_id] = {
        "id": doc_id,
        "filename": filename,
        "file_type": content_type,
        "file_size": file_size,
        "upload_date": now,
        "status": "completed",
        "chunk_count": chunk_count,
        "processing_time": round(processing_time, 2),
        "error_message": None,
    }

    # 업로드 작업 상태 기록
    _upload_jobs[job_id] = {
        "job_id": job_id,
        "status": "completed",
        "progress": 100,
        "message": f"'{filename}' 업로드 완료 ({chunk_count}개 청크)",
        "filename": filename,
        "chunk_count": chunk_count,
        "processing_time": round(processing_time, 2),
        "error_message": None,
        "timestamp": now,
        "documentId": doc_id,
    }

    logger.info(
        f"호환 업로드 완료: {filename} → {chunk_count}개 청크 "
        f"(세션: {session_id[:8]}, 소요: {processing_time:.1f}s)"
    )

    return {"success": True, "jobId": job_id, "message": f"'{filename}' 업로드 완료"}


@compat_router.get("/upload/status/{job_id}")
@limiter.limit(RATE_LIMIT_READ)
async def get_upload_status(
    request: Request,
    job_id: str = Path(..., min_length=1),
) -> dict[str, Any]:
    """업로드 작업 상태 조회"""
    job = _upload_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="업로드 작업을 찾을 수 없습니다.")
    return job


@compat_router.delete("/upload/documents/{doc_id}")
@limiter.limit(RATE_LIMIT_SESSION)
async def delete_document(
    request: Request,
    doc_id: str = Path(..., min_length=1),
) -> dict[str, str]:
    """문서 삭제 (단일)"""
    if doc_id not in _documents:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    del _documents[doc_id]
    return {"message": "문서가 삭제되었습니다."}


@compat_router.post("/upload/documents/bulk-delete")
@limiter.limit(RATE_LIMIT_SESSION)
async def bulk_delete_documents(request: Request) -> dict[str, Any]:
    """문서 일괄 삭제"""
    body = await request.json()
    ids = body.get("ids", [])
    deleted = 0
    for doc_id in ids:
        if doc_id in _documents:
            del _documents[doc_id]
            deleted += 1
    return {"message": f"{deleted}개 문서가 삭제되었습니다.", "deleted": deleted}


@compat_router.delete("/documents/all")
@limiter.limit(RATE_LIMIT_SESSION)
async def delete_all_documents(
    request: Request,
    dry_run: bool = False,
) -> dict[str, Any]:
    """전체 문서 삭제"""
    count = len(_documents)
    if not dry_run:
        _documents.clear()
    return {"message": f"{count}개 문서가 삭제되었습니다.", "deleted": count, "dry_run": dry_run}
