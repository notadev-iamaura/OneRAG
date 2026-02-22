"""
Documents management API endpoints
문서 관리 API 엔드포인트 - 전체 문서 일괄 삭제 포함
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..lib.auth import get_api_key
from ..lib.logger import get_logger

logger = get_logger(__name__)

# ✅ C1, C2 보안 패치: 라우터 레벨 인증 추가
# 모든 Documents API 엔드포인트는 X-API-Key 헤더 필수
router = APIRouter(tags=["Documents"], dependencies=[Depends(get_api_key)])
modules: dict[str, Any] = {}
config: dict[str, Any] = {}


def set_dependencies(app_modules: dict[str, Any], app_config: dict[str, Any]):
    """의존성 주입"""
    global modules, config
    modules = app_modules
    config = app_config


class BulkDeleteAllRequest(BaseModel):
    """전체 문서 일괄 삭제 요청 모델"""

    confirm_code: str = "DELETE_ALL_DOCUMENTS"
    reason: str | None = None


class BulkDeleteAllResponse(BaseModel):
    """전체 문서 일괄 삭제 응답 모델"""

    deleted_count: int
    collection_cleared: bool
    operation_time_seconds: float
    message: str
    timestamp: str


class DocumentStats(BaseModel):
    """문서 통계 모델"""

    total_documents: int
    total_vectors: int
    collection_size_mb: float | None = None
    oldest_document: str | None = None
    newest_document: str | None = None


@router.get("/documents/stats", response_model=DocumentStats)
async def get_document_stats():
    """문서 통계 조회"""
    try:
        retrieval_module = modules.get("retrieval")
        if not retrieval_module:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "검색 모듈 초기화 실패",
                    "message": "검색 모듈이 초기화되지 않았습니다",
                    "suggestion": "서버를 재시작하거나 관리자에게 문의하세요",
                    "api_endpoint": "/documents/stats",
                    "support_email": "support@example.com",
                },
            )
        stats = await retrieval_module.get_document_stats()
        collection_info = await retrieval_module.get_collection_info()
        return DocumentStats(
            total_documents=stats.get("total_documents", 0),
            total_vectors=stats.get("vector_count", 0),
            collection_size_mb=collection_info.get("size_mb"),
            oldest_document=collection_info.get("oldest_document"),
            newest_document=collection_info.get("newest_document"),
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"Document stats error: {error}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "문서 통계 조회 실패",
                "message": "문서 통계를 가져오는 중 오류가 발생했습니다",
                "suggestion": "잠시 후 다시 시도하거나 관리자에게 문의하세요",
                "api_endpoint": "/documents/stats",
                "technical_error": str(error),
            },
        ) from error


@router.delete("/documents/all", response_model=BulkDeleteAllResponse)
async def delete_all_documents(
    request: BulkDeleteAllRequest,
    dry_run: bool = Query(False, description="실제 삭제 없이 시뮬레이션만 수행"),
):
    """
    전체 문서 일괄 삭제

    ⚠️ 위험한 작업: MongoDB의 모든 문서와 벡터를 완전히 삭제합니다.

    Args:
        request: 삭제 확인 코드와 사유
        dry_run: True일 경우 실제 삭제 없이 시뮬레이션만 수행

    Returns:
        삭제 결과 정보
    """
    try:
        start_time = datetime.now()
        if request.confirm_code != "DELETE_ALL_DOCUMENTS":
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "확인 코드 불일치",
                    "message": "문서 삭제 확인 코드가 올바르지 않습니다",
                    "suggestion": "confirm_code 필드에 'DELETE_ALL_DOCUMENTS'를 정확히 입력하세요",
                    "required_code": "DELETE_ALL_DOCUMENTS",
                    "provided_code": request.confirm_code,
                },
            )
        retrieval_module = modules.get("retrieval")
        if not retrieval_module:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "검색 모듈 초기화 실패",
                    "message": "검색 모듈이 초기화되지 않았습니다",
                    "suggestion": "서버를 재시작하거나 관리자에게 문의하세요",
                    "api_endpoint": "/documents/all",
                    "support_email": "support@example.com",
                },
            )
        stats_before = await retrieval_module.get_document_stats()
        total_documents = stats_before.get("total_documents", 0)
        total_vectors = stats_before.get("vector_count", 0)
        if total_documents == 0:
            return BulkDeleteAllResponse(
                deleted_count=0,
                collection_cleared=True,
                operation_time_seconds=0.0,
                message="No documents found. Collection is already empty.",
                timestamp=datetime.now().isoformat(),
            )
        if dry_run:
            logger.info(
                f"DRY RUN - Would delete {total_documents} documents, {total_vectors} vectors"
            )
            return BulkDeleteAllResponse(
                deleted_count=total_documents,
                collection_cleared=True,
                operation_time_seconds=0.0,
                message=f"DRY RUN - Would delete {total_documents} documents and {total_vectors} vectors",
                timestamp=datetime.now().isoformat(),
            )
        logger.warning(
            f"BULK DELETE ALL initiated: {total_documents} documents, reason: {request.reason}"
        )
        try:
            collection_cleared = await retrieval_module.delete_all_documents()
        except Exception as deletion_error:
            operation_time = (datetime.now() - start_time).total_seconds()
            logger.error(f"Deletion process failed: {deletion_error}")
            try:
                stats_after = await retrieval_module.get_document_stats()
                remaining_docs = stats_after.get("total_documents", 0)
                if remaining_docs == 0:
                    logger.info(
                        f"Documents were successfully deleted despite error: {total_documents} → 0"
                    )
                    return BulkDeleteAllResponse(
                        deleted_count=total_documents,
                        collection_cleared=True,
                        operation_time_seconds=round(operation_time, 2),
                        message=f"All {total_documents} documents deleted successfully (collection recreated)",
                        timestamp=datetime.now().isoformat(),
                    )
                else:
                    deleted_count = total_documents - remaining_docs
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "error": "부분 삭제 완료",
                            "message": f"{total_documents}개 문서 중 {deleted_count}개만 삭제되었습니다",
                            "suggestion": "나머지 문서를 삭제하려면 작업을 다시 시도하세요",
                            "deleted_count": deleted_count,
                            "total_count": total_documents,
                            "remaining_count": remaining_docs,
                            "technical_error": str(deletion_error),
                        },
                    ) from deletion_error
            except Exception as verify_error:
                logger.error(f"Cannot verify deletion status: {verify_error}", exc_info=True)
                logger.error(f"Original deletion error: {deletion_error}")
                raise HTTPException(
                    status_code=500,
                    detail={
                        "error": "삭제 상태 확인 실패",
                        "message": "문서 삭제 후 상태를 확인할 수 없습니다",
                        "suggestion": "GET /api/documents/stats로 현재 문서 수를 확인하세요",
                        "api_endpoint": "/documents/stats",
                        "technical_error": str(verify_error),
                        "original_error": str(deletion_error),
                    },
                ) from verify_error
        try:
            stats_after = await retrieval_module.get_document_stats()
            remaining_docs = stats_after.get("total_documents", 0)
        except Exception:
            remaining_docs = 0
        operation_time = (datetime.now() - start_time).total_seconds()
        if remaining_docs > 0:
            deleted_count = total_documents - remaining_docs
            logger.warning(f"Partial deletion: {deleted_count}/{total_documents} documents deleted")
            return BulkDeleteAllResponse(
                deleted_count=deleted_count,
                collection_cleared=False,
                operation_time_seconds=round(operation_time, 2),
                message=f"Partial deletion: {deleted_count} documents deleted, {remaining_docs} remaining",
                timestamp=datetime.now().isoformat(),
            )
        success_message = f"Successfully deleted all {total_documents} documents"
        if total_vectors > 0:
            success_message += f" and {total_vectors} vectors"
        if request.reason:
            success_message += f" (Reason: {request.reason})"
        logger.info(
            f"BULK DELETE ALL completed: {total_documents} deleted in {operation_time:.2f}s"
        )
        return BulkDeleteAllResponse(
            deleted_count=total_documents,
            collection_cleared=collection_cleared,
            operation_time_seconds=round(operation_time, 2),
            message=success_message,
            timestamp=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"Bulk delete all error: {error}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "문서 삭제 실패",
                "message": "문서를 삭제하는 중 예기치 않은 오류가 발생했습니다",
                "suggestion": "잠시 후 다시 시도하거나 관리자에게 문의하세요",
                "api_endpoint": "/documents/all",
                "technical_error": str(error),
                "support_email": "support@example.com",
            },
        ) from error


@router.post("/documents/clear-collection")
async def clear_collection_safe():
    """
    안전한 컬렉션 클리어 (관리자용)

    개발/테스트 환경에서만 사용 권장
    """
    try:
        app_config = config.get("app", {})
        debug_mode = app_config.get("debug", False)
        if not debug_mode:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "권한 없음",
                    "message": "컬렉션 초기화는 디버그 모드에서만 허용됩니다",
                    "suggestion": "프로덕션 환경에서는 DELETE /api/documents/all을 사용하세요",
                    "current_mode": "production",
                    "required_mode": "debug",
                    "api_endpoint": "/documents/clear-collection",
                },
            )
        retrieval_module = modules.get("retrieval")
        if not retrieval_module:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "검색 모듈 초기화 실패",
                    "message": "검색 모듈이 초기화되지 않았습니다",
                    "suggestion": "서버를 재시작하거나 관리자에게 문의하세요",
                    "api_endpoint": "/documents/clear-collection",
                    "support_email": "support@example.com",
                },
            )
        await retrieval_module.recreate_collection()
        logger.info("Collection cleared and recreated in debug mode")
        return {
            "message": "Collection cleared successfully",
            "debug_mode": True,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"Clear collection error: {error}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "컬렉션 초기화 실패",
                "message": "컬렉션을 초기화하는 중 오류가 발생했습니다",
                "suggestion": "잠시 후 다시 시도하거나 관리자에게 문의하세요",
                "api_endpoint": "/documents/clear-collection",
                "technical_error": str(error),
            },
        ) from error


@router.post("/documents/backup-metadata")
async def backup_document_metadata():
    """
    문서 메타데이터 백업

    삭제 전 문서 정보를 백업하여 복구 가능하도록 함
    """
    try:
        retrieval_module = modules.get("retrieval")
        if not retrieval_module:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "검색 모듈 초기화 실패",
                    "message": "검색 모듈이 초기화되지 않았습니다",
                    "suggestion": "서버를 재시작하거나 관리자에게 문의하세요",
                    "api_endpoint": "/documents/backup-metadata",
                    "support_email": "support@example.com",
                },
            )
        backup_data = await retrieval_module.backup_metadata()
        logger.info(f"Document metadata backed up: {len(backup_data)} documents")
        return {
            "message": "Metadata backup completed",
            "document_count": len(backup_data),
            "backup_size_kb": len(str(backup_data)) / 1024,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error(f"Backup metadata error: {error}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "메타데이터 백업 실패",
                "message": "문서 메타데이터를 백업하는 중 오류가 발생했습니다",
                "suggestion": "잠시 후 다시 시도하거나 관리자에게 문의하세요",
                "api_endpoint": "/documents/backup-metadata",
                "technical_error": str(error),
            },
        ) from error
