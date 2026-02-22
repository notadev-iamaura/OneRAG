"""
OneRAG FastAPI Application
한국어 RAG 시스템의 메인 애플리케이션
"""

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

# ⚠️ 중요: 환경 변수를 가장 먼저 로드 (다른 모든 import보다 먼저!)
from dotenv import load_dotenv

# 절대 경로로 .env 파일 명시적 로드
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    print(f"⚠️ .env 파일을 찾을 수 없습니다: {env_path}")

# LangSmith 트레이싱 import
try:
    from langchain_core.tracers.langchain import wait_for_all_tracers

    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Add app directory to path
app_dir = Path(__file__).parent / "app"
sys.path.append(str(app_dir))

# TASK-H3: DI Container import
from app.api import (
    admin,
    chat,
    documents,
    evaluations,  # 평가 API 추가
    health,
    image_chat,  # 이미지 채팅 API 추가 (멀티모달)
    ingest,  # Phase 8: 데이터 적재 API
    langsmith_logs,
    monitoring,  # 모니터링 API 추가
    prompts,
    upload,
)
from app.api.routers import (
    admin_eval_router,  # 관리자 평가 API 라우터
    set_admin_config,  # 관리자 라우터 설정 주입
    set_session_module,  # ✅ Task 5: 세션 모듈 주입
    tools_router,  # Tool Use API 라우터
    weaviate_admin_router,  # Weaviate 관리 API 라우터
    websocket_router,  # ✅ Task 4: WebSocket 채팅 라우터
)

# from app.batch.scheduler import BatchScheduler  # Moved to legacy
from app.core.di_container import (
    AppContainer,
    cleanup_resources,
    initialize_async_resources,
    initialize_async_resources_graceful,  # Graceful Degradation 지원
)
from app.infrastructure.persistence.connection import db_manager  # PostgreSQL 연결 관리자
from app.lib.auth import get_api_key_auth  # API Key 인증
from app.lib.config_loader import ConfigLoader
from app.lib.env_validator import EnvValidator, validate_all_env
from app.lib.logger import get_logger

# Phase 1.3: 신규 Retrieval Architecture (Orchestrator Pattern)

logger = get_logger(__name__)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)


