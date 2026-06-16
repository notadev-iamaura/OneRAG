"""
Admin Router - 관리자용 API 엔드포인트

Phase 3: 배치 평가 API
관리자 전용 기능을 제공합니다.

## Router Layer의 역할
- 관리자 인증 처리
- 배치 평가 요청 처리
- 에러 핸들링
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from ...lib.auth import get_api_key
from ...lib.errors import ErrorCode, get_error_message
from ...lib.logger import get_logger
from ...modules.core.evaluation import EvaluatorFactory
from ..schemas.debug import DebugTrace
from ..schemas.evaluation import (
    BatchEvaluateRequest,
    BatchEvaluateResponse,
    EvaluationResultSchema,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(get_api_key)])


def _resolve_request_language(request: Request | None) -> str:
    """요청 Accept-Language 헤더에서 에러 메시지 언어를 결정한다(ko|en, 기본 ko).

    양언어 에러 카탈로그(app.lib.errors)는 "ko"/"en"만 지원한다. 헤더가 영어를
    우선하면 "en"을, 그 외(미지정 포함)는 "ko"를 반환한다 → 한국어 기본(회귀 0).
    request가 None(엔드포인트 함수 직접 호출 등)이면 "ko"로 폴백한다(회귀 0).
    """
    if request is None:
        return "ko"
    accept_language = (request.headers.get("accept-language") or "").lower()
    en_idx = accept_language.find("en")
    ko_idx = accept_language.find("ko")
    if en_idx != -1 and (ko_idx == -1 or en_idx < ko_idx):
        return "en"
    return "ko"

# 설정 및 모듈 (DI Container에서 주입받을 수 있도록 변수화)
_config: dict | None = None
_session_module = None  # ✅ Task 5: 세션 모듈 주입


def set_config(config: dict) -> None:
    """설정 주입"""
    global _config
    _config = config
    logger.info("Admin Router 설정 주입 완료")


def set_session_module(session_module) -> None:
    """세션 모듈 주입 (Task 5)"""
    global _session_module
    _session_module = session_module
    logger.info("Admin Router 세션 모듈 주입 완료")


@router.post("/evaluate", response_model=BatchEvaluateResponse)
async def batch_evaluate(
    request: BatchEvaluateRequest, http_request: Request = None  # type: ignore[assignment]
) -> BatchEvaluateResponse:
    """
    배치 평가 API

    여러 샘플(질문-답변-컨텍스트)을 한 번에 평가합니다.
    관리자가 시스템 품질을 점검하거나 Golden Dataset을 검증할 때 사용합니다.

    Args:
        request: 배치 평가 요청
            - samples: 평가할 샘플 리스트 (최대 100개)
            - provider: 평가기 종류 ("internal" 또는 "ragas")

    Returns:
        BatchEvaluateResponse: 평가 결과
            - results: 개별 평가 결과 리스트
            - summary: 요약 통계 (평균 점수)
            - sample_count: 평가된 샘플 수

    Raises:
        HTTPException(400): 잘못된 요청
        HTTPException(500): 평가 실패
    """
    try:
        # 평가기 생성
        eval_config = {
            "evaluation": {
                "enabled": True,
                "provider": request.provider,
            }
        }

        # 기존 설정 병합
        if _config:
            eval_config = {**_config, **eval_config}
            eval_config["evaluation"]["provider"] = request.provider

        evaluator = EvaluatorFactory.create(eval_config)

        logger.info(
            "배치 평가 시작",
            sample_count=len(request.samples),
            provider=request.provider,
        )

        # 샘플 변환
        samples = [
            {
                "query": s.query,
                "answer": s.answer,
                "context": s.context,
                "reference": s.reference,
            }
            for s in request.samples
        ]

        # 배치 평가 실행
        results = await evaluator.batch_evaluate(samples)

        # 결과 변환
        result_schemas = [
            EvaluationResultSchema(
                faithfulness=r.faithfulness,
                relevance=r.relevance,
                overall=r.overall,
                reasoning=r.reasoning,
                context_precision=r.context_precision,
            )
            for r in results
        ]

        # 요약 통계 계산
        if results:
            avg_faithfulness = sum(r.faithfulness for r in results) / len(results)
            avg_relevance = sum(r.relevance for r in results) / len(results)
            avg_overall = sum(r.overall for r in results) / len(results)
            summary = {
                "avg_faithfulness": round(avg_faithfulness, 4),
                "avg_relevance": round(avg_relevance, 4),
                "avg_overall": round(avg_overall, 4),
                "min_overall": round(min(r.overall for r in results), 4),
                "max_overall": round(max(r.overall for r in results), 4),
            }
        else:
            summary = {}

        logger.info(
            "배치 평가 완료",
            sample_count=len(results),
            avg_overall=summary.get("avg_overall", 0),
        )

        return BatchEvaluateResponse(
            success=True,
            results=result_schemas,
            summary=summary,
            provider=request.provider,
            sample_count=len(results),
            message="배치 평가 완료",
        )

    except ValueError as e:
        logger.warning(f"배치 평가 요청 오류: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e

    except Exception as e:
        logger.error(f"배치 평가 실패: {e}", exc_info=True)
        lang = _resolve_request_language(http_request)
        raise HTTPException(
            status_code=500,
            detail=get_error_message(ErrorCode.ADMIN_001.value, lang, error=str(e)),
        ) from e


@router.get("/evaluate/providers")
async def get_available_providers() -> dict:
    """
    사용 가능한 평가 프로바이더 조회

    Returns:
        dict: 프로바이더 정보
            - providers: 사용 가능한 프로바이더 목록
            - default: 기본 프로바이더
    """
    providers = EvaluatorFactory.get_supported_evaluators()
    return {
        "providers": providers,
        "default": "internal",
        "description": {
            "internal": "LLM 기반 빠른 평가 (실시간용)",
            "ragas": "Ragas 라이브러리 기반 정밀 평가 (배치용)",
        },
    }


@router.get("/debug/session/{session_id}/messages/{message_id}", response_model=DebugTrace)
async def get_debug_trace(
    session_id: str, message_id: str, request: Request
) -> DebugTrace:
    """
    디버깅 추적 조회 API (Task 5)

    특정 메시지의 RAG 파이프라인 실행 내역을 조회합니다.

    Args:
        session_id: 세션 ID
        message_id: 메시지 ID

    Returns:
        DebugTrace: 디버깅 추적 정보
            - query_transformation: 쿼리 변환 로그
            - retrieved_documents: 검색된 문서 + 점수
            - self_rag_evaluation: Self-RAG 평가 결과
            - generation_prompt: 생성 프롬프트 (선택)

    Raises:
        HTTPException(404): 메시지 없음
        HTTPException(500): 조회 실패
    """
    if _session_module is None:
        logger.error("세션 모듈이 주입되지 않았습니다")
        lang = _resolve_request_language(request)
        raise HTTPException(
            status_code=500,
            detail=get_error_message(ErrorCode.ADMIN_002.value, lang),
        )

    try:
        # 세션 모듈에서 debug_trace 조회
        debug_trace_dict = await _session_module.get_debug_trace(
            session_id, message_id
        )

        if not debug_trace_dict:
            raise HTTPException(
                status_code=404,
                detail=f"Debug trace not found for session {session_id}, message {message_id}",
            )

        # dict → DebugTrace 변환
        debug_trace = DebugTrace(**debug_trace_dict)

        logger.info(
            "디버깅 추적 조회 성공",
            session_id=session_id,
            message_id=message_id,
        )

        return debug_trace

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"디버깅 추적 조회 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve debug trace: {str(e)}",
        ) from e
