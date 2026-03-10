"""
OneRAG 라이브 데모 서버

기존 main.py(80+ DI Provider)의 경량 버전입니다.
데모에 필요한 최소 컴포넌트만 초기화하여 512MB RAM 내에서 동작합니다.

초기화 대상:
1. GeminiEmbedder (API 기반 임베딩 — 로컬 모델 불필요)
2. ChromaDB 클라이언트 (인메모리)
3. GoogleLLMClient (답변 생성)
4. DemoSessionManager (세션 관리)
5. DemoPipeline (RAG 파이프라인)

실행 방법:
    uv run python demo_main.py
    # 또는
    uv run uvicorn demo_main:app --host 0.0.0.0 --port 8000
"""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import chromadb
from chromadb.config import Settings
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.api.demo.compat_router import cleanup_session_history, compat_router
from app.api.demo.demo_pipeline import DemoPipeline
from app.api.demo.demo_router import limiter, set_demo_services
from app.api.demo.demo_router import router as demo_router
from app.api.demo.sample_data import get_available_languages, load_sample_documents
from app.api.demo.session_manager import DemoSessionManager
from app.lib.llm_client import GoogleLLMClient
from app.lib.logger import get_logger
from app.modules.core.embedding.gemini_embedder import GeminiEmbedder

logger = get_logger(__name__)


# =============================================================================
# 환경 변수 안전 파싱
# =============================================================================


def _safe_int(env_name: str, default: int, min_val: int = 1) -> int:
    """환경 변수를 안전하게 int로 변환 (잘못된 값 → 기본값 + 경고)"""
    raw = os.getenv(env_name, str(default))
    try:
        value = int(raw)
        if value < min_val:
            logger.warning(
                f"환경 변수 {env_name}={value}가 최소값({min_val}) 미만 → "
                f"기본값({default}) 사용"
            )
            return default
        return value
    except ValueError:
        logger.warning(
            f"환경 변수 {env_name}='{raw}'가 정수가 아님 → "
            f"기본값({default}) 사용"
        )
        return default


# =============================================================================
# 환경 변수 기반 설정
# =============================================================================

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
DEMO_MAX_SESSIONS = _safe_int("DEMO_MAX_SESSIONS", 50)
DEMO_TTL_SECONDS = _safe_int("DEMO_TTL_SECONDS", 600, min_val=60)
DEMO_MAX_FILE_SIZE_MB = _safe_int("DEMO_MAX_FILE_SIZE_MB", 10)
DEMO_MAX_DOCS_PER_SESSION = _safe_int("DEMO_MAX_DOCS_PER_SESSION", 5)
DEMO_DAILY_API_LIMIT = _safe_int("DEMO_DAILY_API_LIMIT", 500, min_val=0)
DEMO_PORT = _safe_int("PORT", _safe_int("DEMO_PORT", 8000), min_val=1)
DEMO_HOST = os.getenv("DEMO_HOST", "0.0.0.0")
DEMO_SAMPLE_LANGUAGE = os.getenv("DEMO_SAMPLE_LANGUAGE", "ko")

# Gemini 모델 설정 — 무료 티어 내 최신 모델 사용
# 3.1 Flash-Lite: 2.5x 빠른 TTFT, 45% 출력 속도 향상, 무료 티어 동일
GEMINI_EMBEDDING_MODEL = os.getenv(
    "DEMO_EMBEDDING_MODEL", "models/gemini-embedding-001"
)
GEMINI_LLM_MODEL = os.getenv("DEMO_LLM_MODEL", "gemini-3.1-flash-lite-preview")