class RAGChatbotApp:
    """RAG 챗봇 메인 애플리케이션 클래스 (DI Container 기반)"""

    def __init__(self) -> None:
        # TASK-H3: DI Container 기반 아키텍처
        self.container = AppContainer()
        self.config: dict[str, Any] | None = None
        self.app = None

    async def initialize_modules(self) -> None:
        """모듈 초기화 (DI Container 기반)"""
        import time

        try:
            start_time = time.time()
            logger.info("🔧 Initializing modules via DI Container...")

            # Phase 1: Configuration 로드
            logger.info("📋 Loading configuration...")

            # Feature Flag: 신규 모듈화된 Pydantic 스키마 사용 여부
            # 환경 변수 USE_MODULAR_SCHEMA=true로 설정하면 신규 스키마 사용
            use_modular_schema = os.getenv("USE_MODULAR_SCHEMA", "false").lower() == "true"

            # 개발 환경에서는 검증 실패 시 명확한 에러 (프로덕션에서는 Graceful Degradation)
            is_development = os.getenv("NODE_ENV", "development") == "development"

            config_loader = ConfigLoader()
            self.config = config_loader.load_config(
                validate=True,
                use_modular_schema=use_modular_schema,
                raise_on_validation_error=is_development,  # 개발 환경에서만 에러 발생
            )

            # Container에 설정 주입
            self.container.config.from_dict(self.config)

            # Feature Flag: Graceful Degradation 활성화 여부 체크
            enable_graceful_degradation = (
                os.getenv("ENABLE_GRACEFUL_DEGRADATION", "false").lower() == "true"
            )

            # Phase 2-5: Container의 AsyncIO 리소스 초기화
            if enable_graceful_degradation:
                logger.info("🛡️  Graceful Degradation mode enabled")
                await initialize_async_resources_graceful(self.container)
            else:
                logger.info("📦 Standard initialization mode")
                # (내부적으로 5-phase 패턴 실행: Phase 1 LLM Factory → Phase 3 병렬 → Phase 5 순차)
                await initialize_async_resources(self.container)

            total_time = time.time() - start_time
            logger.info("=" * 60)
            logger.info("✅ All modules initialized successfully via Container")
            logger.info(f"⏱️  Total time: {total_time:.2f}s")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"❌ Module initialization failed: {e}", exc_info=True)
            raise

    async def cleanup_modules(self) -> None:
        """모듈 정리 (DI Container 기반)"""
        try:
            logger.info("🧹 Cleaning up modules via Container...")
            await cleanup_resources(self.container)
            logger.info("✅ Module cleanup completed")
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")

    def get_modules_dict(self) -> dict[str, Any]:
        """
        라우터 의존성 주입을 위한 모듈 딕셔너리 반환

        기존 코드 호환성 유지:
        - chat.set_dependencies(rag_app.modules, rag_app.config) 패턴 지원
        - Container providers를 dict 형태로 변환

        Returns:
            모듈 이름 → 모듈 인스턴스 매핑 딕셔너리
        """
        # query_expansion은 추상 메서드 미구현으로 인해 optional 처리
        try:
            query_expansion = self.container.query_expansion()
        except TypeError as e:
            logger.warning(f"⚠️ Query expansion provider failed: {e}, using None")
            query_expansion = None

        return {
            "llm_factory": self.container.llm_factory(),
            # "ip_geolocation": self.container.ip_geolocation(),  # 비활성화: 세션 생성 타임아웃 원인 (DI 컨테이너에서 제거됨)
            "session": self.container.session(),
            "document_processor": self.container.document_processor(),
            "generation": self.container.generation(),
            "evaluation": self.container.evaluation(),
            # retrieval Factory는 async이므로, 이미 초기화된 Singleton인 retrieval_orchestrator 사용
            # retrieval_orchestrator는 .search() 등 동일한 인터페이스를 제공
            "retrieval": self.container.retrieval_orchestrator(),
            "retrieval_orchestrator": self.container.retrieval_orchestrator(),
            "query_router": self.container.query_router(),
            "query_expansion": query_expansion,
            "self_rag": self.container.self_rag(),
            "circuit_breaker_factory": self.container.circuit_breaker_factory(),  # ✅ Circuit Breaker Factory 추가
            "sql_search_service": self.container.sql_search_service(),  # ✅ SQL Search Service 추가 (Phase 3)
        }


# 글로벌 앱 인스턴스
rag_app = RAGChatbotApp()

# Rate Limiter 인스턴스 (전역 생성 - lifespan에서 cleanup task 관리)
from app.middleware.rate_limiter import RateLimiter

