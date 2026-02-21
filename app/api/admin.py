"""
Admin API endpoints
관리자 API 엔드포인트
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..lib.auth import get_api_key, get_api_key_auth
from ..lib.logger import get_logger

logger = get_logger(__name__)

# v3.3.0: 라우터 수준에서 전역 인증 적용 (보안 강화)
router = APIRouter(
    prefix="/api/admin",
    tags=["Admin"],
    dependencies=[Depends(get_api_key)]
)

modules: dict[str, Any] = {}
config: dict[str, Any] = {}
_system_start_time: float = time.time()  # 시스템 시작 시간


def set_dependencies(app_modules: dict[str, Any], app_config: dict[str, Any]):
    """의존성 주입"""
    global modules, config
    modules = app_modules
    config = app_config


websocket_connections: list[WebSocket] = []


class SystemStatus(BaseModel):
    """시스템 상태 모델"""

    status: str
    uptime: float
    modules: dict[str, bool]
    memory_usage: dict[str, Any]
    active_sessions: int
    total_documents: int
    vector_count: int
    timestamp: str


class RealtimeMetrics(BaseModel):
    """실시간 메트릭스 모델"""

    timestamp: str
    chat_requests_per_minute: int
    average_response_time: float
    active_sessions: int
    memory_usage_mb: float
    cpu_usage_percent: float
    error_rate: float
    # 캐시 메트릭 (v3.3.2)
    cache_hit_rate: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_saved_time_ms: float = 0.0
    # 비용 메트릭 (v3.3.2)
    total_cost_usd: float = 0.0
    cost_per_hour: float = 0.0
    total_llm_tokens: int = 0


class ModuleInfo(BaseModel):
    """모듈 정보 모델"""

    name: str
    status: str
    initialized: bool
    config: dict[str, Any]
    stats: dict[str, Any] | None = None


def get_memory_usage() -> dict[str, Any]:
    """메모리 사용량 조회"""
    try:
        import psutil

        memory = psutil.virtual_memory()
        process = psutil.Process()
        return {
            "system_total_mb": round(memory.total / 1024**2, 2),
            "system_used_mb": round(memory.used / 1024**2, 2),
            "system_available_mb": round(memory.available / 1024**2, 2),
            "system_percent": memory.percent,
            "process_memory_mb": round(process.memory_info().rss / 1024**2, 2),
            "process_percent": process.memory_percent(),
        }
    except ImportError:
        return {
            "system_total_mb": 0,
            "system_used_mb": 0,
            "system_available_mb": 0,
            "system_percent": 0,
            "process_memory_mb": 0,
            "process_percent": 0,
        }


async def get_active_sessions_count() -> int:
    """활성 세션 수 조회"""
    try:
        session_module = modules.get("session")
        if session_module:
            stats = await session_module.get_stats()
            active_sessions = stats.get("active_sessions", 0)
            return int(active_sessions) if isinstance(active_sessions, int | float) else 0
    except Exception as e:
        logger.error(
            "활성 세션 수 조회 실패",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            }
        )
    return 0


async def get_document_stats() -> dict[str, int]:
    """문서 통계 조회"""
    try:
        retrieval_module = modules.get("retrieval")
        if retrieval_module:
            stats = await retrieval_module.get_stats()
            return {
                "total_documents": stats.get("total_documents", 0),
                "vector_count": stats.get("vector_count", 0),
            }
    except Exception as e:
        logger.error(
            "문서 통계 조회 실패",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            }
        )
    return {"total_documents": 0, "vector_count": 0}


def get_cpu_usage() -> float:
    """CPU 사용률 조회"""
    try:
        import psutil

        cpu_percent = psutil.cpu_percent(interval=1)
        return float(cpu_percent) if isinstance(cpu_percent, int | float) else 0.0
    except ImportError:
        return 0.0


@router.get("/status", response_model=SystemStatus)
async def get_system_status():
    """시스템 상태 조회"""
    try:
        module_status = {
            "session": bool(modules.get("session")),
            "document_processor": bool(modules.get("document_processor")),
            "retrieval": bool(modules.get("retrieval")),
            "generation": bool(modules.get("generation")),
        }
        memory_usage = get_memory_usage()
        active_sessions = await get_active_sessions_count()
        doc_stats = await get_document_stats()
        all_modules_ok = all(module_status.values())
        system_status = "healthy" if all_modules_ok else "degraded"
        return SystemStatus(
            status=system_status,
            uptime=time.time() - _system_start_time,
            modules=module_status,
            memory_usage=memory_usage,
            active_sessions=active_sessions,
            total_documents=doc_stats["total_documents"],
            vector_count=doc_stats["vector_count"],
            timestamp=datetime.now().isoformat(),
        )
    except Exception as error:
        logger.error(
            "시스템 상태 조회 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve system status") from error


@router.get("/modules", response_model=list[ModuleInfo])
async def get_module_info():
    """모듈 정보 조회"""
    try:
        module_info = []
        for module_name, module_instance in modules.items():
            status = "active" if module_instance else "inactive"
            module_stats = None
            module_config = {}
            try:
                if hasattr(module_instance, "get_stats"):
                    module_stats = await module_instance.get_stats()
                if hasattr(module_instance, "config"):
                    module_config = getattr(module_instance, "config", {})
            except Exception as e:
                logger.warning(
                    "모듈 통계 조회 실패",
                    extra={
                        "module_name": module_name,
                        "error": str(e),
                        "error_type": type(e).__name__
                    }
                )
            module_info.append(
                ModuleInfo(
                    name=module_name,
                    status=status,
                    initialized=bool(module_instance),
                    config=module_config,
                    stats=module_stats,
                )
            )
        return module_info
    except Exception as error:
        logger.error(
            "모듈 정보 조회 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=500, detail="Failed to retrieve module information"
        ) from error


@router.get("/config")
async def get_config_info():
    """설정 정보 조회"""
    try:
        safe_config = {}
        for key, value in config.items():
            if key in ["models", "session"]:
                safe_value = mask_sensitive_data(value)
                safe_config[key] = safe_value
            else:
                safe_config[key] = value
        return {
            "config": safe_config,
            "environment": config.get("environment", "unknown"),
            "version": "2.0.0",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as error:
        logger.error(
            "설정 정보 조회 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve configuration") from error


def mask_sensitive_data(data: Any) -> Any:
    """민감한 데이터 마스킹"""
    if isinstance(data, dict):
        masked = {}
        for key, value in data.items():
            if any(
                sensitive in key.lower() for sensitive in ["key", "secret", "password", "token"]
            ):
                if isinstance(value, str) and len(value) > 4:
                    masked[key] = value[:4] + "*" * (len(value) - 4)
                else:
                    masked[key] = "***"
            else:
                masked[key] = mask_sensitive_data(value)
        return masked
    elif isinstance(data, list):
        return [mask_sensitive_data(item) for item in data]
    else:
        return data


@router.get("/realtime-metrics", response_model=RealtimeMetrics)
async def get_realtime_metrics():
    """실시간 메트릭스 조회"""
    try:
        memory_usage = get_memory_usage()
        cpu_usage = get_cpu_usage()
        active_sessions = await get_active_sessions_count()
        import random

        chat_requests_per_minute = random.randint(5, 25)
        average_response_time = round(random.uniform(0.5, 2.0), 2)
        error_rate = round(random.uniform(0.0, 5.0), 2)

        # 캐시 메트릭 조회 (retrieval_orchestrator에서)
        cache_hit_rate = 0.0
        cache_hits = 0
        cache_misses = 0
        cache_saved_time_ms = 0.0
        retrieval_module = modules.get("retrieval")
        if retrieval_module and hasattr(retrieval_module, "get_stats"):
            try:
                retrieval_stats = retrieval_module.get_stats()
                orchestrator_stats = retrieval_stats.get("orchestrator", {})
                cache_stats = retrieval_stats.get("cache", {})
                cache_hit_rate = orchestrator_stats.get("cache_hit_rate", 0.0)
                cache_hits = orchestrator_stats.get("cache_hits", 0)
                cache_misses = orchestrator_stats.get("cache_misses", 0)
                cache_saved_time_ms = cache_stats.get("saved_time_ms", 0.0)
            except Exception as e:
                logger.warning(
                    "캐시 메트릭 조회 실패",
                    extra={"error": str(e), "error_type": type(e).__name__}
                )

        # 비용 메트릭 조회 (cost_tracker에서)
        total_cost_usd = 0.0
        cost_per_hour = 0.0
        total_llm_tokens = 0
        cost_tracker_module = modules.get("cost_tracker")
        if cost_tracker_module and hasattr(cost_tracker_module, "get_stats"):
            try:
                cost_stats = cost_tracker_module.get_stats()
                total_cost_usd = cost_stats.get("total_cost", 0.0)
                cost_per_hour = cost_stats.get("cost_per_hour", 0.0)
                # 모든 provider의 토큰 합산
                usage = cost_stats.get("usage", {})
                for provider_stats in usage.values():
                    total_llm_tokens += provider_stats.get("total_tokens", 0)
            except Exception as e:
                logger.warning(
                    "비용 메트릭 조회 실패",
                    extra={"error": str(e), "error_type": type(e).__name__}
                )

        return RealtimeMetrics(
            timestamp=datetime.now().isoformat(),
            chat_requests_per_minute=chat_requests_per_minute,
            average_response_time=average_response_time,
            active_sessions=active_sessions,
            memory_usage_mb=memory_usage["process_memory_mb"],
            cpu_usage_percent=cpu_usage,
            error_rate=error_rate,
            # 캐시 메트릭
            cache_hit_rate=cache_hit_rate,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            cache_saved_time_ms=cache_saved_time_ms,
            # 비용 메트릭
            total_cost_usd=total_cost_usd,
            cost_per_hour=cost_per_hour,
            total_llm_tokens=total_llm_tokens,
        )
    except Exception as error:
        logger.error(
            "실시간 메트릭스 조회 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=500, detail="Failed to retrieve realtime metrics"
        ) from error


@router.post("/cache/clear")
async def clear_cache():
    """캐시 클리어 (인증 필요)"""
    try:
        session_module = modules.get("session")
        if session_module and hasattr(session_module, "clear_cache"):
            await session_module.clear_cache()
        retrieval_module = modules.get("retrieval")
        if retrieval_module and hasattr(retrieval_module, "clear_cache"):
            await retrieval_module.clear_cache()
        logger.info("Cache cleared by admin request")
        return {"message": "Cache cleared successfully", "timestamp": datetime.now().isoformat()}
    except Exception as error:
        logger.error(
            "캐시 클리어 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to clear cache") from error


@router.post("/modules/{module_name}/restart")
async def restart_module(module_name: str):
    """모듈 재시작 (인증 필요)"""
    try:
        if module_name not in modules:
            raise HTTPException(status_code=404, detail=f"Module {module_name} not found")
        module_instance = modules[module_name]
        if hasattr(module_instance, "restart"):
            await module_instance.restart()
        elif hasattr(module_instance, "destroy") and hasattr(module_instance, "initialize"):
            await module_instance.destroy()
            await module_instance.initialize()
        else:
            raise HTTPException(
                status_code=400, detail=f"Module {module_name} does not support restart"
            )
        logger.info(
            "모듈 재시작 완료",
            extra={"module_name": module_name}
        )
        return {
            "message": f"Module {module_name} restarted successfully",
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error(
            "모듈 재시작 실패",
            extra={
                "module_name": module_name,
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to restart module {module_name}"
        ) from error


@router.get("/metrics")
async def get_metrics(period: str = "7d"):
    """시계열 메트릭 데이터 조회"""
    try:
        return {
            "period": period,
            "totalSessions": 150,
            "totalQueries": 1250,
            "avgResponseTime": 0.8,
            "timeSeries": [
                {"date": "2024-01-01", "sessions": 20, "queries": 180, "avgResponseTime": 0.7},
                {"date": "2024-01-02", "sessions": 25, "queries": 220, "avgResponseTime": 0.9},
                {"date": "2024-01-03", "sessions": 18, "queries": 160, "avgResponseTime": 0.6},
                {"date": "2024-01-04", "sessions": 30, "queries": 280, "avgResponseTime": 1.1},
                {"date": "2024-01-05", "sessions": 22, "queries": 200, "avgResponseTime": 0.8},
                {"date": "2024-01-06", "sessions": 28, "queries": 250, "avgResponseTime": 0.9},
                {"date": "2024-01-07", "sessions": 32, "queries": 300, "avgResponseTime": 1.0},
            ],
        }
    except Exception as error:
        logger.error(
            "메트릭 조회 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve metrics") from error


@router.get("/keywords")
async def get_keywords(period: str = "7d"):
    """주요 키워드 분석"""
    try:
        return {
            "keywords": [
                {"rank": 1, "keyword": "퇴사 절차", "count": 45},
                {"rank": 2, "keyword": "연차 사용", "count": 38},
                {"rank": 3, "keyword": "급여 명세서", "count": 32},
                {"rank": 4, "keyword": "업무 인수인계", "count": 28},
                {"rank": 5, "keyword": "보험 해지", "count": 24},
            ]
        }
    except Exception as error:
        logger.error(
            "키워드 조회 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve keywords") from error


@router.get("/chunks")
async def get_chunks(period: str = "7d"):
    """자주 사용된 청크 분석"""
    try:
        return {
            "chunks": [
                {"rank": 1, "chunkName": "퇴사신청서_작성방법.pdf", "count": 42},
                {"rank": 2, "chunkName": "연차사용_가이드라인.docx", "count": 35},
                {"rank": 3, "chunkName": "급여정산_절차.pdf", "count": 29},
                {"rank": 4, "chunkName": "업무인수인계_템플릿.xlsx", "count": 26},
                {"rank": 5, "chunkName": "보험해지_안내.pdf", "count": 21},
            ]
        }
    except Exception as error:
        logger.error(
            "청크 조회 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve chunks") from error


@router.get("/countries")
async def get_countries(period: str = "7d"):
    """접속 국가 통계"""
    try:
        return {
            "countries": [
                {"country": "한국", "count": 145},
                {"country": "미국", "count": 23},
                {"country": "일본", "count": 18},
                {"country": "중국", "count": 12},
                {"country": "독일", "count": 8},
                {"country": "영국", "count": 6},
                {"country": "프랑스", "count": 4},
                {"country": "캐나다", "count": 3},
            ]
        }
    except Exception as error:
        logger.error(
            "국가 조회 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve countries") from error


@router.get("/sessions")
async def get_sessions(status: str = "all", limit: int = 50, offset: int = 0):
    """세션 목록 조회"""
    try:
        session_module = modules.get("session")
        if not session_module:
            raise HTTPException(status_code=503, detail="Session module not available")
        result = await session_module.get_all_sessions(status, limit, offset)
        return result
    except HTTPException:
        raise
    except Exception as error:
        logger.error(
            "세션 목록 조회 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve sessions") from error


@router.get("/sessions/{session_id}")
async def get_session_details(session_id: str):
    """세션 상세 정보 조회"""
    try:
        session_module = modules.get("session")
        if not session_module:
            raise HTTPException(status_code=503, detail="Session module not available")
        session_details = await session_module.get_session_details(session_id)
        if not session_details:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return session_details
    except HTTPException:
        raise
    except Exception as error:
        logger.error(
            "세션 상세 정보 조회 실패",
            extra={
                "session_id": session_id,
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve session details") from error


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """세션 강제 종료"""
    try:
        session_module = modules.get("session")
        if not session_module:
            raise HTTPException(status_code=503, detail="Session module not available")
        session_details = await session_module.get_session_details(session_id)
        if not session_details:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        await session_module.delete_session(session_id)
        logger.info(
            "세션 강제 종료 완료",
            extra={"session_id": session_id}
        )
        return {
            "success": True,
            "message": f"Session {session_id} deleted successfully",
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error(
            "세션 강제 종료 실패",
            extra={
                "session_id": session_id,
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to delete session") from error


@router.get("/documents")
async def get_documents(page: int = 1, page_size: int = 20):
    """문서 목록 조회"""
    try:
        retrieval_module = modules.get("retrieval")
        if not retrieval_module:
            raise HTTPException(status_code=503, detail="Retrieval module not available")
        result = await retrieval_module.list_documents(page, page_size)
        documents = []
        for doc in result.get("documents", []):
            documents.append(
                {
                    "id": doc["id"],
                    "name": doc["filename"],
                    "chunkCount": doc["chunk_count"],
                    "size": f"{doc['file_size'] / 1024:.2f} KB" if doc["file_size"] else "unknown",
                    "lastUpdate": (
                        datetime.fromtimestamp(doc["upload_date"]).isoformat()
                        if doc["upload_date"]
                        else None
                    ),
                    "status": "active",
                    "fileType": doc["file_type"],
                    "metadata": {
                        "file_size": doc["file_size"],
                        "upload_timestamp": doc["upload_date"],
                    },
                }
            )
        return {
            "documents": documents,
            "total": result.get("total_count", 0),
            "page": page,
            "page_size": page_size,
            "has_next": result.get("has_next", False),
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error(
            "문서 목록 조회 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve documents") from error


@router.get("/documents/{document_id}")
async def get_document_details(document_id: str):
    """문서 상세 정보 조회"""
    try:
        retrieval_module = modules.get("retrieval")
        if not retrieval_module:
            raise HTTPException(status_code=503, detail="Retrieval module not available")
        document_details = await retrieval_module.get_document_details(document_id)
        if not document_details:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found")
        return {
            "id": document_details["id"],
            "name": document_details["filename"],
            "chunkCount": document_details["actual_chunk_count"],
            "size": (
                f"{document_details['file_size'] / 1024:.2f} KB"
                if document_details["file_size"]
                else "unknown"
            ),
            "lastUpdate": (
                datetime.fromtimestamp(document_details["upload_date"]).isoformat()
                if document_details["upload_date"]
                else None
            ),
            "status": "active",
            "fileType": document_details["file_type"],
            "filePath": document_details.get("file_path"),
            "fileHash": document_details.get("file_hash"),
            "chunkPreviews": document_details["chunk_previews"],
            "metadata": document_details["metadata"],
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error(
            "문서 상세 정보 조회 실패",
            extra={
                "document_id": document_id,
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=500, detail="Failed to retrieve document details"
        ) from error


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str):
    """문서 삭제"""
    try:
        retrieval_module = modules.get("retrieval")
        if not retrieval_module:
            raise HTTPException(status_code=503, detail="Retrieval module not available")
        document_details = await retrieval_module.get_document_details(document_id)
        if not document_details:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found")
        await retrieval_module.delete_document(document_id)
        logger.info(
            "문서 삭제 완료",
            extra={"document_id": document_id}
        )
        return {
            "success": True,
            "message": f"Document {document_id} deleted successfully",
            "document_id": document_id,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error(
            "문서 삭제 실패",
            extra={
                "document_id": document_id,
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to delete document") from error


@router.post("/documents/{document_id}/reprocess")
async def reprocess_document(document_id: str):
    """문서 재처리 (Phase 2로 연기)"""
    raise HTTPException(
        status_code=501, detail="Document reprocessing not implemented yet (Phase 2)"
    )


@router.post("/test")
async def test_rag(request: dict):
    """RAG 시스템 테스트"""
    try:
        query = request.get("query")
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        generation_module = modules.get("generation")
        retrieval_module = modules.get("retrieval")
        if not generation_module or not retrieval_module:
            raise HTTPException(status_code=503, detail="RAG modules not available")
        start_time = time.time()
        retrieved_chunks = await retrieval_module.search(query, {"limit": 5})
        response = await generation_module.generate_response(query, retrieved_chunks)
        response_time = time.time() - start_time
        return {
            "query": query,
            "retrievedChunks": retrieved_chunks,
            "generatedAnswer": response,
            "responseTime": f"{response_time:.2f}s",
        }
    except Exception as error:
        logger.error(
            "RAG 테스트 실행 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to execute RAG test") from error


@router.post("/database/optimize")
async def optimize_database():
    """PostgreSQL 데이터베이스 최적화 (인증 필요)"""
    try:
        from sqlalchemy import text

        from ..database.connection import db_manager

        if not db_manager._initialized:
            return {
                "success": True,
                "message": "Database not initialized (using in-memory mode)",
                "timestamp": datetime.now().isoformat(),
            }
        logger.info("Starting database optimization...")
        async with db_manager.get_session() as session:
            await session.execute(text("ANALYZE"))
            await session.commit()
        logger.info("Database optimization completed")
        return {
            "success": True,
            "message": "Database optimized successfully (ANALYZE executed)",
            "note": "VACUUM requires superuser privileges and should be run from psql",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as error:
        logger.error(
            "데이터베이스 최적화 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to optimize database. Please try again or contact support.",
        ) from error


@router.get("/logs/download")
async def download_logs(lines: int = 1000):
    """로그 파일 다운로드"""
    try:
        from pathlib import Path

        log_dir = Path(__file__).parent.parent.parent / "logs"
        if not log_dir.exists():
            raise HTTPException(
                status_code=404, detail="Log directory not found. Logs are being sent to stdout."
            )
        log_files = sorted(log_dir.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True)
        if not log_files:
            raise HTTPException(status_code=404, detail="No log files found")
        log_file = log_files[0]
        with open(log_file, encoding="utf-8") as f:
            all_lines = f.readlines()
            recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
        log_content = "".join(recent_lines)
        from fastapi.responses import Response

        return Response(
            content=log_content,
            media_type="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename=app_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            },
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.error(
            "로그 다운로드 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=500, detail="Failed to download logs. Please try again or contact support."
        ) from error


@router.get("/recent-chats")
async def get_recent_chats(limit: int = 20):
    """
    최근 채팅 로그 조회 (지역 정보 포함)

    Args:
        limit: 반환할 최대 채팅 수 (기본값: 20)

    Returns:
        ChatLog 리스트 (country, city 필드 포함)
    """
    try:
        session_module = modules.get("session")
        if not session_module:
            raise HTTPException(status_code=500, detail="Session module not available")
        chats = await session_module.get_recent_chats(limit=limit)
        for chat in chats:
            session_id = chat.get("chatId")
            if session_id:
                location = await _get_session_location(session_id)
                chat["country"] = location.get("country")
                chat["city"] = location.get("city")
                chat["countryCode"] = location.get("country_code")
        return {"chats": chats, "total": len(chats)}
    except Exception as error:
        logger.error(
            "최근 채팅 조회 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve recent chats. Please try again or contact support.",
        ) from error


@router.get("/analytics/countries")
async def get_country_statistics(days: int = 30, limit: int = 20):
    """
    국가별 접속 통계

    Args:
        days: 조회 기간 (일)
        limit: 반환할 최대 국가 수

    Returns:
        국가별 세션 수, 메시지 수, 비율
    """
    try:
        from datetime import datetime, timedelta

        from sqlalchemy import func, select

        from ..database.connection import db_manager
        from ..database.models import ChatSessionModel

        cutoff_date = datetime.now() - timedelta(days=days)
        async with db_manager.get_session() as db_session:
            stmt = (
                select(
                    ChatSessionModel.country,
                    ChatSessionModel.country_code,
                    func.count(ChatSessionModel.session_id).label("session_count"),
                    func.sum(ChatSessionModel.message_count).label("total_messages"),
                )
                .where(ChatSessionModel.created_at >= cutoff_date)
                .where(ChatSessionModel.country.is_not(None))
                .group_by(ChatSessionModel.country, ChatSessionModel.country_code)
                .order_by(func.count(ChatSessionModel.session_id).desc())
                .limit(limit)
            )
            result = await db_session.execute(stmt)
            rows = result.all()
            total_sessions = sum(row.session_count for row in rows)
            countries = [
                {
                    "country": row.country,
                    "countryCode": row.country_code,
                    "sessions": row.session_count,
                    "messages": row.total_messages or 0,
                    "percentage": (
                        round(row.session_count / total_sessions * 100, 2)
                        if total_sessions > 0
                        else 0
                    ),
                }
                for row in rows
            ]
            return {"countries": countries, "total_sessions": total_sessions, "period_days": days}
    except Exception as error:
        logger.error(
            "국가 통계 조회 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve country statistics. Please try again or contact support.",
        ) from error


@router.get("/analytics/cities")
async def get_city_statistics(country_code: str | None = None, days: int = 30, limit: int = 20):
    """
    도시별 접속 통계

    Args:
        country_code: 국가 코드 필터 (예: KR)
        days: 조회 기간 (일)
        limit: 반환할 최대 도시 수

    Returns:
        도시별 세션 수, 메시지 수
    """
    try:
        from datetime import datetime, timedelta

        from sqlalchemy import func, select

        from ..database.connection import db_manager
        from ..database.models import ChatSessionModel

        cutoff_date = datetime.now() - timedelta(days=days)
        async with db_manager.get_session() as db_session:
            stmt = (
                select(
                    ChatSessionModel.city,
                    ChatSessionModel.country,
                    ChatSessionModel.country_code,
                    func.count(ChatSessionModel.session_id).label("session_count"),
                    func.sum(ChatSessionModel.message_count).label("total_messages"),
                )
                .where(ChatSessionModel.created_at >= cutoff_date)
                .where(ChatSessionModel.city.is_not(None))
            )
            if country_code:
                stmt = stmt.where(ChatSessionModel.country_code == country_code)
            stmt = (
                stmt.group_by(
                    ChatSessionModel.city, ChatSessionModel.country, ChatSessionModel.country_code
                )
                .order_by(func.count(ChatSessionModel.session_id).desc())
                .limit(limit)
            )
            result = await db_session.execute(stmt)
            rows = result.all()
            cities = [
                {
                    "city": row.city,
                    "country": row.country,
                    "countryCode": row.country_code,
                    "sessions": row.session_count,
                    "messages": row.total_messages or 0,
                }
                for row in rows
            ]
            return {
                "cities": cities,
                "total_cities": len(cities),
                "period_days": days,
                "filter_country": country_code,
            }
    except Exception as error:
        logger.error(
            "도시 통계 조회 실패",
            extra={
                "error": str(error),
                "error_type": type(error).__name__
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve city statistics. Please try again or contact support.",
        ) from error


async def _get_session_location(session_id: str) -> dict:
    """세션 지역 정보 조회 (헬퍼)"""
    try:
        from sqlalchemy import select

        from ..database.connection import db_manager
        from ..database.models import ChatSessionModel

        async with db_manager.get_session() as db_session:
            stmt = select(ChatSessionModel).where(ChatSessionModel.session_id == session_id)
            result = await db_session.execute(stmt)
            session = result.scalar_one_or_none()
            if session:
                return {
                    "country": session.country,
                    "city": session.city,
                    "country_code": session.country_code,
                }
    except Exception as e:
        logger.error(
            "지역 정보 조회 실패",
            extra={
                "session_id": session_id,
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True
        )
    return {"country": None, "city": None, "country_code": None}


async def broadcast_metrics():
    """실시간 메트릭 브로드캐스트"""
    while True:
        try:
            if websocket_connections:
                metrics = await get_realtime_metrics()
                message = {"type": "metrics", "data": metrics.dict()}
                disconnected = []
                for websocket in websocket_connections:
                    try:
                        await websocket.send_text(json.dumps(message))
                    except Exception:
                        disconnected.append(websocket)
                for websocket in disconnected:
                    websocket_connections.remove(websocket)
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(
                "메트릭 브로드캐스트 실패",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            await asyncio.sleep(5)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """관리자 WebSocket 엔드포인트 (API Key 인증 필수)"""
    # WebSocket은 라우터 dependencies가 적용되지 않으므로 수동 인증
    api_key = websocket.query_params.get("api_key") or websocket.headers.get("X-API-Key")
    auth = get_api_key_auth()

    if auth.api_key and (not api_key or not __import__("secrets").compare_digest(api_key, auth.api_key)):
        await websocket.close(code=4001, reason="인증 실패: 유효한 API Key가 필요합니다")
        logger.warning("Admin WebSocket 인증 실패: API Key 없음 또는 불일치")
        return

    await websocket.accept()
    websocket_connections.append(websocket)
    logger.info("Admin WebSocket connected")
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        logger.info("Admin WebSocket disconnected")
    except Exception as e:
        logger.error(
            "Admin WebSocket 에러",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True
        )
    finally:
        if websocket in websocket_connections:
            websocket_connections.remove(websocket)


def setup_websocket(http_server):
    """WebSocket 설정 (main.py에서 호출)"""
    asyncio.create_task(broadcast_metrics())
    logger.info("Admin WebSocket metrics broadcasting started")
    return None
