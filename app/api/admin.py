"""
Admin API endpoints
관리자 API 엔드포인트
"""

import asyncio
import json
import os
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..lib.auth import get_api_key, get_api_key_auth
from ..lib.logger import get_logger
from .admin_ai_settings_store import (
    can_persist_provider_keys,
    canonical_provider,
    get_admin_ai_settings_store,
)
from .analytics_event_store import get_analytics_event_store
from .services.openai_model_resolver import list_available_models, parse_model, resolve_model_config

logger = get_logger(__name__)

# v3.3.0: 라우터 수준에서 전역 인증 적용 (보안 강화)
router = APIRouter(
    prefix="/api/admin",
    tags=["Admin"],
    dependencies=[Depends(get_api_key)]
)
websocket_router = APIRouter(prefix="/api/admin", tags=["Admin"])

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


class AISettingsUpdate(BaseModel):
    provider: str
    model: str


class AIProviderKeyUpdate(BaseModel):
    apiKey: str


class AISettingsTestRequest(BaseModel):
    provider: str
    model: str


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
            stats = await retrieval_module.get_document_stats()
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
                    config=mask_sensitive_data(module_config),
                    stats=mask_sensitive_data(module_stats),
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
        safe_config = mask_sensitive_data(config)
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


SUPPORTED_GENERATION_PROVIDERS = {"google", "openai", "openrouter", "ollama"}


def _build_ai_catalog() -> dict[str, Any]:
    """Build a provider/model catalog for admin settings."""
    store = get_admin_ai_settings_store()
    provider_models = _catalog_provider_models()
    providers = []
    for provider in sorted(SUPPORTED_GENERATION_PROVIDERS):
        models = provider_models[provider]
        providers.append(
            {
                "id": provider,
                "label": {
                    "google": "Google Gemini",
                    "openai": "OpenAI",
                    "openrouter": "OpenRouter",
                    "ollama": "Ollama",
                }.get(provider, provider),
                "models": models,
                "key": store.get_key_metadata(provider),
            }
        )
    return {"providers": providers}


def _catalog_provider_models() -> dict[str, list[dict[str, str]]]:
    provider_models: dict[str, list[dict[str, str]]] = {
        provider: [] for provider in sorted(SUPPORTED_GENERATION_PROVIDERS)
    }
    for model_info in list_available_models():
        model_id = model_info.get("id", "")
        try:
            provider, sub_model = parse_model(model_id)
            resolved = resolve_model_config(provider, sub_model)
        except ValueError:
            continue
        resolved_provider = canonical_provider(resolved["provider"])
        if resolved_provider not in SUPPORTED_GENERATION_PROVIDERS:
            continue
        provider_models.setdefault(resolved_provider, []).append(
            {
                "id": resolved["model"],
                "label": model_id,
                "description": model_info.get("description", ""),
            }
        )

    fallback_models = {
        "google": [{"id": "gemini-2.0-flash", "label": "gemini-2.0-flash"}],
        "openai": [{"id": "gpt-4o", "label": "gpt-4o"}],
        "openrouter": [{"id": "google/gemini-2.5-flash", "label": "google/gemini-2.5-flash"}],
        "ollama": [{"id": "llama3.2", "label": "llama3.2"}],
    }
    catalog: dict[str, list[dict[str, str]]] = {}
    for provider in sorted(SUPPORTED_GENERATION_PROVIDERS):
        models = provider_models.get(provider) or fallback_models[provider]
        # Stable de-duplication by concrete model id.
        catalog[provider] = list({model["id"]: model for model in models}.values())
    return catalog


def _running_generation_info() -> dict[str, Any]:
    generation_module = modules.get("generation")
    return {
        "provider": getattr(generation_module, "provider", None),
        "model": getattr(generation_module, "default_model", None),
        "available": bool(generation_module),
    }


def _validate_ai_settings(provider: str, model: str) -> tuple[str, str]:
    resolved_provider = _validate_provider(provider)
    resolved_model = str(model or "").strip()
    if not resolved_model:
        raise HTTPException(status_code=400, detail="model is required")
    valid_model_ids = {model["id"] for model in _catalog_provider_models()[resolved_provider]}
    if resolved_model not in valid_model_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model for {resolved_provider}: {resolved_model}",
        )
    return resolved_provider, resolved_model