rate_limiter = RateLimiter(
    ip_limit=30,  # IP 기반: 분당 30개
    session_limit=10,  # Session 기반: 분당 10개
    window_seconds=60,  # 1분 윈도우
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """애플리케이션 라이프사이클 관리"""
    # LangSmith 트레이싱 설정
    langsmith_enabled = False

    # 시작 시
    try:
        logger.info("🚀 Starting OneRAG Application...")

        # NOTE: Legacy Batch Crawler startup logic removed (Moved to Ingestion API)
        # See app/api/ingest.py for new usage.

        # 환경 변수 검증 (CRITICAL: 필수 환경 변수 확인)
        logger.info("🔍 환경 변수 검증 시작...")
        validation_result = validate_all_env(strict=False)

        if not validation_result.is_valid:
            missing_vars = validation_result.missing_vars
            help_message = EnvValidator.get_missing_env_help(missing_vars)
            logger.error(f"❌ 필수 환경 변수 누락:\n{help_message}")

            # 필수 환경 변수 없으면 서비스 시작 중단
            if missing_vars:
                raise RuntimeError(
                    f"필수 환경 변수 누락: {', '.join(missing_vars)}\n"
                    "서비스를 시작할 수 없습니다. 환경 변수를 설정해주세요."
                )

        if validation_result.warnings:
            for warning in validation_result.warnings:
                logger.warning(f"⚠️ {warning}")

        logger.info("✅ 환경 변수 검증 완료")

        # 🚨 보안 강화: 프로덕션 환경에서 필수 환경 변수 추가 검증
        from app.lib.environment import is_production_environment, validate_required_env_vars

        if is_production_environment():
            logger.info("🔒 프로덕션 환경 감지 - 필수 환경 변수 검증...")
            validate_required_env_vars()  # FASTAPI_AUTH_KEY 등 필수 검증
            logger.info("✅ 프로덕션 필수 환경 변수 검증 완료")

        # PostgreSQL 데이터베이스 초기화 (Railway 배포용)
        try:
            logger.info("🔧 PostgreSQL 연결 초기화 중...")
            await db_manager.initialize()

            logger.info("📦 데이터베이스 테이블 생성 중...")
            await db_manager.create_tables()

            logger.info("✅ PostgreSQL 초기화 완료!")
        except Exception as e:
            logger.warning(f"⚠️ PostgreSQL 초기화 실패 (무시하고 계속): {e}")

        # Weaviate 자동 초기화 (Railway 배포용)
        if os.getenv("WEAVIATE_AUTO_INIT", "false").lower() == "true":
            try:
                logger.info("🔧 Weaviate 자동 초기화 시작...")

                from app.lib.weaviate_setup import create_schema

                # 스키마 생성
                schema_created = await create_schema()

                if schema_created:
                    logger.info("✅ Weaviate 스키마 초기화 완료!")

                    # 데이터 자동 인덱싱 (옵션)
                    if os.getenv("WEAVIATE_AUTO_INDEX", "false").lower() == "true":
                        logger.info("📊 데이터 자동 인덱싱 시작...")

                        from scripts.index_all_data import index_all_data

                        result = await index_all_data()
                        logger.info(
                            f"✅ 데이터 인덱싱 완료: {result['count']}개 문서 ({result['duration']:.2f}초)"
                        )
                else:
                    logger.warning("⚠️ Weaviate 스키마 생성 실패")

            except Exception as e:
                logger.warning(f"⚠️ Weaviate 자동 초기화 실패 (무시하고 계속): {e}")

        # LangSmith 트레이싱 초기화 (환경변수 기반)
        if LANGSMITH_AVAILABLE:
            langsmith_tracing = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
            langsmith_api_key = os.getenv("LANGSMITH_API_KEY")
            langsmith_project = os.getenv("LANGSMITH_PROJECT", "moneywork-chatbot")

            if langsmith_tracing and langsmith_api_key:
                # 환경변수를 통해 LangSmith 자동 활성화
                os.environ["LANGCHAIN_TRACING_V2"] = "true"
                os.environ["LANGCHAIN_PROJECT"] = langsmith_project
                langsmith_enabled = True
                logger.info(f"📊 LangSmith tracing enabled for project: {langsmith_project}")
            else:
                logger.info("📊 LangSmith tracing disabled")
        else:
            logger.info("📊 LangSmith not available")

        # 모듈 초기화 (DI Container 기반)
        await rag_app.initialize_modules()

        # Container providers → dict 변환 (라우터 호환성)
        modules_dict = rag_app.get_modules_dict()

        # Config 초기화 검증 (타입 안전성)
        assert rag_app.config is not None, "Config must be initialized before router setup"

        # 라우터에 의존성 주입
        chat.set_dependencies(modules_dict, rag_app.config)
        upload.set_dependencies(modules_dict, rag_app.config)
        documents.set_dependencies(modules_dict, rag_app.config)
        admin.set_dependencies(modules_dict, rag_app.config)
        # Phase 1-3 개선: retrieval 모듈을 health API에 전달
        health.set_retrieval_module(modules_dict["retrieval"])
        # 평가 라우터 초기화
        evaluations.init_evaluation_router(modules_dict["evaluation"])
        # Admin 평가 라우터에 설정 주입
        set_admin_config(rag_app.config)
        # ✅ Task 5: Admin 라우터에 세션 모듈 주입
        set_session_module(modules_dict["session"])

        # Tool Use 라우터 초기화 (DI Container에서 주입)
        tool_executor = rag_app.container.tool_executor()
        tools_router.set_tool_executor(tool_executor)
        logger.info("✅ ToolExecutor 초기화 및 주입 완료 (DI Container)")

        # ✅ Task 4: WebSocket 라우터에 ChatService 주입
        from app.api.services.chat_service import ChatService

        chat_service_instance = ChatService(modules_dict, rag_app.config)
        websocket_router.set_chat_service(chat_service_instance)
        logger.info("✅ WebSocket 라우터에 ChatService 주입 완료")

        # Rate Limiter cleanup task 시작 (24시간 주기 메모리 정리)
        rate_limiter.start_cleanup_task()
        logger.info("✅ Rate Limiter cleanup task started")

        logger.info("✅ Application started successfully")

    except Exception as e:
        logger.error(f"❌ Failed to start application: {e}")
        raise

    yield

    # 종료 시
    try:
        # Rate Limiter cleanup task 중지
        await rate_limiter.stop_cleanup_task()
        logger.info("✅ Rate Limiter cleanup task stopped")

        # Tool Executor 리소스 정리 (httpx AsyncClient 종료, DI Container에서)
        try:
            tool_executor = rag_app.container.tool_executor()
            await tool_executor.cleanup()
        except Exception as e:
            logger.warning(f"⚠️ Tool Executor cleanup warning: {e}")

        await rag_app.cleanup_modules()

        # PostgreSQL 연결 종료 (안전하게 처리)
        try:
            if db_manager._initialized:
                await db_manager.close()
        except Exception as e:
            logger.warning(f"⚠️ PostgreSQL close warning: {e}")

        # Weaviate 연결 종료 (이슈 #2 수정: 싱글톤 명시적 종료)
        try:
            from app.lib.weaviate_client import weaviate_client
            weaviate_client.close()
            logger.info("✅ Weaviate client closed")
        except Exception as e:
            logger.warning(f"⚠️ Weaviate close warning: {e}")

        # MongoDB 연결 종료 (이슈 #5 수정: 싱글톤 명시적 종료)
        try:
            from app.lib.mongodb_client import mongodb_client
            mongodb_client.close()
            logger.info("✅ MongoDB client closed")
        except Exception as e:
            logger.warning(f"⚠️ MongoDB close warning: {e}")

        # LangSmith 트레이스 flush
        if langsmith_enabled and LANGSMITH_AVAILABLE:
            try:
                logger.info("📊 Flushing LangSmith traces...")
                wait_for_all_tracers()
                logger.info("📊 LangSmith tracing shutdown completed")
            except Exception as e:
                logger.warning(f"⚠️ LangSmith shutdown error: {e}")

        logger.info("📡 Application shutdown completed")

    except Exception as e:
        logger.error(f"❌ Error during shutdown: {e}")


# FastAPI 앱 생성
app = FastAPI(
    title="OneRAG API",
    description="OneRAG 시스템 - API Key 인증 필요",
    version="2.0.0",
    lifespan=lifespan,
)

# Swagger UI에 API Key 인증 추가 (Authorize 버튼)
api_key_auth = get_api_key_auth()
custom_openapi = api_key_auth.get_custom_openapi_func(app)
app.openapi = custom_openapi  # type: ignore[method-assign]

# Rate limiting 설정
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 통합 에러 핸들러 설정
from fastapi.responses import JSONResponse

from app.lib.errors import (
    ErrorCode,
    RAGException,
    format_error_response,
    wrap_exception,
)


def _get_language_from_request(request: Request) -> str:
    """Accept-Language 헤더에서 언어 코드 추출.

    Args:
        request: FastAPI Request 객체

    Returns:
        언어 코드 ("ko" 또는 "en")
    """
    accept_language = request.headers.get("Accept-Language", "ko")

    # "en-US,en;q=0.9,ko;q=0.8" 형식 파싱
    if "en" in accept_language.lower().split(",")[0]:
        return "en"
    return "ko"


@app.exception_handler(RAGException)
async def rag_exception_handler(request: Request, exc: RAGException) -> JSONResponse:
    """RAGException 통합 핸들러 (양언어 지원).

    Features:
    - Accept-Language 헤더 기반 자동 언어 감지
    - 에러 코드별 현지화된 메시지
    - DEBUG 모드에서 기술적 세부사항 노출
    - 해결 방법 제공
    """
    # Accept-Language 헤더에서 언어 감지
    lang = _get_language_from_request(request)

    # 에러 코드 추출 (문자열 또는 Enum)
    error_code = exc.error_code if isinstance(exc.error_code, str) else exc.error_code.value

    # 양언어 에러 응답 생성
    error_response = format_error_response(
        error_code,
        lang=lang,
        include_solutions=True,
        **exc.context,
    )

    # 기본 응답 구조
    response_content: dict[str, Any] = {
        "error": True,
        "error_code": error_response["error_code"],
        "message": error_response["message"],
        "solutions": error_response.get("solutions", []),
    }

    # DEBUG 모드에서만 기술적 세부사항 추가
    debug_mode = os.getenv("DEBUG", "False").lower() == "true"
    if debug_mode:
        response_content["detail"] = str(exc)
        response_content["context"] = exc.context

    return JSONResponse(
        status_code=500,
        content=response_content,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """일반 예외 핸들러 (fallback, 양언어 지원)."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    # Accept-Language 헤더에서 언어 감지
    lang = _get_language_from_request(request)

    # 예외를 RAGException으로 래핑
    wrapped_error = wrap_exception(
        exc,
        default_code=ErrorCode.API_001,
        path=str(request.url),
    )

    # 양언어 응답 생성
    return JSONResponse(
        status_code=500,
        content=wrapped_error.to_dict(lang=lang, include_solutions=True),
    )


# 미들웨어 설정
# 배포 환경에서의 CORS 허용 도메인은 환경 변수 ALLOWED_ORIGINS(콤마 구분)로 확장 가능
default_allowed_origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:5000",
    "http://localhost:5173",
]
env_allowed_origins = os.getenv("ALLOWED_ORIGINS", "")
if env_allowed_origins:
    default_allowed_origins.extend(
        [origin.strip() for origin in env_allowed_origins.split(",") if origin.strip()]
    )

# ✅ H6 보안 패치: allow_methods를 명시적으로 지정 (와일드카드 제거)
app.add_middleware(
    CORSMiddleware,
    allow_origins=default_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Session-ID", "Accept-Language"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


# API Key 인증 미들웨어 추가
# ⚠️ 주의: 인증 미들웨어는 다른 미들웨어보다 먼저 실행되도록 마지막에 등록
@app.middleware("http")
async def api_key_auth_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """API Key 인증 미들웨어"""
    response = await api_key_auth.authenticate_request(request, call_next)
    return cast(Response, response)


# Rate Limiting Middleware 추가 (IP/Session 기반)
# ⚠️ rate_limiter 인스턴스는 위에서 전역으로 생성됨 (lifespan에서 cleanup task 관리)
from app.middleware.rate_limiter import RateLimitMiddleware

app.add_middleware(
    RateLimitMiddleware,
    rate_limiter=rate_limiter,
    excluded_paths=[
        "/health",
        "/api/health",
        "/api/chat",  # 🔧 채팅 API도 제외 (body 읽기로 인한 타임아웃 방지)
        "/api/chat/session",  # 세션 생성은 Rate Limit 제외 (body 읽기로 인한 14초 타임아웃 방지)
        "/api/chat/stream",  # 🔧 스트리밍 API도 제외
        "/docs",
        "/redoc",
        "/openapi.json",
        "/",
        "/api",
    ],
)

# Error Logging Middleware 추가 (모든 에러 자동 로깅)
# ⚠️ 주의: API 로직의 에러만 캡처 (인증/Rate Limit 에러는 제외)
from app.middleware.error_logger import ErrorLoggingMiddleware

app.add_middleware(ErrorLoggingMiddleware)

# 정적 파일 서빙 (있는 경우)
static_path = Path(__file__).parent.parent / "public"
if static_path.exists():
    app.mount("/dashboard", StaticFiles(directory=static_path), name="static")

# 라우터 등록
app.include_router(health.router)
app.include_router(chat.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(image_chat.router, prefix="/api")  # 이미지 채팅 API
app.include_router(admin.router)
app.include_router(prompts.router)
app.include_router(langsmith_logs.router)
app.include_router(ingest.router, prefix="/api")  # Phase 8: 데이터 적재 API
app.include_router(evaluations.router, prefix="/api/evaluations", tags=["Evaluations"])
app.include_router(monitoring.router, prefix="/api")
app.include_router(tools_router.router, prefix="/api", tags=["Tools"])
app.include_router(weaviate_admin_router.router, tags=["Weaviate Admin"])
app.include_router(admin_eval_router, prefix="/api", tags=["Admin Evaluation"])
app.include_router(websocket_router.router, tags=["WebSocket"])  # ✅ Task 4: WebSocket 채팅


@app.get("/")
async def root() -> RedirectResponse:
    """루트 엔드포인트 - FastAPI 스웨거 페이지로 리다이렉트"""
    return RedirectResponse(url="/docs")


@app.get("/api")
async def api_info() -> dict[str, Any]:
    """API 정보 엔드포인트"""
    # 모듈 상태 확인
    modules_status = {}
    if hasattr(rag_app, "modules") and rag_app.modules:
        for module_name, module in rag_app.modules.items():
            modules_status[module_name] = "활성화" if module else "비활성화"

    return {
        "name": "OneRAG API",
        "version": "2.0.0",
        "description": "OneRAG 시스템",
        "status": "운영 중",
        "modules": modules_status,
        "features": [
            "다중 LLM 지원 (GPT-5, Claude, Gemini)",
            "하이브리드 검색 (Dense + Sparse)",
            "LLM 기반 리랭킹",
            "세션 기반 대화 관리",
            "다양한 문서 형식 지원",
        ],
        "endpoints": {
            "건강 상태": "/health",
            "시스템 통계": "/stats",
            "대시보드": "/dashboard",
            "채팅 API": "/api/chat",
            "파일 업로드": "/api/upload",
            "문서 관리": "/api/upload/documents",
            "관리자": "/api/admin",
            "LangSmith 로그": "/api/langsmith/logs",
            "LangSmith 통계": "/api/langsmith/statistics",
            "평가 시스템": "/api/evaluations",
            "평가 통계": "/api/evaluations/stats/summary",
            "Tool Use": "/api/tools",
            "Tool 실행": "/api/tools/{tool_name}/execute",
            "배치 평가 API": "/api/admin/evaluate",
        },
        "usage": {
            "chat_example": {
                "url": "/api/chat",
                "method": "POST",
                "body": {
                    "message": "안녕하세요, 질문이 있어요.",
                    "session_id": "optional_session_id",
                },
            }
        },
    }


@app.middleware("http")
async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """요청 로깅 미들웨어"""
    start_time = asyncio.get_event_loop().time()

    response = await call_next(request)

    process_time = asyncio.get_event_loop().time() - start_time
    logger.info(
        f"{request.method} {request.url.path} - {response.status_code} - {process_time:.3f}s",
        extra={
            "method": request.method,
            "path": str(request.url.path),
            "status_code": response.status_code,
            "process_time": process_time,
            "client_ip": request.client.host if request.client else None,
        },
    )

    return response


def main() -> None:
    """메인 실행 함수"""
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info(f"🚀 Starting server on {host}:{port}")

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=os.getenv("DEBUG", "false").lower() == "true",
        reload_excludes=["logs/*", "*.log"],  # 로그 파일 변경 무시
        log_level="info",
    )


if __name__ == "__main__":
    main()
