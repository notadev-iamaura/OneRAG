"""
Tools Router - Tool Use API 엔드포인트
LLM Tool Use (Function Calling) 기능을 위한 API 라우터

## 제공 엔드포인트
- GET /api/tools - 사용 가능한 Tool 목록 조회
- GET /api/tools/{tool_name} - 특정 Tool 상세 정보 조회
- POST /api/tools/{tool_name}/execute - Tool 실행
"""

import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...lib.auth import get_api_key
from ...lib.errors import ErrorCode, get_error_message
from ...lib.logger import get_logger
from ...modules.core.tools import ToolExecutionResult, ToolExecutor

logger = get_logger(__name__)
router = APIRouter()
tool_executor: ToolExecutor | None = None


def _resolve_request_language(request: Request | None) -> str:
    """요청 Accept-Language 헤더에서 에러 메시지 언어를 결정한다(ko|en, 기본 ko).

    양언어 에러 카탈로그(app.lib.errors)는 "ko"/"en"만 지원한다. 헤더가 영어를
    우선하면 "en"을, 그 외(미지정/요청 없음 포함)는 "ko"를 반환한다 → 한국어
    기본(회귀 0). evaluations/chat_router와 동일한 패턴을 따른다.

    Args:
        request: FastAPI 요청 객체 (의존성 주입 실패 등으로 None일 수 있음)

    Returns:
        에러 메시지 언어 코드 ("ko" 또는 "en")
    """
    if request is None:
        return "ko"
    accept_language = (request.headers.get("accept-language") or "").lower()
    en_idx = accept_language.find("en")
    ko_idx = accept_language.find("ko")
    if en_idx != -1 and (ko_idx == -1 or en_idx < ko_idx):
        return "en"
    return "ko"


def set_tool_executor(executor: ToolExecutor) -> None:
    """ToolExecutor 의존성 주입"""
    global tool_executor
    tool_executor = executor
    logger.info("ToolExecutor 주입 완료")


class ToolExecuteRequest(BaseModel):
    """Tool 실행 요청"""

    parameters: dict[str, Any] = Field(..., description="Tool 실행 파라미터")
    context: dict[str, Any] | None = Field(None, description="요청 컨텍스트 정보 (선택사항)")


class ToolExecuteResponse(BaseModel):
    """Tool 실행 응답"""

    success: bool = Field(..., description="실행 성공 여부")
    tool_name: str = Field(..., description="실행된 Tool 이름")
    data: dict[str, Any] | None = Field(None, description="실행 결과 데이터")
    error: dict[str, str] | None = Field(None, description="에러 정보")
    execution_time_ms: float | None = Field(None, description="실행 시간 (밀리초)")
    metadata: dict[str, Any] | None = Field(None, description="메타데이터")
    request_id: str = Field(..., description="요청 ID")


class ToolInfoResponse(BaseModel):
    """Tool 정보 응답"""

    name: str = Field(..., description="Tool 이름")
    display_name: str = Field(..., description="Tool 표시 이름")
    category: str = Field(..., description="Tool 카테고리")
    description: str = Field(..., description="Tool 설명")
    parameters: dict[str, Any] = Field(..., description="Tool 파라미터 스키마")
    metadata: dict[str, Any] | None = Field(None, description="메타데이터")


class ToolListResponse(BaseModel):
    """Tool 목록 응답"""

    tools: list[dict[str, Any]] = Field(..., description="Tool 목록")
    total_count: int = Field(..., description="전체 Tool 수")


@router.get("/tools", response_model=ToolListResponse)
async def get_tools(request: Request, category: str | None = None) -> ToolListResponse:
    """
    사용 가능한 Tool 목록 조회

    Args:
        request: FastAPI 요청 객체 (Accept-Language 기반 에러 언어 결정용)
        category: 카테고리 필터 (선택사항)

    Returns:
        Tool 목록
    """
    lang = _resolve_request_language(request)
    try:
        if not tool_executor:
            raise HTTPException(
                status_code=500, detail=get_error_message(ErrorCode.TOOL_001.value, lang)
            )
        tools = tool_executor.get_available_tools()
        if category:
            tools = [tool for tool in tools if tool.get("category") == category]
        logger.info(f"Tool 목록 조회 완료: {len(tools)}개")
        return ToolListResponse(tools=tools, total_count=len(tools))
    except Exception as e:
        logger.error(f"Tool 목록 조회 실패: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=get_error_message(ErrorCode.TOOL_002.value, lang),
        ) from e


