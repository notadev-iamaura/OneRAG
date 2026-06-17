"""
평가 시스템 API 엔드포인트

사용자 쿼리와 LLM 응답에 대한 평가를 수집하고 관리하는 API
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ..infrastructure.persistence.evaluation_manager import (
    DuplicateEvaluationError,
    EvaluationDataManager,
)
from ..lib.auth import get_api_key
from ..lib.errors import ErrorCode, get_error_message
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


def _resolve_request_language(request: Request | None) -> str:
    """요청 Accept-Language 헤더에서 에러 메시지 언어를 결정한다(ko|en, 기본 ko).

    양언어 에러 카탈로그(app.lib.errors)는 "ko"/"en"만 지원한다. 헤더가 영어를
    우선하면 "en"을, 그 외(미지정/요청 없음 포함)는 "ko"를 반환한다 → 한국어
    기본(회귀 0). chat_router/websocket_router와 동일한 패턴을 따른다.

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


def _eval_detail(error_code: ErrorCode, lang: str = "ko", **context: Any) -> str:
    """평가 API HTTPException detail용 양언어 메시지를 생성한다.

    ErrorCode를 키로 ko/en 메시지를 카탈로그에서 조회한다(Accept-Language 기반
    자동 전환). 기본 lang은 "ko"라 기존 한국어 detail과 동일하다(회귀 0).

    Args:
        error_code: 평가 에러 코드 (EVAL-xxx)
        lang: 메시지 언어 ("ko"|"en", 기본 ko)
        **context: 메시지 템플릿 포맷팅 인자 (현 EVAL 메시지는 미사용)

    Returns:
        포맷팅된 에러 메시지 문자열
    """
    return get_error_message(error_code.value, lang=lang, **context)


def get_evaluation_module() -> EvaluationDataManager:
    """평가 데이터 관리자 의존성 주입"""
    if _evaluation_module is None:
        # 모듈 미초기화는 요청 컨텍스트 이전이라 기본 ko로 렌더(기존 동작 동일).
        raise HTTPException(
            status_code=500, detail=_eval_detail(ErrorCode.EVAL_001)
        )
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
    request: Request,
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
    lang = _resolve_request_language(request)
    try:
        logger.info(
            f"평가 생성 요청: 세션={evaluation_data.session_id}, 메시지={evaluation_data.message_id}"
        )
        evaluation = await evaluation_module.create_evaluation(evaluation_data)
        logger.info(f"평가 생성 완료: {evaluation.evaluation_id}")
        return evaluation
    except DuplicateEvaluationError as e:
        logger.warning("평가 생성 실패 - 중복 message_id: %s", e.message_id)
        # 구조화 detail(dict)은 유지하되 message만 양언어 카탈로그로 렌더한다.
        raise HTTPException(
            status_code=409,
            detail={
                "message": _eval_detail(ErrorCode.EVAL_002, lang),
                "existing_evaluation_id": e.evaluation_id,
                "message_id": e.message_id,
            },
        ) from e
    except ValueError as e:
        # 유효성 검증 원본 메시지는 그대로 노출한다(Pydantic/도메인 메시지 보존).
        logger.error(f"평가 생성 실패 - 유효성 검증 오류: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"평가 생성 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail=_eval_detail(ErrorCode.EVAL_003, lang)
        ) from e


@router.get("/message/{message_id}", response_model=EvaluationResponse)
async def get_evaluation_by_message(
    message_id: str,
    request: Request,
    evaluation_module: EvaluationDataManager = Depends(get_evaluation_module),
):
    """메시지 ID로 평가 조회"""
    evaluation = await evaluation_module.get_evaluation_by_message(message_id)
    if not evaluation:
        lang = _resolve_request_language(request)
        raise HTTPException(status_code=404, detail=_eval_detail(ErrorCode.EVAL_004, lang))
    return evaluation