# =============================================================================
# 앱 생명주기
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """앱 시작/종료 시 리소스 관리"""
    logger.info("=" * 60)
    logger.info("OneRAG 라이브 데모 서버 시작")
    logger.info("=" * 60)

    # API 키 확인
    if not GOOGLE_API_KEY:
        logger.error(
            "GOOGLE_API_KEY가 설정되지 않았습니다. "
            "데모 서버가 시작되지만 AI 기능은 작동하지 않습니다."
        )

    # 1. ChromaDB 인메모리 클라이언트
    chroma_client = chromadb.Client(
        settings=Settings(anonymized_telemetry=False)
    )
    logger.info("ChromaDB 인메모리 클라이언트 초기화 완료")

    # 2. GeminiEmbedder
    embedder = GeminiEmbedder(
        google_api_key=GOOGLE_API_KEY,
        model_name=GEMINI_EMBEDDING_MODEL,
    )
    logger.info(f"GeminiEmbedder 초기화 완료: {GEMINI_EMBEDDING_MODEL}")

    # 3. GoogleLLMClient
    llm_client = GoogleLLMClient(config={
        "api_key": GOOGLE_API_KEY,
        "model": GEMINI_LLM_MODEL,
        "temperature": 0.3,
        "max_tokens": 2048,
        "timeout": 30,
    })
    logger.info(f"GoogleLLMClient 초기화 완료: {GEMINI_LLM_MODEL}")

    # 4. DemoSessionManager
    session_manager = DemoSessionManager(
        chroma_client=chroma_client,
        max_sessions=DEMO_MAX_SESSIONS,
        ttl_seconds=DEMO_TTL_SECONDS,
        max_docs_per_session=DEMO_MAX_DOCS_PER_SESSION,
        max_file_size_mb=DEMO_MAX_FILE_SIZE_MB,
        daily_api_limit=DEMO_DAILY_API_LIMIT,
        on_session_deleted=cleanup_session_history,
    )
    await session_manager.start_cleanup_loop()

    # 5. DemoPipeline
    pipeline = DemoPipeline(
        session_manager=session_manager,
        embedder=embedder,
        chroma_client=chroma_client,
        llm_client=llm_client,
    )

    # 6. 라우터에 서비스 주입
    set_demo_services(session_manager, pipeline)

    # 7. 샘플 데이터 사전 로드
    await _preload_sample_data(session_manager, pipeline)

    logger.info("-" * 60)
    logger.info("데모 서버 준비 완료")
    logger.info(f"  최대 세션: {DEMO_MAX_SESSIONS}")
    logger.info(f"  세션 TTL: {DEMO_TTL_SECONDS}초")
    logger.info(f"  최대 파일 크기: {DEMO_MAX_FILE_SIZE_MB}MB")
    logger.info(f"  세션당 최대 문서: {DEMO_MAX_DOCS_PER_SESSION}")
    logger.info(f"  API 문서: http://{DEMO_HOST}:{DEMO_PORT}/docs")
    logger.info("-" * 60)

    yield

    # 종료 정리
    await session_manager.stop_cleanup_loop()
    logger.info("OneRAG 데모 서버 종료")


async def _preload_sample_data(
    manager: DemoSessionManager, pipeline: DemoPipeline
) -> None:
    """샘플 데이터 세션 사전 생성"""
    if not GOOGLE_API_KEY:
        logger.warning("API 키 미설정으로 샘플 데이터 사전 로드를 건너뜁니다.")
        return

    languages = get_available_languages()
    lang = DEMO_SAMPLE_LANGUAGE if DEMO_SAMPLE_LANGUAGE in languages else "ko"
    documents = load_sample_documents(lang)

    if not documents:
        logger.warning("샘플 데이터가 없습니다.")
        return

    try:
        session = await manager.create_session(is_sample=True)
        count = await pipeline.ingest_sample_data(session.session_id, documents)
        logger.info(
            f"샘플 데이터 세션 생성 완료: {session.session_id} "
            f"({count}개 문서, 언어: {lang})"
        )
    except Exception as e:
        logger.error(f"샘플 데이터 로드 실패: {e}")


# =============================================================================
# FastAPI 앱
# =============================================================================

app = FastAPI(
    title="OneRAG Live Demo",
    description=(
        "OneRAG 라이브 데모 API. "
        "문서를 업로드하고 RAG 기반 질문 답변을 체험할 수 있습니다."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Rate Limiter 등록
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Rate Limit 초과 시 429 응답"""
    from app.lib.errors.codes import ErrorCode

    return Response(
        status_code=429,
        content=f'{{"detail": "{ErrorCode.DEMO_007.value}"}}',
        media_type="application/json",
    )


# CORS 설정 (프론트엔드 연동)
_demo_allowed_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
]
_env_origins = os.getenv("DEMO_ALLOWED_ORIGINS", "")
if _env_origins:
    _demo_allowed_origins.extend(
        [o.strip() for o in _env_origins.split(",") if o.strip()]
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_demo_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept-Language"],
)

# 라우터 등록
app.include_router(demo_router, prefix="/api/demo")
app.include_router(compat_router)  # 프론트엔드 호환 라우터 (/api/chat 등)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """헬스 체크"""
    return {"status": "healthy", "service": "onerag-demo"}


@app.get("/")
async def root() -> dict[str, str]:
    """루트 경로 — 데모 안내"""
    return {
        "service": "OneRAG Live Demo",
        "docs": "/docs",
        "demo_api": "/api/demo",
    }


# =============================================================================
# 직접 실행
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "demo_main:app",
        host=DEMO_HOST,
        port=DEMO_PORT,
        reload=False,
        log_level="info",
    )