@router.get("/tools/{tool_name}", response_model=ToolInfoResponse)
async def get_tool_info(request: Request, tool_name: str) -> ToolInfoResponse:
    """
    특정 Tool의 상세 정보 조회

    Args:
        request: FastAPI 요청 객체 (Accept-Language 기반 에러 언어 결정용)
        tool_name: Tool 이름

    Returns:
        Tool 상세 정보
    """
    lang = _resolve_request_language(request)
    try:
        if not tool_executor:
            raise HTTPException(
                status_code=500, detail=get_error_message(ErrorCode.TOOL_001.value, lang)
            )
        tool_info = tool_executor.get_tool_info(tool_name)
        if not tool_info:
            raise HTTPException(
                status_code=404,
                detail=get_error_message(ErrorCode.TOOL_003.value, lang, tool_name=tool_name),
            )
        logger.info(f"Tool 정보 조회 완료: {tool_name}")
        return ToolInfoResponse(**tool_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Tool 정보 조회 실패: {tool_name} - {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=get_error_message(ErrorCode.TOOL_004.value, lang),
        ) from e


# ✅ H3 보안 패치: Tool 실행은 위험할 수 있으므로 인증 필요
@router.post("/tools/{tool_name}/execute", response_model=ToolExecuteResponse, dependencies=[Depends(get_api_key)])
async def execute_tool(
    http_request: Request, tool_name: str, request: ToolExecuteRequest
) -> ToolExecuteResponse:
    """
    Tool 실행

    Args:
        http_request: FastAPI 요청 객체 (Accept-Language 기반 에러 언어 결정용)
        tool_name: 실행할 Tool 이름
        request: Tool 실행 요청

    Returns:
        Tool 실행 결과
    """
    lang = _resolve_request_language(http_request)
    request_id = str(uuid4())
    start_time = time.time()
    try:
        if not tool_executor:
            raise HTTPException(
                status_code=500, detail=get_error_message(ErrorCode.TOOL_001.value, lang)
            )
        logger.info(f"Tool 실행 요청: {tool_name} (request_id: {request_id})")
        parameters = request.parameters.copy()
        if request.context:
            parameters["context"] = request.context
        result: ToolExecutionResult = await tool_executor.execute_tool(
            tool_name=tool_name, parameters=parameters
        )
        total_time_ms = (time.time() - start_time) * 1000
        logger.info(
            f"Tool 실행 완료: {tool_name} (성공: {result.success}, 전체 시간: {total_time_ms:.0f}ms)"
        )
        return ToolExecuteResponse(
            success=result.success,
            tool_name=result.tool_name,
            data=result.data,
            error=result.error,
            execution_time_ms=result.execution_time_ms,
            metadata=result.metadata,
            request_id=request_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        total_time_ms = (time.time() - start_time) * 1000
        logger.error(f"Tool 실행 예외 발생: {tool_name} - {str(e)} (request_id: {request_id})")
        return ToolExecuteResponse(
            success=False,
            tool_name=tool_name,
            data=None,
            error={
                "code": "EXECUTION_EXCEPTION",
                "message": get_error_message(ErrorCode.TOOL_005.value, lang, error=str(e)),
            },
            execution_time_ms=total_time_ms,
            metadata=None,
            request_id=request_id,
        )


@router.get("/tools/health")
async def tools_health_check() -> dict[str, Any]:
    """
    Tool Use 시스템 헬스 체크

    Returns:
        시스템 상태 정보
    """
    try:
        is_initialized = tool_executor is not None
        tools_count = len(tool_executor.get_available_tools()) if is_initialized else 0  # type: ignore[union-attr]
        return {
            "status": "healthy" if is_initialized else "not_initialized",
            "tool_executor_initialized": is_initialized,
            "available_tools_count": tools_count,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Tool Use 헬스 체크 실패: {str(e)}")
        return {"status": "unhealthy", "error": str(e), "timestamp": time.time()}
