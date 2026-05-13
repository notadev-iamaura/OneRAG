"""
Health check API endpoints
시스템 상태 확인 엔드포인트
"""

import os
import sys
import time
from datetime import datetime
from typing import Any

import psutil
from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from ..lib.logger import get_logger
from ..lib.startup_policy import is_retrieval_required

logger = get_logger(__name__)
router = APIRouter(tags=["Health"])

# Phase 1-3 개선: 캐시 통계 제공을 위한 retrieval_rerank 모듈
_retrieval_module = None  # 초기화 시 설정됨
_startup_state: dict[str, Any] = {
    "ready": False,
    "status": "starting",
    "details": {},
}


def set_retrieval_module(module):
    """Retrieval 모듈 설정 (앱 시작 시 호출)"""
    global _retrieval_module
    _retrieval_module = module


def set_startup_state(
    ready: bool,
    status_value: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """애플리케이션 startup/readiness 상태 설정."""
    global _startup_state
    _startup_state = {
        "ready": ready,
        "status": status_value or ("ready" if ready else "not_ready"),
        "details": details or {},
    }


def reset_health_state() -> None:
    """테스트와 재초기화를 위한 health 상태 초기화."""
    global _retrieval_module, _startup_state
    _retrieval_module = None
    _startup_state = {
        "ready": False,
        "status": "starting",
        "details": {},
    }


# 시작 시간 기록
start_time = time.time()


class HealthResponse(BaseModel):
    """Health 체크 응답 모델"""

    status: str
    timestamp: str
    uptime: float
    version: str = "2.0.0"
    environment: str


class ReadinessResponse(BaseModel):
    """Readiness 체크 응답 모델"""

    status: str
    timestamp: str
    uptime: float
    environment: str
    checks: dict[str, Any]


class StatsResponse(BaseModel):
    """시스템 통계 응답 모델"""

    uptime: float
    uptime_human: str
    cpu_percent: float
    memory_usage: dict[str, Any]
    disk_usage: dict[str, Any]
    system_info: dict[str, Any]


def get_uptime() -> float:
    """업타임 반환 (초)"""
    return time.time() - start_time


def format_uptime(seconds: float) -> str:
    """업타임 포맷팅"""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def get_memory_info() -> dict[str, Any]:
    """메모리 사용량 정보"""
    memory = psutil.virtual_memory()
    return {
        "total": memory.total,
        "available": memory.available,
        "used": memory.used,
        "percentage": memory.percent,
        "total_gb": round(memory.total / (1024**3), 2),
        "used_gb": round(memory.used / (1024**3), 2),
        "available_gb": round(memory.available / (1024**3), 2),
    }


def get_disk_info() -> dict[str, Any]:
    """디스크 사용량 정보"""
    disk = psutil.disk_usage("/")
    return {
        "total": disk.total,
        "used": disk.used,
        "free": disk.free,
        "percentage": round((disk.used / disk.total) * 100, 2),
        "total_gb": round(disk.total / (1024**3), 2),
        "used_gb": round(disk.used / (1024**3), 2),
        "free_gb": round(disk.free / (1024**3), 2),
    }


def get_system_info() -> dict[str, Any]:
    """시스템 정보"""
    return {
        "platform": os.name,
        "python_version": sys.version.split()[0],
        "cpu_count": psutil.cpu_count(),
        "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
    }


def get_environment_name() -> str:
    """Runtime 환경 이름 반환."""
    return os.getenv("ENVIRONMENT") or os.getenv("NODE_ENV", "development")


def _component_is_unhealthy(value: Any) -> bool:
    """Readiness checks can return bools or small status dictionaries."""
    if value is None:
        return False
    if isinstance(value, bool):
        return not value
    if isinstance(value, dict):
        if "error" in value:
            return True
        if isinstance(value.get("healthy"), bool):
            return not value["healthy"]
        component_status = value.get("status")
        if isinstance(component_status, str):
            if component_status.lower() in {
                "error",
                "failed",
                "unhealthy",
                "not_configured",
                "not_ready",
                "unknown",
            }:
                return True
        return any(
            _component_is_unhealthy(child)
            for key, child in value.items()
            if key != "status"
        )
    return False


async def _collect_retrieval_readiness() -> dict[str, Any]:
    if _retrieval_module is None:
        return {"status": "not_configured", "message": "Retrieval module not initialized"}

    health_check = getattr(_retrieval_module, "health_check", None)
    if not callable(health_check):
        return {"status": "unknown", "message": "Retrieval module has no health_check"}

    result = health_check()
    if hasattr(result, "__await__"):
        result = await result

    return {"status": "checked", "components": result}


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """기본 헬스 체크"""
    try:
        return HealthResponse(
            status="OK",
            timestamp=datetime.now().isoformat(),
            uptime=get_uptime(),
            environment=get_environment_name(),
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthResponse(
            status="ERROR",
            timestamp=datetime.now().isoformat(),
            uptime=get_uptime(),
            environment=get_environment_name(),
        )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(response: Response):
    """서비스 readiness 체크: startup 및 필수 의존성 상태를 확인합니다."""
    checks: dict[str, Any] = {"startup": _startup_state}
    response_status = "ready"

    if not _startup_state.get("ready", False):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="not_ready",
            timestamp=datetime.now().isoformat(),
            uptime=get_uptime(),
            environment=get_environment_name(),
            checks=checks,
        )

    try:
        retrieval_check = await _collect_retrieval_readiness()
    except Exception as e:
        logger.warning("Readiness retrieval check failed", extra={"error": str(e)}, exc_info=True)
        retrieval_check = {"status": "error", "error": str(e)}

    checks["retrieval"] = retrieval_check

    if _component_is_unhealthy(retrieval_check):
        if is_retrieval_required():
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            response_status = "not_ready"
        else:
            response_status = "degraded"

    return ReadinessResponse(
        status=response_status,
        timestamp=datetime.now().isoformat(),
        uptime=get_uptime(),
        environment=get_environment_name(),
        checks=checks,
    )


@router.get("/stats", response_model=StatsResponse)
async def system_stats():
    """시스템 통계"""
    try:
        uptime = get_uptime()

        return StatsResponse(
            uptime=uptime,
            uptime_human=format_uptime(uptime),
            cpu_percent=psutil.cpu_percent(interval=0.1),
            memory_usage=get_memory_info(),
            disk_usage=get_disk_info(),
            system_info=get_system_info(),
        )
    except Exception as e:
        logger.error(f"Stats collection failed: {e}")
        raise


@router.get("/ping")
async def ping():
    """간단한 ping 엔드포인트"""
    return {"message": "pong", "timestamp": datetime.now().isoformat()}


@router.get("/cache-stats")
async def cache_stats():
    """리랭킹 캐시 통계 (Phase 1-3 개선)

    Returns:
        dict: 캐시 통계 정보
            - cache_size: 현재 캐시 항목 수
            - max_size: 최대 캐시 크기
            - hit_rate: 캐시 히트율 (0.0 ~ 1.0)
            - total_requests: 총 리랭킹 요청 수
            - hits: 캐시 히트 수
            - misses: 캐시 미스 수
            - saved_time_ms: 절약된 총 시간 (밀리초)
            - avg_rerank_time_ms: 평균 리랭킹 소요 시간 (밀리초)
    """
    try:
        if _retrieval_module is None:
            return {
                "status": "unavailable",
                "message": "Retrieval module not initialized",
                "timestamp": datetime.now().isoformat(),
            }

        cache_stats = _retrieval_module.get_cache_stats()

        return {"status": "ok", "timestamp": datetime.now().isoformat(), **cache_stats}
    except Exception as e:
        logger.error(f"Cache stats collection failed: {e}")
        return {"status": "error", "message": str(e), "timestamp": datetime.now().isoformat()}