def _validate_provider(provider: str) -> str:
    resolved_provider = canonical_provider(provider)
    if resolved_provider not in SUPPORTED_GENERATION_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported generation provider: {provider}",
        )
    return resolved_provider


@router.get("/ai-settings")
async def get_ai_settings():
    """Return active AI settings and provider key metadata without raw keys."""
    try:
        store = get_admin_ai_settings_store()
        settings = store.get_settings()
        running = _running_generation_info()
        catalog = _build_ai_catalog()
        return {
            "settings": settings,
            "running": running,
            "catalog": catalog,
            "applyMode": "request_model_override",
            "restartRequired": bool(settings.get("configured"))
            and (
                bool(settings.get("restartRequired"))
                or settings.get("provider") != running.get("provider")
            ),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as error:
        logger.error(
            "AI 설정 조회 실패",
            extra={"error": str(error), "error_type": type(error).__name__},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve AI settings") from error


@router.patch("/ai-settings")
async def update_ai_settings(payload: AISettingsUpdate):
    """Persist provider/model settings server-side."""
    provider, model = _validate_ai_settings(payload.provider, payload.model)
    try:
        store = get_admin_ai_settings_store()
        previous_settings = store.get_settings()
        settings = store.update_settings(provider, model)
        running = _running_generation_info()
        restart_required = provider != running.get("provider") or (
            bool(previous_settings.get("restartRequired"))
            and previous_settings.get("provider") == running.get("provider")
            and provider == running.get("provider")
        )
        if not restart_required:
            store.set_restart_required(False)
            settings = store.get_settings()
        return {
            "settings": settings,
            "running": running,
            "restartRequired": restart_required,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as error:
        logger.error(
            "AI 설정 저장 실패",
            extra={"error": str(error), "error_type": type(error).__name__},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update AI settings") from error


@router.put("/ai-settings/providers/{provider}/key")
async def replace_ai_provider_key(provider: str, payload: AIProviderKeyUpdate):
    """Replace a provider API key. The raw key is write-only."""
    resolved_provider = _validate_provider(provider)
    if not payload.apiKey or not payload.apiKey.strip():
        raise HTTPException(status_code=400, detail="apiKey is required")
    if not can_persist_provider_keys():
        raise HTTPException(
            status_code=400,
            detail=(
                "Provider key replacement requires ONERAG_SETTINGS_SECRET "
                "or FASTAPI_AUTH_KEY so the key can be encrypted at rest"
            ),
        )
    try:
        store = get_admin_ai_settings_store()
        if not store.get_settings().get("configured"):
            raise HTTPException(
                status_code=400,
                detail="Save provider/model settings before replacing a provider key",
            )
        metadata = store.replace_provider_key(
            resolved_provider, payload.apiKey
        )
        return {
            "provider": resolved_provider,
            "key": metadata,
            "restartRequired": True,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error(
            "AI provider key 교체 실패",
            extra={"provider": resolved_provider, "error": str(error)},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to replace provider key") from error


@router.post("/ai-settings/test")
async def test_ai_settings(payload: AISettingsTestRequest):
    """Dry-run validate provider/model/key availability without echoing secrets."""
    provider, model = _validate_ai_settings(payload.provider, payload.model)
    store = get_admin_ai_settings_store()
    key_metadata = store.get_key_metadata(provider)
    requires_key = provider != "ollama"
    configured = bool(key_metadata.get("configured")) or not requires_key
    return {
        "provider": provider,
        "model": model,
        "ok": configured,
        "mode": "dry_run",
        "message": (
            "Provider key is configured"
            if configured
            else "Provider key is not configured"
        ),
        "key": key_metadata,
        "timestamp": datetime.now().isoformat(),
    }


@router.post("/ai-settings/apply")
async def apply_ai_settings():
    """Report conservative runtime application status."""
    store = get_admin_ai_settings_store()
    settings = store.get_settings()
    running = _running_generation_info()
    restart_required = bool(settings.get("configured")) and (
        bool(settings.get("restartRequired"))
        or settings.get("provider") != running.get("provider")
    )
    store.set_restart_required(restart_required)
    return {
        "settings": store.get_settings(),
        "running": running,
        "applied": bool(settings.get("configured")) and not restart_required,
        "restartRequired": restart_required,
        "message": (
            "Model override is applied per chat request"
            if settings.get("configured") and not restart_required
            else "No admin AI setting has been saved"
            if not settings.get("configured")
            else "Provider or key changes require service restart to rebuild clients"
        ),
        "timestamp": datetime.now().isoformat(),
    }


def mask_sensitive_data(data: Any) -> Any:
    """민감한 데이터 마스킹"""
    if isinstance(data, dict):
        masked = {}
        for key, value in data.items():
            if any(
                sensitive in key.lower() for sensitive in ["key", "secret", "password", "token"]
            ):
                if isinstance(value, str) and len(value) > 4:
                    masked[key] = f"****{value[-4:]}"
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

        # Phase 2.5: 가짜 random 값 제거 — 실제 성능 메트릭에서 집계한다.
        # 별도 요청-카운터(분당 요청 수)는 아직 추적하지 않으므로 0으로 둔다(정직).
        chat_requests_per_minute = 0
        average_response_time = 0.0
        error_rate = 0.0
        perf_module = modules.get("performance_metrics")
        if perf_module and hasattr(perf_module, "get_all_stats"):
            try:
                all_stats = perf_module.get_all_stats()
                func_stats = [
                    s
                    for s in all_stats.values()
                    if isinstance(s, dict) and "avg_latency_ms" in s
                ]
                # total_calls는 누적 성공 호출 수(total_calls 필드), count는 최근 윈도우(≤100).
                # error_rate 분모에 윈도우 count를 쓰면 누적 에러 ÷ 최근 100건이 되어
                # 100%를 초과하는 왜곡이 생기므로 누적 분모를 사용한다.
                total_calls = sum(s.get("total_calls", 0) for s in func_stats)
                total_errors = sum(s.get("errors", 0) for s in func_stats)
                window_calls = sum(s.get("count", 0) for s in func_stats)
                if window_calls > 0:
                    # 최근 윈도우 기준 가중 평균 응답시간(ms → s) — '최근' 평균임을 명시
                    weighted = sum(
                        s.get("avg_latency_ms", 0) * s.get("count", 0) for s in func_stats
                    )
                    average_response_time = round(weighted / window_calls / 1000, 2)
                if total_calls + total_errors > 0:
                    # 에러 발생 호출은 record_latency가 호출되지 않으므로
                    # 분모 = 성공(누적 total_calls) + 에러(누적 errors)
                    error_rate = round(total_errors / (total_calls + total_errors) * 100, 2)
            except Exception as e:
                logger.warning(
                    "성능 메트릭 조회 실패",
                    extra={"error": str(e), "error_type": type(e).__name__},
                )

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
        if cost_tracker_module and hasattr(cost_tracker_module, "get_summary"):
            try:
                cost_summary = cost_tracker_module.get_summary()
                total_cost_usd = cost_summary.get("total_cost_usd", 0.0)
                cost_per_hour = cost_summary.get("cost_per_hour", 0.0)
                total_llm_tokens = cost_summary.get("total_tokens", 0)
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
        period_days = _period_to_days(period)
        store = get_analytics_event_store()
        summary = store.summary(days=period_days)
        time_series = store.timeseries(months=max(1, period_days // 31), grain="day")
        return {
            "period": period,
            "totalSessions": summary["sessions"],
            "totalQueries": summary["questions"],
            "avgResponseTime": round(summary["avgLatencyMs"] / 1000, 2),
            "timeSeries": [
                {
                    "date": row["bucket"],
                    "sessions": row["sessions"],
                    "queries": row["questions"],
                    "avgResponseTime": round(row["avgLatencyMs"] / 1000, 2),
                }
                for row in time_series
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


def _period_to_days(period: str) -> int:
    normalized = str(period or "7d").strip().lower()
    if normalized.endswith("d"):
        try:
            return max(1, min(int(normalized[:-1]), 366))
        except ValueError:
            return 7
    if normalized.endswith("m"):
        try:
            return max(1, min(int(normalized[:-1]), 12)) * 31
        except ValueError:
            return 31
    if normalized.endswith("y"):
        try:
            return max(1, min(int(normalized[:-1]), 2)) * 366
        except ValueError:
            return 366
    return 7


@router.get("/analytics/summary")
async def get_analytics_summary(days: int = 365):
    """12개월 운영 통계 요약."""
    try:
        bounded_days = max(1, min(days, 366))
        return {
            "summary": get_analytics_event_store().summary(days=bounded_days),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as error:
        logger.error("analytics summary 조회 실패", extra={"error": str(error)}, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve analytics summary") from error


@router.get("/analytics/timeseries")
async def get_analytics_timeseries(months: int = 12, grain: str = "month"):
    """월/일 단위 운영 통계 시계열."""
    try:
        bounded_months = max(1, min(months, 12))
        resolved_grain = "day" if grain == "day" else "month"
        return {
            "grain": resolved_grain,
            "months": bounded_months,
            "series": get_analytics_event_store().timeseries(
                months=bounded_months,
                grain=resolved_grain,
            ),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as error:
        logger.error("analytics timeseries 조회 실패", extra={"error": str(error)}, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve analytics timeseries") from error


@router.get("/analytics/models")
async def get_analytics_model_usage(days: int = 365):
    """모델/Provider별 사용량."""
    try:
        bounded_days = max(1, min(days, 366))
        return {
            "models": get_analytics_event_store().model_usage(days=bounded_days),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as error:
        logger.error("analytics models 조회 실패", extra={"error": str(error)}, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve analytics models") from error


def _langfuse_settings() -> dict[str, Any]:
    enabled = os.getenv("LANGFUSE_ENABLED", "").strip().lower() not in {
        "false",
        "0",
        "no",
        "off",
    }
    host = (os.getenv("LANGFUSE_HOST") or "https://cloud.langfuse.com").rstrip("/")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    return {
        "enabled": enabled,
        "host": host,
        "publicKeyConfigured": bool(public_key),
        "secretKeyConfigured": bool(secret_key),
        "configured": enabled and bool(public_key and secret_key),
        "publicKey": public_key,
        "secretKey": secret_key,
    }


def _redact_preview(value: Any, *, limit: int = 220) -> str | None:
    if value is None:
        return None
    text = str(value)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email]", text)
    text = re.sub(r"\b\d{2,3}[-.\s]?\d{3,4}[-.\s]?\d{4}\b", "[phone]", text)
    text = re.sub(r"(sk|pk|api)[-_][A-Za-z0-9]{12,}", "[secret]", text)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 1] + "..."
    return text


def _sanitize_langfuse_trace(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}
    total_tokens = row.get("totalTokens") or usage.get("total") or usage.get("totalUsage")
    latency_ms = row.get("latencyMs") or row.get("latency_ms")
    if latency_ms is None and row.get("latency") is not None:
        try:
            latency_ms = round(float(row["latency"]) * 1000, 2)
        except (TypeError, ValueError):
            latency_ms = None
    return {
        "traceId": row.get("id") or row.get("traceId"),
        "name": _redact_preview(row.get("name"), limit=120),
        "timestamp": row.get("timestamp") or row.get("createdAt"),
        "sessionId": _redact_preview(row.get("sessionId"), limit=80),
        "userId": _redact_preview(row.get("userId"), limit=80),
        "model": _redact_preview(metadata.get("model") or metadata.get("model_name"), limit=120),
        "latencyMs": latency_ms,
        "totalTokens": total_tokens,
        "totalCost": row.get("totalCost"),
    }


def _parse_trace_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_trace_within_retention(row: dict[str, Any], *, days: int) -> bool:
    timestamp = _parse_trace_timestamp(row.get("timestamp") or row.get("createdAt"))
    if timestamp is None:
        return False
    return timestamp >= datetime.now(UTC) - timedelta(days=days)


@router.get("/langfuse/status")
async def get_langfuse_status():
    """Langfuse server-side integration status."""
    settings = _langfuse_settings()
    return {
        "available": settings["configured"],
        "enabled": settings["enabled"],
        "host": settings["host"],
        "publicKeyConfigured": settings["publicKeyConfigured"],
        "secretKeyConfigured": settings["secretKeyConfigured"],
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/langfuse/daily-metrics")
async def get_langfuse_daily_metrics(limit: int = 30):
    """Proxy Langfuse daily metrics through the admin API."""
    settings = _langfuse_settings()
    if not settings["configured"]:
        return {
            "available": False,
            "reason": "Langfuse is not configured",
            "data": [],
            "timestamp": datetime.now().isoformat(),
        }
    try:
        import httpx

        bounded_limit = max(1, min(limit, 366))
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings['host']}/api/public/metrics/daily",
                auth=(settings["publicKey"], settings["secretKey"]),
                params={"limit": bounded_limit},
            )
            response.raise_for_status()
        payload = response.json()
        return {
            "available": True,
            "data": payload.get("data", []),
            "meta": payload.get("meta", {}),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as error:
        logger.warning("Langfuse daily metrics 조회 실패", extra={"error": str(error)})
        return {
            "available": False,
            "reason": "Langfuse metrics request failed",
            "data": [],
            "timestamp": datetime.now().isoformat(),
        }


@router.get("/langfuse/traces")
async def get_langfuse_traces(limit: int = 25):
    """Proxy recent Langfuse traces as redacted summaries."""
    settings = _langfuse_settings()
    if not settings["configured"]:
        return {
            "available": False,
            "reason": "Langfuse is not configured",
            "traces": [],
            "retentionDays": 7,
            "timestamp": datetime.now().isoformat(),
        }
    try:
        import httpx

        bounded_limit = max(1, min(limit, 100))
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings['host']}/api/public/traces",
                auth=(settings["publicKey"], settings["secretKey"]),
                params={"limit": bounded_limit},
            )
            response.raise_for_status()
        payload = response.json()
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        retained_rows = [
            row
            for row in rows
            if isinstance(row, dict) and _is_trace_within_retention(row, days=7)
        ]
        return {
            "available": True,
            "traces": [
                _sanitize_langfuse_trace(row)
                for row in retained_rows
            ],
            "retentionDays": 7,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as error:
        logger.warning("Langfuse traces 조회 실패", extra={"error": str(error)})
        return {
            "available": False,
            "reason": "Langfuse traces request failed",
            "traces": [],
            "retentionDays": 7,
            "timestamp": datetime.now().isoformat(),
        }


@router.get("/keywords")
async def get_keywords(period: str = "7d"):
    """주요 키워드 분석 (실제 집계 미구현 — 빈 결과 반환)"""
    # Phase 2.5: 하드코딩 가짜 통계 제거. 가짜 데이터로 운영 판단을 오도하지 않기 위해
    # 실제 키워드 집계가 구현되기 전까지 빈 리스트를 반환한다.
    logger.info("키워드 집계 미구현 — 빈 결과 반환", extra={"period": period})
    return {"keywords": []}


@router.get("/chunks")
async def get_chunks(period: str = "7d"):
    """자주 사용된 청크 분석 (실제 집계 미구현 — 빈 결과 반환)"""
    # Phase 2.5: 하드코딩 가짜 통계 제거 (가짜 문서명으로 운영 판단 오도 방지).
    logger.info("청크 집계 미구현 — 빈 결과 반환", extra={"period": period})
    return {"chunks": []}


@router.get("/countries")
async def get_countries(period: str = "7d"):
    """접속 국가 통계 (실제 집계 미구현 — 빈 결과 반환)"""
    # Phase 2.5: 하드코딩 가짜 통계 제거 (가짜 국가 분포로 운영 판단 오도 방지).
    logger.info("국가 집계 미구현 — 빈 결과 반환", extra={"period": period})
    return {"countries": []}


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


@websocket_router.websocket("/ws")
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