@router.get("/session/{session_id}", response_model=list[EvaluationResponse])
async def get_session_evaluations(
    session_id: str,
    request: Request,
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
        lang = _resolve_request_language(request)
        raise HTTPException(status_code=500, detail=_eval_detail(ErrorCode.EVAL_005, lang)) from e


@router.get("/stats/summary", response_model=EvaluationStatistics)
async def get_evaluation_statistics(
    request: Request,
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
        lang = _resolve_request_language(request)
        raise HTTPException(status_code=500, detail=_eval_detail(ErrorCode.EVAL_006, lang)) from e


@router.get("/export/{format}")
async def export_evaluations(
    request: Request,
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
    lang = _resolve_request_language(request)
    if format not in ["json", "csv"]:
        raise HTTPException(status_code=400, detail=_eval_detail(ErrorCode.EVAL_007, lang))
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
        # 내보내기 형식/필터 검증 원본 메시지는 그대로 노출한다.
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"데이터 내보내기 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=_eval_detail(ErrorCode.EVAL_008, lang)) from e


@router.post("/batch", response_model=list[EvaluationResponse])
async def create_batch_evaluations(
    evaluations: list[EvaluationCreate],
    request: Request,
    evaluation_module: EvaluationDataManager = Depends(get_evaluation_module),
):
    """
    여러 평가 일괄 생성

    최대 100개까지 한 번에 생성 가능합니다.
    """
    lang = _resolve_request_language(request)
    if len(evaluations) > 100:
        raise HTTPException(status_code=400, detail=_eval_detail(ErrorCode.EVAL_009, lang))
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
        raise HTTPException(status_code=500, detail=_eval_detail(ErrorCode.EVAL_010, lang)) from e


@router.get("", response_model=dict[str, Any])
async def get_all_evaluations(
    request: Request,
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
        lang = _resolve_request_language(request)
        raise HTTPException(status_code=500, detail=_eval_detail(ErrorCode.EVAL_011, lang)) from e


@router.get("/recent/list", response_model=list[EvaluationResponse])
async def get_recent_evaluations(
    request: Request,
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
        lang = _resolve_request_language(request)
        raise HTTPException(status_code=500, detail=_eval_detail(ErrorCode.EVAL_012, lang)) from e


@router.get("/{evaluation_id}", response_model=EvaluationResponse)
async def get_evaluation(
    evaluation_id: str,
    request: Request,
    evaluation_module: EvaluationDataManager = Depends(get_evaluation_module),
):
    """특정 평가 조회"""
    evaluation = await evaluation_module.get_evaluation(evaluation_id)
    if not evaluation:
        lang = _resolve_request_language(request)
        raise HTTPException(status_code=404, detail=_eval_detail(ErrorCode.EVAL_013, lang))
    return evaluation


@router.put("/{evaluation_id}", response_model=EvaluationResponse)
async def update_evaluation(
    evaluation_id: str,
    update_data: EvaluationUpdate,
    request: Request,
    evaluation_module: EvaluationDataManager = Depends(get_evaluation_module),
):
    """평가 정보 업데이트"""
    lang = _resolve_request_language(request)
    try:
        evaluation = await evaluation_module.update_evaluation(evaluation_id, update_data)
        if not evaluation:
            raise HTTPException(status_code=404, detail=_eval_detail(ErrorCode.EVAL_013, lang))
        logger.info(f"평가 업데이트 완료: {evaluation_id}")
        return evaluation
    except ValueError as e:
        # 업데이트 검증 원본 메시지는 그대로 노출한다.
        logger.error(f"평가 업데이트 실패 - 유효성 검증 오류: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"평가 업데이트 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=_eval_detail(ErrorCode.EVAL_014, lang)) from e


@router.delete("/{evaluation_id}", status_code=204)
async def delete_evaluation(
    evaluation_id: str,
    request: Request,
    evaluation_module: EvaluationDataManager = Depends(get_evaluation_module),
):
    """평가 삭제"""
    success = await evaluation_module.delete_evaluation(evaluation_id)
    if not success:
        lang = _resolve_request_language(request)
        raise HTTPException(status_code=404, detail=_eval_detail(ErrorCode.EVAL_013, lang))
    logger.info(f"평가 삭제 완료: {evaluation_id}")
    return Response(status_code=204)
