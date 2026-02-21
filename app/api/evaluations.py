"""
평가 시스템 API 엔드포인트

사용자 쿼리와 LLM 응답에 대한 평가를 수집하고 관리하는 API
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..infrastructure.persistence.evaluation_manager import (
    DuplicateEvaluationError,
    EvaluationDataManager,
)
from ..lib.auth import get_api_key
from ..lib.logger import get_logger
from ..models.evaluation import (
    EvaluationCreate,
    EvaluationFilter,
    EvaluationResponse,
    EvaluationStatistics,
    EvaluationUpdate,
)

logger = get_logger(__name__)
router = APIRouter(dependencies=[Depends(get_api_key)])
_evaluation_module: EvaluationDataManager | None = None


def get_evaluation_module() -> EvaluationDataManager:
    """평가 데이터 관리자 의존성 주입"""
    if _evaluation_module is None:
        raise HTTPException(status_code=500, detail="평가 모듈이 초기화되지 않았습니다")
    return _evaluation_module


def init_evaluation_router(evaluation_module: EvaluationDataManager) -> APIRouter:
    """
    평가 라우터 초기화

    Args:
        evaluation_module: 평가 데이터 관리자 인스턴스

    Returns:
        초기화된 라우터
    """
    global _evaluation_module
    _evaluation_module = evaluation_module
    module_type = type(evaluation_module).__name__
    backend_type = "PostgreSQL" if hasattr(evaluation_module, "db_manager") else "In-Memory"
    logger.info(f"✅ 평가 라우터 초기화 완료: {backend_type} 백엔드 사용 (모듈: {module_type})")
    return router


@router.get("/health")
async def evaluation_health(
    evaluation_module: EvaluationDataManager = Depends(get_evaluation_module),
):
    """
    평가 모듈 상태 확인

    Returns:
        평가 모듈의 현재 상태 정보
    """
    module_type = type(evaluation_module).__name__
    health_info = {
        "status": "healthy",
        "module_type": module_type,
        "backend": "postgresql" if hasattr(evaluation_module, "db_manager") else "in-memory",
        "timestamp": datetime.utcnow().isoformat(),
    }
    if hasattr(evaluation_module, "db_manager"):
        try:
            async with evaluation_module.db_manager.get_session() as session:
                from sqlalchemy import text

                await session.execute(text("SELECT 1"))
                health_info["db_connection"] = "ok"
        except Exception as e:
            health_info["status"] = "degraded"
            health_info["db_connection"] = f"failed: {str(e)}"
            logger.error(f"PostgreSQL 연결 확인 실패: {e}")
    return health_info


@router.post("", response_model=EvaluationResponse, status_code=201)
async def create_evaluation(
    evaluation_data: EvaluationCreate,
    evaluation_module: EvaluationDataManager = Depends(get_evaluation_module),
):
    """
    새 평가 생성

    평가 점수 범위: 1-5점
    - 1점: 매우 나쁨
    - 2점: 나쁨
    - 3점: 보통
    - 4점: 좋음
    - 5점: 매우 좋음
    """
    try:
        logger.info(
            f"평가 생성 요청: 세션={evaluation_data.session_id}, 메시지={evaluation_data.message_id}"
        )
        evaluation = await evaluation_module.create_evaluation(evaluation_data)
        logger.info(f"평가 생성 완료: {evaluation.evaluation_id}")
        return evaluation
    except DuplicateEvaluationError as e:
        logger.warning("평가 생성 실패 - 중복 message_id: %s", e.message_id)
        raise HTTPException(
            status_code=409,
            detail={
                "message": "동일한 message_id에 대한 평가가 이미 존재합니다",
                "existing_evaluation_id": e.evaluation_id,
                "message_id": e.message_id,
            },
        ) from e
    except ValueError as e:
        logger.error(f"평가 생성 실패 - 유효성 검증 오류: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"평가 생성 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="평가 생성 중 오류가 발생했습니다") from e


@router.get("/{evaluation_id}", response_model=EvaluationResponse)
async def get_evaluation(
    evaluation_id: str, evaluation_module: EvaluationDataManager = Depends(get_evaluation_module)
):
    """특정 평가 조회"""
    evaluation = await evaluation_module.get_evaluation(evaluation_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="평가를 찾을 수 없습니다")
    return evaluation


@router.get("/message/{message_id}", response_model=EvaluationResponse)
async def get_evaluation_by_message(
    message_id: str, evaluation_module: EvaluationDataManager = Depends(get_evaluation_module)
):
    """메시지 ID로 평가 조회"""
    evaluation = await evaluation_module.get_evaluation_by_message(message_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="해당 메시지에 대한 평가를 찾을 수 없습니다")
    return evaluation


@router.get("/session/{session_id}", response_model=list[EvaluationResponse])
async def get_session_evaluations(
    session_id: str,
    skip: int = Query(0, ge=0, description="건너뛸 개수"),
    limit: int = Query(20, ge=1, le=100, description="조회할 최대 개수"),
    evaluation_module: EvaluationDataManager = Depends(get_evaluation_module),
):
    """세션의 평가 목록 조회"""
    try:
        evaluations = await evaluation_module.get_session_evaluations(
            session_id=session_id, skip=skip, limit=limit
        )
        logger.info(f"세션 {session_id}의 평가 {len(evaluations)}개 조회")
        return evaluations
    except Exception as e:
        logger.error(f"세션 평가 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="평가 조회 중 오류가 발생했습니다") from e


@router.put("/{evaluation_id}", response_model=EvaluationResponse)
async def update_evaluation(
    evaluation_id: str,
    update_data: EvaluationUpdate,
    evaluation_module: EvaluationDataManager = Depends(get_evaluation_module),
):
    """평가 정보 업데이트"""
    try:
        evaluation = await evaluation_module.update_evaluation(evaluation_id, update_data)
        if not evaluation:
            raise HTTPException(status_code=404, detail="평가를 찾을 수 없습니다")
        logger.info(f"평가 업데이트 완료: {evaluation_id}")
        return evaluation
    except ValueError as e:
        logger.error(f"평가 업데이트 실패 - 유효성 검증 오류: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"평가 업데이트 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="평가 업데이트 중 오류가 발생했습니다") from e


@router.delete("/{evaluation_id}", status_code=204)
async def delete_evaluation(
    evaluation_id: str, evaluation_module: EvaluationDataManager = Depends(get_evaluation_module)
):
    """평가 삭제"""
    success = await evaluation_module.delete_evaluation(evaluation_id)
    if not success:
        raise HTTPException(status_code=404, detail="평가를 찾을 수 없습니다")
    logger.info(f"평가 삭제 완료: {evaluation_id}")
    return Response(status_code=204)


@router.get("/stats/summary", response_model=EvaluationStatistics)
async def get_evaluation_statistics(
    session_id: str | None = Query(None, description="특정 세션 필터링"),
    evaluator_id: str | None = Query(None, description="특정 평가자 필터링"),
    min_score: int | None = Query(None, ge=1, le=5, description="최소 점수"),
    max_score: int | None = Query(None, ge=1, le=5, description="최대 점수"),
    start_date: datetime | None = Query(None, description="시작 날짜"),
    end_date: datetime | None = Query(None, description="종료 날짜"),
    has_feedback: bool | None = Query(None, description="피드백 유무"),
    use_cache: bool = Query(True, description="캐시 사용 여부"),
    evaluation_module: EvaluationDataManager = Depends(get_evaluation_module),
):
    """
    평가 통계 조회

    다양한 필터 조건을 적용하여 통계를 조회할 수 있습니다.
    캐시를 사용하면 성능이 향상되지만, 실시간 정확도는 떨어질 수 있습니다.
    """
    try:
        filter_params = None
        if any(
            [
                session_id,
                evaluator_id,
                min_score,
                max_score,
                start_date,
                end_date,
                has_feedback is not None,
            ]
        ):
            filter_params = EvaluationFilter(
                session_id=session_id,
                evaluator_id=evaluator_id,
                min_score=min_score,
                max_score=max_score,
                start_date=start_date,
                end_date=end_date,
                has_feedback=has_feedback,
            )
        stats = await evaluation_module.get_statistics(
            filter_params=filter_params, use_cache=use_cache
        )
        logger.info(f"평가 통계 조회: 전체 {stats.total_evaluations}개")
        return stats
    except Exception as e:
        logger.error(f"통계 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="통계 조회 중 오류가 발생했습니다") from e


@router.get("/export/{format}")
async def export_evaluations(
    format: str = "json",
    session_id: str | None = Query(None, description="특정 세션 필터링"),
    start_date: datetime | None = Query(None, description="시작 날짜"),
    end_date: datetime | None = Query(None, description="종료 날짜"),
    evaluation_module: EvaluationDataManager = Depends(get_evaluation_module),
):
    """
    평가 데이터 내보내기

    지원 형식:
    - json: JSON 형식
    - csv: CSV 형식
    """
    if format not in ["json", "csv"]:
        raise HTTPException(
            status_code=400, detail="지원하지 않는 형식입니다. json 또는 csv를 사용하세요."
        )
    try:
        filter_params = None
        if any([session_id, start_date, end_date]):
            filter_params = EvaluationFilter(
                session_id=session_id,
                start_date=start_date,
                end_date=end_date,
                min_score=None,
                max_score=None,
            )
        export_data = await evaluation_module.export_evaluations(
            format=format, filter_params=filter_params
        )
        if format == "json":
            media_type = "application/json"
            filename = f"evaluations_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        else:
            media_type = "text/csv"
            filename = f"evaluations_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            content=export_data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"데이터 내보내기 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="데이터 내보내기 중 오류가 발생했습니다") from e


@router.post("/batch", response_model=list[EvaluationResponse])
async def create_batch_evaluations(
    evaluations: list[EvaluationCreate],
    evaluation_module: EvaluationDataManager = Depends(get_evaluation_module),
):
    """
    여러 평가 일괄 생성

    최대 100개까지 한 번에 생성 가능합니다.
    """
    if len(evaluations) > 100:
        raise HTTPException(status_code=400, detail="한 번에 최대 100개까지만 생성할 수 있습니다")
    try:
        created_evaluations = []
        failed_count = 0
        for eval_data in evaluations:
            try:
                evaluation = await evaluation_module.create_evaluation(eval_data)
                created_evaluations.append(evaluation)
            except Exception as e:
                logger.error(f"배치 평가 생성 실패: {str(e)}")
                failed_count += 1
        logger.info(
            f"배치 평가 생성 완료: 성공 {len(created_evaluations)}개, 실패 {failed_count}개"
        )
        if failed_count > 0:
            logger.warning(f"{failed_count}개의 평가 생성이 실패했습니다")
        return created_evaluations
    except Exception as e:
        logger.error(f"배치 평가 생성 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="배치 평가 생성 중 오류가 발생했습니다") from e


@router.get("", response_model=dict[str, Any])
async def get_all_evaluations(
    session_id: str | None = Query(None, description="특정 세션 필터링"),
    evaluator_id: str | None = Query(None, description="특정 평가자 필터링"),
    min_score: int | None = Query(None, ge=1, le=5, description="최소 점수"),
    max_score: int | None = Query(None, ge=1, le=5, description="최대 점수"),
    start_date: datetime | None = Query(None, description="시작 날짜"),
    end_date: datetime | None = Query(None, description="종료 날짜"),
    has_feedback: bool | None = Query(None, description="피드백 유무"),
    skip: int = Query(0, ge=0, description="건너뛸 개수"),
    limit: int = Query(20, ge=1, le=100, description="조회할 최대 개수"),
    sort_by: str = Query("created_at", description="정렬 기준 필드"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$", description="정렬 순서"),
    evaluation_module: EvaluationDataManager = Depends(get_evaluation_module),
):
    """
    전체 평가 목록 조회

    필터링, 정렬, 페이지네이션을 지원합니다.

    정렬 가능 필드:
    - created_at: 생성 날짜
    - overall_score: 전체 점수
    - query_score: 쿼리 점수
    - response_score: 응답 점수
    """
    try:
        filter_params = None
        if any(
            [
                session_id,
                evaluator_id,
                min_score,
                max_score,
                start_date,
                end_date,
                has_feedback is not None,
            ]
        ):
            filter_params = EvaluationFilter(
                session_id=session_id,
                evaluator_id=evaluator_id,
                min_score=min_score,
                max_score=max_score,
                start_date=start_date,
                end_date=end_date,
                has_feedback=has_feedback,
            )
        if hasattr(evaluation_module, "get_all_evaluations"):
            result = await evaluation_module.get_all_evaluations(
                filter_params=filter_params,
                skip=skip,
                limit=limit,
                sort_by=sort_by,
                sort_order=sort_order,
            )
            return result
        else:
            all_evaluations = list(evaluation_module.evaluations.values())  # type: ignore[attr-defined]
            if filter_params:
                all_evaluations = evaluation_module._apply_filter(all_evaluations, filter_params)  # type: ignore[attr-defined]
            reverse = sort_order == "desc"
            if sort_by == "created_at":
                all_evaluations.sort(key=lambda e: e.created_at, reverse=reverse)
            elif sort_by == "overall_score":
                all_evaluations.sort(key=lambda e: e.overall_score or 0, reverse=reverse)
            elif sort_by == "query_score":
                all_evaluations.sort(key=lambda e: e.query_score or 0, reverse=reverse)
            elif sort_by == "response_score":
                all_evaluations.sort(key=lambda e: e.response_score or 0, reverse=reverse)
            total = len(all_evaluations)
            paginated = all_evaluations[skip : skip + limit]
            return {
                "total": total,
                "items": [EvaluationResponse(**e.model_dump()) for e in paginated],
                "skip": skip,
                "limit": limit,
            }
    except Exception as e:
        logger.error(f"평가 목록 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="평가 목록 조회 중 오류가 발생했습니다") from e


@router.get("/recent/list", response_model=list[EvaluationResponse])
async def get_recent_evaluations(
    limit: int = Query(10, ge=1, le=50, description="조회할 최대 개수"),
    evaluation_module: EvaluationDataManager = Depends(get_evaluation_module),
):
    """
    최근 평가 목록 조회

    전체 평가 중 가장 최근 것들을 반환합니다.
    """
    try:
        if hasattr(evaluation_module, "get_recent_evaluations"):
            return await evaluation_module.get_recent_evaluations(limit=limit)
        else:
            all_evaluations = list(evaluation_module.evaluations.values())  # type: ignore[attr-defined]
            sorted_evaluations = sorted(all_evaluations, key=lambda e: e.created_at, reverse=True)[
                :limit
            ]
            recent_evaluations = [EvaluationResponse(**e.model_dump()) for e in sorted_evaluations]
            logger.info(f"최근 평가 {len(recent_evaluations)}개 조회")
            return recent_evaluations
    except Exception as e:
        logger.error(f"최근 평가 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="최근 평가 조회 중 오류가 발생했습니다") from e
