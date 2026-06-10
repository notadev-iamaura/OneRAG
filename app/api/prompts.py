"""
프롬프트 관리 API 엔드포인트
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..lib.auth import get_api_key
from ..lib.logger import get_logger
from ..models.prompts import PromptCreate, PromptListResponse, PromptResponse, PromptUpdate

# 순환 임포트 방지: 타입 힌트용으로만 임포트
if TYPE_CHECKING:
    from ..core.di_container import AppContainer

logger = get_logger(__name__)
# ✅ H2 보안 패치: GET(읽기)은 공개, POST/PUT/DELETE(쓰기)는 인증 필요
# 라우터 레벨 인증 대신 개별 엔드포인트에 적용
router = APIRouter(prefix="/api/prompts", tags=["Prompts"])


# 공유 DI 컨테이너 (main.py lifespan에서 주입)
# 새 AppContainer() 생성을 막아 PromptManager가 실행 중 파이프라인과 동일한
# 설정(use_database 등)을 공유하게 한다 (관리 API와 RAG의 split-brain 방지).
_shared_container: AppContainer | None = None


def set_container(container: AppContainer) -> None:
    """공유 DI 컨테이너 주입 (main.py lifespan에서 호출)"""
    global _shared_container
    _shared_container = container


def _get_container() -> AppContainer:
    """공유 컨테이너를 반환한다 (미주입 시 경고 후 새 인스턴스 — 테스트 폴백)"""
    if _shared_container is not None:
        return _shared_container
    from ..core.di_container import AppContainer

    logger.warning("공유 컨테이너 미주입 — 새 AppContainer 생성 (설정이 비어 있을 수 있음)")
    return AppContainer()


@router.get(
    "",
    response_model=PromptListResponse,
    summary="프롬프트 목록 조회",
    description="프롬프트 목록을 조회합니다. /api/prompts 또는 /api/prompts/ 두 경로 모두 사용 가능합니다.",
)
@router.get("/", response_model=PromptListResponse, include_in_schema=False)
async def list_prompts(
    category: str | None = Query(None, description="카테고리 필터"),
    is_active: bool | None = Query(None, description="활성화 상태 필터"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(50, ge=1, le=100, description="페이지 크기"),
):
    """
    프롬프트 목록 조회

    - **category**: 카테고리로 필터링 (system, style 등)
    - **is_active**: 활성화 상태로 필터링
    - **page**: 페이지 번호 (기본값: 1)
    - **page_size**: 페이지 크기 (기본값: 50, 최대: 100)
    """
    try:
        container = _get_container()
        prompt_manager = container.prompt_manager()
        result = await prompt_manager.list_prompts(
            category=category, is_active=is_active, page=page, page_size=page_size
        )
        return PromptListResponse(**result)
    except Exception as e:
        logger.error(f"Error listing prompts: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


@router.get("/{prompt_id}", response_model=PromptResponse)
async def get_prompt(prompt_id: str):
    """
    특정 프롬프트 조회

    - **prompt_id**: 프롬프트 고유 ID
    """
    try:
        container = _get_container()
        prompt_manager = container.prompt_manager()
        prompt = await prompt_manager.get_prompt(prompt_id=prompt_id)
        if not prompt:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Prompt {prompt_id} not found"
            )
        return prompt
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting prompt: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


@router.get("/by-name/{name}", response_model=PromptResponse)
async def get_prompt_by_name(name: str):
    """
    이름으로 프롬프트 조회

    - **name**: 프롬프트 이름
    """
    try:
        container = _get_container()
        prompt_manager = container.prompt_manager()
        prompt = await prompt_manager.get_prompt(name=name)
        if not prompt:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Prompt with name '{name}' not found"
            )
        return prompt
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting prompt by name: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


# ✅ H2 보안 패치: POST(생성) 인증 필요
@router.post(
    "",
    response_model=PromptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="프롬프트 생성",
    description="새 프롬프트를 생성합니다. /api/prompts 또는 /api/prompts/ 두 경로 모두 사용 가능합니다.",
    dependencies=[Depends(get_api_key)],
)
@router.post(
    "/", response_model=PromptResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False,
    dependencies=[Depends(get_api_key)],
)
async def create_prompt(prompt_data: PromptCreate):
    """
    새 프롬프트 생성

    - **name**: 프롬프트 이름 (고유해야 함)
    - **content**: 프롬프트 내용
    - **description**: 프롬프트 설명 (선택사항)
    - **category**: 카테고리 (기본값: system)
    - **is_active**: 활성화 여부 (기본값: true)
    """
    try:
        container = _get_container()
        prompt_manager = container.prompt_manager()
        prompt = await prompt_manager.create_prompt(prompt_data)
        return prompt
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error creating prompt: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


# ✅ H2 보안 패치: PUT(수정) 인증 필요
@router.put("/{prompt_id}", response_model=PromptResponse, dependencies=[Depends(get_api_key)])
async def update_prompt(prompt_id: str, update_data: PromptUpdate):
    """
    프롬프트 업데이트

    - **prompt_id**: 프롬프트 고유 ID
    - 업데이트할 필드만 전달하면 됨
    """
    try:
        container = _get_container()
        prompt_manager = container.prompt_manager()
        prompt = await prompt_manager.update_prompt(prompt_id, update_data)
        return prompt
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error updating prompt: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


# ✅ H2 보안 패치: DELETE(삭제) 인증 필요
@router.delete("/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(get_api_key)])
async def delete_prompt(prompt_id: str):
    """
    프롬프트 삭제

    - **prompt_id**: 프롬프트 고유 ID
    - 기본 시스템 프롬프트는 삭제할 수 없음
    """
    try:
        container = _get_container()
        prompt_manager = container.prompt_manager()
        await prompt_manager.delete_prompt(prompt_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error deleting prompt: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


@router.get("/export/all")
async def export_prompts():
    """
    모든 프롬프트 내보내기 (백업용)
    """
    try:
        container = _get_container()
        prompt_manager = container.prompt_manager()
        data = await prompt_manager.export_prompts()
        return data
    except Exception as e:
        logger.error(f"Error exporting prompts: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


# ✅ H2 보안 패치: import도 데이터 수정이므로 인증 필요
@router.post("/import", dependencies=[Depends(get_api_key)])
async def import_prompts(
    data: dict, overwrite: bool = Query(False, description="기존 프롬프트 덮어쓰기 여부")
):
    """
    프롬프트 가져오기 (복원용)

    - **data**: export_prompts로 내보낸 데이터
    - **overwrite**: 동일한 이름의 프롬프트가 있을 경우 덮어쓸지 여부
    """
    try:
        container = _get_container()
        prompt_manager = container.prompt_manager()
        result = await prompt_manager.import_prompts(data, overwrite=overwrite)
        return result
    except Exception as e:
        logger.error(f"Error importing prompts: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e
