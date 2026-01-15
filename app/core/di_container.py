"""
DI Container - Dependency Injection Container for RAG Chatbot

TASK-H3: main.py 660줄 → 250줄 리팩토링
dependency-injector 라이브러리 기반 DI Container

Provider 타입:
- Configuration: YAML 로딩 + 환경 변수 병합
- Singleton: 공유 상태 (config, llm_factory 등)
- Coroutine: AsyncIO 초기화 필요 (session, retrieval 등)
- Factory: 요청마다 새 인스턴스 (RAGPipeline, ChatService 등)
"""

import asyncio
import os
from typing import Any, TypeVar

from dependency_injector import containers, providers

# Services
from app.api.services.chat_service import ChatService
from app.api.services.rag_pipeline import RAGPipeline
from app.batch.notion_client import NotionAPIClient

# SQL Search 모듈 (Phase 3: 메타데이터 SQL 검색)
from app.infrastructure.persistence.connection import DatabaseManager
from app.infrastructure.persistence.evaluation_manager import EvaluationDataManager
from app.infrastructure.persistence.prompt_repository import PromptRepository
from app.infrastructure.storage.metadata.postgres_store import PostgresMetadataStore

# Phase 8: Storage & Ingestion (Factory 패턴 적용)
from app.infrastructure.storage.vector.factory import VectorStoreFactory

# Core modules
from app.lib.auth import get_api_key_auth
from app.lib.circuit_breaker import CircuitBreakerFactory
from app.lib.config_validator import get_env_int, get_env_url

# from app.lib.ip_geolocation import IPGeolocationModule  # 비활성화: 세션 생성 타임아웃 원인
from app.lib.llm_client import LLMClientFactory, get_llm_factory, initialize_llm_factory
from app.lib.logger import get_logger
from app.lib.metrics import CostTracker, PerformanceMetrics
from app.lib.weaviate_client import WeaviateClient

# Phase 5: Agent 모듈 (Agentic RAG Orchestrator)
from app.modules.core.agent import AgentFactory
from app.modules.core.documents.document_processing import DocumentProcessor

# Phase 9: 평가 시스템 모듈 (Evaluation System)
from app.modules.core.evaluation import EvaluatorFactory
from app.modules.core.generation.generator import GenerationModule
from app.modules.core.generation.prompt_manager import PromptManager

# Phase 7: GraphRAG 모듈 (지식 그래프 기반 검색)
from app.modules.core.graph import (
    GraphRAGFactory,
    KnowledgeGraphBuilder,
    LLMEntityExtractor,
    LLMRelationExtractor,
)

# Phase 4: MCP 모듈 (Model Context Protocol)
from app.modules.core.mcp import MCPServer, MCPToolFactory

# Phase 2: 개인정보 보호 모듈 (통합 PII 처리)
from app.modules.core.privacy import (
    PIIProcessor,
    PrivacyMasker,
    WhitelistManager,
)

# Phase 3: PII Review System (문서 전처리용)
from app.modules.core.privacy.review import (
    HybridPIIDetector,
    PIIAuditLogger,
    PIIPolicyEngine,
    PIIReviewProcessor,
)

# Phase 2: BM25 고도화 모듈 (동의어, 불용어, 사용자 사전)
from app.modules.core.retrieval.bm25 import StopwordFilter, SynonymManager, UserDictionary
from app.modules.core.retrieval.cache.memory_cache import MemoryCacheManager

# Phase 6: 시맨틱 캐시 (쿼리 임베딩 유사도 기반)
from app.modules.core.retrieval.cache.semantic_cache import (
    InMemorySemanticCache,
    SemanticCacheConfig,
)
from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator
from app.modules.core.retrieval.query_expansion.gpt5_engine import GPT5QueryExpansionEngine

# Phase 6: 고급 리랭킹 모듈 (ColBERT, RerankerChain)
from app.modules.core.retrieval.rerankers.colbert_reranker import (
    ColBERTRerankerConfig,
    JinaColBERTReranker,
)
from app.modules.core.retrieval.rerankers.gemini_reranker import GeminiFlashReranker
from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker
from app.modules.core.retrieval.rerankers.reranker_chain import (
    RerankerChain,
    RerankerChainConfig,
)

# Retriever Factory (다중 벡터 DB 지원 - Factory 패턴 적용)
from app.modules.core.retrieval.retrievers.factory import RetrieverFactory
from app.modules.core.routing.complexity_calculator import ComplexityCalculator
from app.modules.core.routing.llm_query_router import LLMQueryRouter
from app.modules.core.self_rag.evaluator import LLMQualityEvaluator
from app.modules.core.self_rag.orchestrator import SelfRAGOrchestrator
from app.modules.core.session.facade import EnhancedSessionModule
from app.modules.core.session.services.memory_service import MemoryService
from app.modules.core.sql_search import SQLSearchService
from app.modules.core.tools.external_api_caller import ExternalAPICaller
from app.modules.core.tools.tool_executor import ToolExecutor
from app.modules.core.tools.tool_loader import ToolLoader
from app.modules.ingestion.factory import IngestionConnectorFactory
from app.modules.ingestion.service import IngestionService

logger = get_logger(__name__)

# TypeVar for generic type parameters
T = TypeVar("T")


# ========================================
# Helper Functions
# ========================================


def initialize_llm_factory_wrapper(config: dict) -> LLMClientFactory:
    """
    LLM Factory 초기화 wrapper

    dependency-injector의 Singleton provider에서 사용하기 위해
    전역 상태 초기화를 캡슐화.

    Args:
        config: 설정 딕셔너리

    Returns:
        LLMClientFactory: LLM 클라이언트 팩토리 인스턴스
    """
    initialize_llm_factory(config)
    return get_llm_factory()


def extract_topic_default(message: str) -> str:
    """
    기본 토픽 추출 함수
    """
    if isinstance(message, list):
        message = " ".join(str(item) for item in message)
    elif not isinstance(message, str):
        message = str(message)

    if not message:
        return "general"

    # 범용 키워드 매핑 (검색, 도움말, 일반 대화 등)
    keywords = {
        "search": ["검색", "찾기", "찾아", "조회", "정보", "어디", "알려"],
        "help": ["도움", "어떻게", "방법", "안내", "사용법", "매뉴얼"],
        "greeting": ["안녕", "반가워", "하이", "헬로"],
        "thanks": ["고마워", "감사", "땡큐"],
    }

    try:
        lower_message = message.lower()
        for topic, words in keywords.items():
            if any(word in lower_message for word in words):
                return topic
        return "general"
    except Exception:
        return "general"


def _get_provider_config(
    config: dict, provider_name: str, key: str, default: T | None = None
) -> T | None:
    """
    Provider별 설정값 로딩 (defaults 활용)

    우선순위:
    1. providers.{provider_name}.{key} (provider별 설정)
    2. reranking.defaults.{key} (공통 기본값)
    3. default 인자 (함수 기본값)

    Args:
        config: 전체 설정 딕셔너리
        provider_name: provider 이름 (예: "gemini_flash", "jina")
        key: 설정 키 (예: "max_documents", "timeout")
        default: 최종 fallback 기본값

    Returns:
        설정값 또는 None

    Raises:
        TypeError: 설정값 타입이 예상과 다를 경우
    """
    reranking = config.get("reranking", {})

    if not isinstance(reranking, dict):
        raise TypeError(f"config.reranking must be dict, got {type(reranking).__name__}")

    providers = reranking.get("providers", {})
    if not isinstance(providers, dict):
        raise TypeError(f"reranking.providers must be dict, got {type(providers).__name__}")

    provider_config = providers.get(provider_name, {})
    if not isinstance(provider_config, dict):
        raise TypeError(
            f"provider config for '{provider_name}' must be dict, got {type(provider_config).__name__}"
        )

    defaults = reranking.get("defaults", {})
    if not isinstance(defaults, dict):
        raise TypeError(f"reranking.defaults must be dict, got {type(defaults).__name__}")

    # Provider 설정 > Defaults > 함수 기본값
    result = provider_config.get(key, defaults.get(key, default))

    # 타입 안전성 검증: default가 있으면 result 타입이 일치해야 함
    if default is not None and result is not None:
        if not isinstance(result, type(default)):
            raise TypeError(
                f"Config value type mismatch for '{provider_name}.{key}': "
                f"expected {type(default).__name__}, got {type(result).__name__}"
            )

    return result


async def create_reranker_instance(
    config: dict, llm_factory: LLMClientFactory | None = None
) -> GeminiFlashReranker | JinaReranker | None:
    """
    Reranker 인스턴스 생성 헬퍼 함수

    main.py의 Phase 5 로직을 재현:
    1. Gemini Flash Reranker 우선
    2. 실패 시 Jina Reranker fallback
    3. 둘 다 없으면 None

    Args:
        config: 설정 딕셔너리
        llm_factory: LLM Factory (optional, 향후 확장용)

    Returns:
        Reranker 인스턴스 또는 None

    v3.1.0 개선사항:
    - YAML defaults 활용으로 중복 제거
    - Provider별 설정 우선순위 명확화
    """
    reranking_config = config.get("reranking", {})
    default_provider = reranking_config.get("default_provider", "gemini_flash")

    # DEBUG: Reranker 초기화 디버깅
    google_api_key_set = "SET" if os.getenv("GOOGLE_API_KEY") else "NOT SET"
    logger.info(
        "Reranker 초기화 디버그",
        extra={"provider": default_provider, "google_api_key_set": google_api_key_set}
    )

    # Gemini Flash Reranker 시도
    if default_provider == "gemini_flash":
        google_api_key = os.getenv("GOOGLE_API_KEY")
        if google_api_key:
            try:
                reranker = GeminiFlashReranker(
                    api_key=google_api_key,
                    max_documents=_get_provider_config(config, "gemini_flash", "max_documents", 10)
                    or 10,
                    timeout=_get_provider_config(config, "gemini_flash", "timeout", 10) or 10,
                )
                logger.info("GeminiFlashReranker 초기화 성공", extra={"provider": "gemini_flash"})
                return reranker
            except Exception as e:
                logger.warning(
                    "GeminiFlashReranker 초기화 실패",
                    extra={"error": str(e), "fallback": "jina"},
                    exc_info=True
                )

    # Jina Reranker fallback
    jina_api_key = os.getenv("JINA_API_KEY")
    if jina_api_key:
        try:
            reranker = JinaReranker(  # type: ignore[assignment]
                api_key=jina_api_key,
                model=_get_provider_config(
                    config, "jina", "model", "jina-reranker-v2-base-multilingual"
                )
                or "jina-reranker-v2-base-multilingual",
            )
            logger.info("JinaReranker 초기화 성공", extra={"provider": "jina"})
            return reranker
        except Exception as e:
            logger.warning("JinaReranker 초기화 실패", extra={"error": str(e)}, exc_info=True)

    logger.warning("Reranker API 키 없음", extra={"status": "proceeding_without_reranker"})
    return None


async def create_cache_instance(config: dict) -> MemoryCacheManager | None:
    """
    Cache 인스턴스 생성 헬퍼 함수

    환경변수 REDIS_URL이 설정되어 있으면 RedisCacheManager,
    없으면 MemoryCacheManager를 반환합니다.

    Args:
        config: 설정 딕셔너리

    Returns:
        MemoryCacheManager 또는 RedisCacheManager 인스턴스 또는 None
        (RedisCacheManager는 MemoryCacheManager를 상속하므로 타입 호환)

    Redis 장애 시 Graceful Fallback:
    - RedisCacheManager는 내부적으로 로컬 캐시를 폴백으로 사용
    - Redis 연결 실패 시 자동으로 MemoryCacheManager로 전환
    """
    cache_config = config.get("cache", {})
    if not cache_config.get("enabled", True):
        logger.info("Cache 비활성화", extra={"config_key": "cache.enabled", "value": False})
        return None

    # Redis URL 환경변수 확인
    redis_url = os.getenv("REDIS_URL")

    if redis_url:
        # Redis 분산 캐시 사용 (멀티 인스턴스 환경)
        try:
            from redis.asyncio import Redis

            from app.modules.core.retrieval.cache.redis_cache import RedisCacheManager

            redis_client = Redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=False,  # bytes로 받아서 직접 디코딩
                socket_connect_timeout=5,
                socket_timeout=3,
                max_connections=10,  # Connection Pool 크기
            )

            cache = RedisCacheManager(
                redis_client=redis_client,
                key_prefix=cache_config.get("key_prefix", "rag:cache:"),
                default_ttl=cache_config.get("default_ttl", 3600),
                enable_stats=cache_config.get("enable_stats", True),
                enable_fallback=cache_config.get("enable_fallback", True),
                operation_timeout=cache_config.get("operation_timeout", 2.0),
            )

            # Health Check (연결 확인)
            if await cache.health_check():
                logger.info(
                    "RedisCacheManager 초기화 성공",
                    extra={"cache_type": "distributed", "redis_url": redis_url}
                )
                return cache  # type: ignore[return-value]
            else:
                logger.warning(
                    "Redis 헬스체크 실패",
                    extra={"fallback": "MemoryCacheManager"}
                )
                # Redis 연결 실패 시 메모리 캐시로 폴백
                await cache.close()

        except ImportError:
            logger.warning(
                "Redis 패키지 미설치",
                extra={"fallback": "MemoryCacheManager", "required_package": "redis"}
            )
        except Exception as e:
            logger.warning(
                "Redis Cache 초기화 실패",
                extra={"error": str(e), "fallback": "MemoryCacheManager"},
                exc_info=True
            )

    # 인메모리 캐시 사용 (단일 인스턴스 또는 Redis 실패 시)
    try:
        cache = MemoryCacheManager(  # type: ignore[assignment]
            maxsize=cache_config.get("maxsize", 100),
            default_ttl=cache_config.get("default_ttl", 3600),
        )
        logger.info(
            "MemoryCacheManager 초기화 성공",
            extra={
                "cache_type": "in_memory",
                "maxsize": cache_config.get("maxsize", 100),
                "ttl": cache_config.get("default_ttl", 3600)
            }
        )
        return cache  # type: ignore[return-value]
    except Exception as e:
        logger.warning("Cache 초기화 실패", extra={"error": str(e)}, exc_info=True)
        return None


async def create_colbert_reranker_instance(
    config: dict,
) -> JinaColBERTReranker | None:
    """
    ColBERT Reranker 인스턴스 생성 헬퍼 함수

    Jina ColBERT v2 API를 사용한 고품질 리랭킹.
    토큰 수준 Late Interaction으로 더 정교한 관련성 평가.

    Args:
        config: 설정 딕셔너리

    Returns:
        JinaColBERTReranker 인스턴스 또는 None

    Phase 6 추가:
    - ColBERT 리랭커 (Jina ColBERT v2 API)
    - 설정 기반 활성화/비활성화
    """
    colbert_config = config.get("reranking", {}).get("colbert", {})

    # 비활성화 체크
    if not colbert_config.get("enabled", False):
        logger.info(
            "ColBERT Reranker 비활성화",
            extra={"config_key": "reranking.colbert.enabled", "value": False}
        )
        return None

    # API 키 확인
    jina_api_key = os.getenv("JINA_API_KEY")
    if not jina_api_key:
        logger.warning(
            "JINA_API_KEY 미설정",
            extra={"status": "ColBERT_Reranker_disabled", "env_var": "JINA_API_KEY"}
        )
        return None

    try:
        reranker_config = ColBERTRerankerConfig(
            enabled=True,
            api_key=jina_api_key,
            model=colbert_config.get("model", "jina-colbert-v2"),
            endpoint=colbert_config.get("endpoint", "https://api.jina.ai/v1/rerank"),
            timeout=colbert_config.get("timeout", 10),
            max_documents=colbert_config.get("max_documents", 20),
        )
        reranker = JinaColBERTReranker(config=reranker_config)
        logger.info(
            "JinaColBERTReranker 초기화 성공",
            extra={
                "model": colbert_config.get("model", "jina-colbert-v2"),
                "max_documents": colbert_config.get("max_documents", 20)
            }
        )
        return reranker
    except Exception as e:
        logger.warning(
            "ColBERT Reranker 초기화 실패",
            extra={"error": str(e)},
            exc_info=True
        )
        return None


async def create_reranker_chain_instance(
    config: dict,
    colbert_reranker: JinaColBERTReranker | None = None,
    llm_reranker: GeminiFlashReranker | JinaReranker | None = None,
) -> RerankerChain | None:
    """
    RerankerChain 인스턴스 생성 헬퍼 함수

    다중 리랭커를 순차적으로 실행하는 체인.
    Pipeline: RRF → ColBERT → LLM Reranker (각각 독립적으로 토글 가능)

    Args:
        config: 설정 딕셔너리
        colbert_reranker: ColBERT 리랭커 (선택)
        llm_reranker: LLM 리랭커 (Gemini 또는 Jina)

    Returns:
        RerankerChain 인스턴스 또는 None

    Phase 6 추가:
    - 다중 리랭커 체인 (순차 실행)
    - 각 리랭커 독립적 활성화/비활성화
    """
    chain_config = config.get("reranking", {}).get("chain", {})

    # 비활성화 체크
    if not chain_config.get("enabled", False):
        logger.info(
            "RerankerChain 비활성화",
            extra={"config_key": "reranking.chain.enabled", "value": False}
        )
        return None

    # 활성화된 리랭커 수집
    rerankers = []
    if colbert_reranker:
        rerankers.append(colbert_reranker)
    if llm_reranker:
        rerankers.append(llm_reranker)

    if not rerankers:
        logger.warning(
            "RerankerChain 생성 불가",
            extra={"reason": "no_rerankers_available"}
        )
        return None

    try:
        chain = RerankerChain(
            rerankers=rerankers,
            config=RerankerChainConfig(
                enabled=True,
                continue_on_error=chain_config.get("continue_on_error", True),
                log_intermediate_results=chain_config.get("log_intermediate_results", False),
            ),
        )
        reranker_names = [r.name for r in rerankers]
        logger.info(
            "RerankerChain 초기화 성공",
            extra={"rerankers": reranker_names, "count": len(rerankers)}
        )
        return chain
    except Exception as e:
        logger.warning(
            "RerankerChain 초기화 실패",
            extra={"error": str(e)},
            exc_info=True
        )
        return None


async def create_mcp_server_instance(
    config: dict,
    retriever=None,
    graph_store=None,
) -> MCPServer | None:
    """
    MCP 서버 인스턴스 생성 헬퍼 함수

    설정 기반 MCP 서버 생성 및 retriever, graph_store 주입.
    기존 EmbedderFactory, RerankerFactory 패턴과 동일.

    Args:
        config: 설정 딕셔너리
        retriever: WeaviateRetriever 인스턴스 (도구에서 사용)
        graph_store: GraphStore 인스턴스 (GraphRAG 도구에서 사용, Phase 7)

    Returns:
        MCPServer 인스턴스 또는 None (비활성화 시)

    Phase 4 추가:
    - MCP (Model Context Protocol) 지원
    - 설정 기반 도구 활성화/비활성화

    Phase 7 추가:
    - GraphRAG graph_store 주입 (search_graph, get_neighbors 도구용)
    """
    mcp_config = config.get("mcp", {})

    # 비활성화 체크
    if not mcp_config.get("enabled", False):
        logger.info(
            "MCP Server 비활성화",
            extra={"config_key": "mcp.enabled", "value": False}
        )
        return None

    try:
        # global_config 구성 (도구에서 retriever, graph_store 접근용)
        global_config = {
            **config,
            "retriever": retriever,
            "graph_store": graph_store,  # Phase 7: GraphRAG 저장소 추가
        }

        # MCPToolFactory를 통해 서버 생성
        server = MCPToolFactory.create(config)

        # global_config 업데이트 (retriever, graph_store 주입)
        server._global_config = global_config

        logger.info(
            "MCPServer 초기화 성공",
            extra={"server_name": server.server_name}
        )
        return server

    except ValueError as e:
        # MCP 비활성화 또는 설정 오류
        logger.info(
            "MCP Server 생성 불가",
            extra={"reason": str(e)}
        )
        return None
    except Exception as e:
        logger.warning(
            "MCP Server 초기화 실패",
            extra={"error": str(e)},
            exc_info=True
        )
        return None


async def create_evaluator_instance(
    config: dict,
    llm_factory: LLMClientFactory | None = None,
):
    """
    Evaluator 인스턴스 생성 헬퍼 함수

    설정 기반 평가기 생성 (EvaluatorFactory 사용).
    기존 create_reranker_instance, create_cache_instance 패턴과 동일.

    Args:
        config: 설정 딕셔너리
        llm_factory: LLM Factory (internal 평가기에 필요)

    Returns:
        IEvaluator 인스턴스 또는 None (비활성화 시)

    Phase 9 추가:
    - 평가 시스템 지원
    - 설정 기반 프로바이더 선택 (internal, ragas)
    """
    eval_config = config.get("evaluation", {})

    # 비활성화 체크
    if not eval_config.get("enabled", False):
        logger.info(
            "Evaluator 비활성화",
            extra={"config_key": "evaluation.enabled", "value": False}
        )
        return None

    try:
        # LLM 클라이언트 생성 (internal 평가기용)
        llm_client = None
        if llm_factory is not None:
            # LLM Factory에서 generate 메서드를 가진 래퍼 생성
            llm_client = _create_evaluator_llm_client(llm_factory, eval_config)

        evaluator = EvaluatorFactory.create(config, llm_client=llm_client)

        if evaluator:
            logger.info(
                "Evaluator 초기화 성공",
                extra={"evaluator_name": evaluator.name}
            )
        return evaluator

    except Exception as e:
        logger.warning(
            "Evaluator 초기화 실패",
            extra={"error": str(e)},
            exc_info=True
        )
        return None


def _create_evaluator_llm_client(
    llm_factory: LLMClientFactory, eval_config: dict
):
    """
    평가기용 LLM 클라이언트 래퍼 생성

    Args:
        llm_factory: LLM Factory
        eval_config: 평가 설정

    Returns:
        generate 메서드를 가진 LLM 클라이언트 래퍼
    """
    internal_config = eval_config.get("internal", {})
    model = internal_config.get("model", "google/gemini-2.5-flash-lite")

    class EvaluatorLLMClient:
        """평가기용 LLM 클라이언트 래퍼"""

        def __init__(self, factory: LLMClientFactory, model_name: str):
            self._factory = factory
            self._model = model_name

        async def generate(self, prompt: str) -> str:
            """프롬프트를 LLM에 전송하고 응답 반환"""
            client = self._factory.get_client(provider="openrouter")
            response = await client.generate(
                prompt=prompt,
                model=self._model,
            )
            return response

    return EvaluatorLLMClient(llm_factory, model)


async def create_graph_store_instance(config: dict, embedder: Any = None):
    """
    GraphRAG 저장소 인스턴스 생성 헬퍼 함수

    설정 기반 그래프 저장소 생성 (GraphRAGFactory 사용).
    v3.3.0: 벡터 검색을 위한 embedder 주입 지원.
    """
    graph_rag_config = config.get("graph_rag", {})

    # 비활성화 체크
    if not graph_rag_config.get("enabled", False):
        logger.info(
            "GraphRAG 비활성화",
            extra={"config_key": "graph_rag.enabled", "value": False}
        )
        return None

    try:
        # GraphRAGFactory를 통해 저장소 생성
        store = GraphRAGFactory.create(config)

        if store:
            # 벡터 검색을 위한 임베더 주입 (구현체에 set_embedder가 있는 경우)
            if embedder and hasattr(store, "set_embedder"):
                store.set_embedder(embedder)
                logger.info(
                    "GraphStore 벡터 검색 활성화",
                    extra={"store_type": store.__class__.__name__}
                )

            logger.info(
                "GraphStore 초기화 성공",
                extra={"store_type": store.__class__.__name__}
            )
        return store

    except Exception as e:
        logger.warning(
            "GraphStore 초기화 실패",
            extra={"error": str(e)},
            exc_info=True
        )
        return None


async def create_entity_extractor_instance(
    config: dict,
    llm_factory: LLMClientFactory | None = None,
) -> LLMEntityExtractor | None:
    """
    LLM 엔티티 추출기 인스턴스 생성 헬퍼 함수

    텍스트에서 엔티티(인물, 회사, 장소 등)를 LLM으로 추출.
    IEntityExtractor 프로토콜 구현체.

    Args:
        config: 설정 딕셔너리
        llm_factory: LLM Factory (LLM 클라이언트 생성용)

    Returns:
        LLMEntityExtractor 인스턴스 또는 None (비활성화 시)

    Phase 7 추가:
    - LLM 기반 엔티티 추출 지원
    - 설정 기반 모델 선택 (Gemini, GPT 등)
    """
    graph_rag_config = config.get("graph_rag", {})

    # GraphRAG 비활성화 체크
    if not graph_rag_config.get("enabled", False):
        logger.info(
            "LLMEntityExtractor 비활성화",
            extra={"reason": "GraphRAG_disabled"}
        )
        return None

    if llm_factory is None:
        logger.warning(
            "LLMEntityExtractor 비활성화",
            extra={"reason": "LLM_Factory_not_provided"}
        )
        return None

    try:
        # 추출 설정 로드
        extraction_config = graph_rag_config.get("extraction", {})
        llm_config = extraction_config.get("llm", {})

        # LLM 클라이언트 생성 (generate 메서드를 가진 간단한 래퍼)
        model = llm_config.get("model", "google/gemini-2.5-flash-lite")
        llm_client = _create_graph_llm_client(llm_factory, model)

        extractor = LLMEntityExtractor(
            llm_client=llm_client,
            config={
                "max_entities": llm_config.get("max_entities_per_chunk", 20),
                "model": model,
            },
        )
        logger.info(
            "LLMEntityExtractor 초기화 성공",
            extra={
                "model": model,
                "max_entities": llm_config.get("max_entities_per_chunk", 20)
            }
        )
        return extractor

    except Exception as e:
        logger.warning(
            "LLMEntityExtractor 초기화 실패",
            extra={"error": str(e)},
            exc_info=True
        )
        return None


async def create_relation_extractor_instance(
    config: dict,
    llm_factory: LLMClientFactory | None = None,
) -> LLMRelationExtractor | None:
    """
    LLM 관계 추출기 인스턴스 생성 헬퍼 함수

    엔티티 간 관계(파트너십, 위치 등)를 LLM으로 추출.
    IRelationExtractor 프로토콜 구현체.

    Args:
        config: 설정 딕셔너리
        llm_factory: LLM Factory (LLM 클라이언트 생성용)

    Returns:
        LLMRelationExtractor 인스턴스 또는 None (비활성화 시)

    Phase 7 추가:
    - LLM 기반 관계 추출 지원
    - 설정 기반 모델 선택 (Gemini, GPT 등)
    """
    graph_rag_config = config.get("graph_rag", {})

    # GraphRAG 비활성화 체크
    if not graph_rag_config.get("enabled", False):
        logger.info(
            "LLMRelationExtractor 비활성화",
            extra={"reason": "GraphRAG_disabled"}
        )
        return None

    if llm_factory is None:
        logger.warning(
            "LLMRelationExtractor 비활성화",
            extra={"reason": "LLM_Factory_not_provided"}
        )
        return None

    try:
        # 추출 설정 로드
        extraction_config = graph_rag_config.get("extraction", {})
        llm_config = extraction_config.get("llm", {})

        # LLM 클라이언트 생성
        model = llm_config.get("model", "google/gemini-2.5-flash-lite")
        llm_client = _create_graph_llm_client(llm_factory, model)

        extractor = LLMRelationExtractor(
            llm_client=llm_client,
            config={
                "max_relations": llm_config.get("max_relations_per_chunk", 30),
                "model": model,
            },
        )
        logger.info(
            "LLMRelationExtractor 초기화 성공",
            extra={
                "model": model,
                "max_relations": llm_config.get("max_relations_per_chunk", 30)
            }
        )
        return extractor

    except Exception as e:
        logger.warning(
            "LLMRelationExtractor 초기화 실패",
            extra={"error": str(e)},
            exc_info=True
        )
        return None


async def create_knowledge_graph_builder_instance(
    config: dict,
    graph_store=None,
    entity_extractor=None,
    relation_extractor=None,
) -> KnowledgeGraphBuilder | None:
    """
    지식 그래프 빌더 인스턴스 생성 헬퍼 함수

    엔티티 추출 → 관계 추출 → 그래프 저장 파이프라인을 실행.
    문서 청킹 후 그래프 구축에 사용.

    Args:
        config: 설정 딕셔너리
        graph_store: 그래프 저장소 인스턴스
        entity_extractor: 엔티티 추출기 인스턴스
        relation_extractor: 관계 추출기 인스턴스

    Returns:
        KnowledgeGraphBuilder 인스턴스 또는 None (비활성화 시)

    Phase 7 추가:
    - 지식 그래프 빌드 파이프라인
    - 문서 배치 처리 지원
    """
    graph_rag_config = config.get("graph_rag", {})

    # GraphRAG 비활성화 체크
    if not graph_rag_config.get("enabled", False):
        logger.info(
            "KnowledgeGraphBuilder 비활성화",
            extra={"reason": "GraphRAG_disabled"}
        )
        return None

    # 의존성 체크
    if graph_store is None:
        logger.warning(
            "KnowledgeGraphBuilder 비활성화",
            extra={"reason": "GraphStore_not_provided"}
        )
        return None

    if entity_extractor is None or relation_extractor is None:
        logger.warning(
            "KnowledgeGraphBuilder 비활성화",
            extra={"reason": "Extractors_not_provided"}
        )
        return None

    try:
        builder = KnowledgeGraphBuilder(
            graph_store=graph_store,
            entity_extractor=entity_extractor,
            relation_extractor=relation_extractor,
        )
        logger.info("KnowledgeGraphBuilder 초기화 성공")
        return builder

    except Exception as e:
        logger.warning(
            "KnowledgeGraphBuilder 초기화 실패",
            extra={"error": str(e)},
            exc_info=True
        )
        return None


def _create_graph_llm_client(llm_factory: LLMClientFactory, model: str):
    """
    GraphRAG용 LLM 클라이언트 래퍼 생성

    LLMEntityExtractor와 LLMRelationExtractor에서 사용할
    간단한 generate(prompt) -> str 인터페이스를 제공.

    Args:
        llm_factory: LLM Factory 인스턴스
        model: 사용할 모델 ID

    Returns:
        generate 메서드를 가진 래퍼 객체
    """

    class GraphLLMClient:
        """
        GraphRAG 추출기용 LLM 클라이언트 래퍼

        LLMClientFactory를 사용하여 LLM 호출을 수행.
        덕 타이핑: async generate(prompt: str) -> str 메서드 제공.
        """

        def __init__(self, factory: LLMClientFactory, model_id: str):
            self._factory = factory
            self._model_id = model_id

        async def generate(self, prompt: str) -> str:
            """
            LLM 생성 호출

            Args:
                prompt: 프롬프트 텍스트

            Returns:
                LLM 응답 텍스트
            """
            # LLMClientFactory를 통해 generate 호출
            # 팩토리 인터페이스에 맞게 조정
            client = self._factory.get_client()
            response = await client.generate(
                prompt=prompt,
                model=self._model_id,
                max_tokens=2000,
                temperature=0.1,  # 정확한 추출을 위해 낮은 온도
            )
            return response

    return GraphLLMClient(llm_factory, model)


async def create_semantic_cache_instance(
    config: dict,
    embedder=None,
) -> InMemorySemanticCache | None:
    """
    Semantic Cache 인스턴스 생성 헬퍼 함수

    쿼리 임베딩 유사도 기반 시맨틱 캐시.
    유사한 쿼리에 대해 캐시된 결과를 반환하여 성능 향상.

    Args:
        config: 설정 딕셔너리
        embedder: 임베딩 함수 (DocumentProcessor.embedder 사용)

    Returns:
        InMemorySemanticCache 인스턴스 또는 None

    Phase 6 추가:
    - 시맨틱 캐시 (코사인 유사도 기반)
    - 보수적 임계값으로 false positive 최소화
    """
    semantic_cache_config = config.get("cache", {}).get("semantic", {})

    # 비활성화 체크
    if not semantic_cache_config.get("enabled", False):
        logger.info(
            "Semantic Cache 비활성화",
            extra={"config_key": "cache.semantic.enabled", "value": False}
        )
        return None

    if embedder is None:
        logger.warning(
            "Semantic Cache 비활성화",
            extra={"reason": "Embedder_not_provided"}
        )
        return None

    try:
        cache_config = SemanticCacheConfig(
            enabled=True,
            similarity_threshold=semantic_cache_config.get("similarity_threshold", 0.95),
            max_entries=semantic_cache_config.get("max_entries", 1000),
            ttl_seconds=semantic_cache_config.get("ttl_seconds", 3600),
            embedding_dim=semantic_cache_config.get("embedding_dim", 768),
        )
        cache = InMemorySemanticCache(embedder=embedder, config=cache_config)
        logger.info(
            "SemanticCache 초기화 성공",
            extra={
                "threshold": cache_config.similarity_threshold,
                "max_entries": cache_config.max_entries,
                "ttl_seconds": cache_config.ttl_seconds
            }
        )
        return cache
    except Exception as e:
        logger.warning(
            "Semantic Cache 초기화 실패",
            extra={"error": str(e)},
            exc_info=True
        )
        return None


def create_vector_store_via_factory(config: dict) -> Any:
    """
    설정 기반 벡터 스토어 생성 (VectorStoreFactory 사용)

    Provider별로 다른 설정 파라미터를 매핑하여 VectorStoreFactory를 통해
    인스턴스를 생성합니다.

    Args:
        config: 설정 딕셔너리 (base.yaml + features/*.yaml 병합)

    Returns:
        IVectorStore 구현체 인스턴스

    Raises:
        ValueError: 지원하지 않는 provider인 경우
        ImportError: 필요한 라이브러리가 미설치된 경우

    지원 Provider:
    - weaviate: Dense + BM25 하이브리드 검색 (기본값)
    - chroma: 경량 로컬 벡터 DB
    - pinecone: 서버리스 클라우드 벡터 DB
    - qdrant: 셀프호스팅/클라우드 하이브리드 검색
    - pgvector: PostgreSQL 기반 벡터 검색
    - mongodb: MongoDB Atlas Vector Search
    """
    provider = config.get("vector_db", {}).get("provider", "weaviate")

    # Provider별 설정 매핑
    store_config: dict[str, Any] = {}

    if provider == "weaviate":
        # Weaviate: URL, API Key, gRPC 포트
        store_config = {
            "url": get_env_url("WEAVIATE_URL", default=os.getenv("WEAVIATE_URL")),
            "api_key": os.getenv("WEAVIATE_API_KEY"),
            "grpc_port": get_env_int(
                "WEAVIATE_GRPC_PORT", default=50051, min_value=1, max_value=65535
            ),
        }
    elif provider == "chroma":
        # Chroma: 영속 디렉토리 (collection_name은 add_documents에서 지정)
        chroma_config = config.get("chroma", {})
        store_config = {
            "persist_directory": chroma_config.get(
                "persist_directory", os.getenv("CHROMA_PERSIST_DIR", "./chroma_data")
            ),
        }
    elif provider == "pinecone":
        # Pinecone: API Key, 인덱스명, namespace
        pinecone_config = config.get("pinecone", {})
        store_config = {
            "api_key": os.getenv("PINECONE_API_KEY"),
            "index_name": pinecone_config.get("index_name", "documents"),
        }
    elif provider == "qdrant":
        # Qdrant: URL, API Key, 컬렉션명
        qdrant_config = config.get("qdrant", {})
        store_config = {
            "url": os.getenv("QDRANT_URL", qdrant_config.get("url", "http://localhost:6333")),
            "api_key": os.getenv("QDRANT_API_KEY"),
            "collection_name": qdrant_config.get("collection_name", "documents"),
        }
    elif provider == "pgvector":
        # pgvector: PostgreSQL DSN (연결 문자열), 테이블명
        pgvector_config = config.get("pgvector", {})
        store_config = {
            "dsn": os.getenv(
                "PGVECTOR_CONNECTION_STRING",
                pgvector_config.get("dsn", os.getenv("DATABASE_URL"))
            ),
            "table_name": pgvector_config.get("table_name", "documents"),
        }
    elif provider == "mongodb":
        # MongoDB Atlas: 연결 문자열, DB명, 컬렉션명, 인덱스명
        mongodb_config = config.get("mongodb", {}).get("vector_search", {})
        store_config = {
            "connection_string": os.getenv("MONGODB_URI"),
            "database_name": mongodb_config.get("database_name", "rag_vectors"),
            "collection_name": mongodb_config.get("collection_name", "documents"),
            "index_name": mongodb_config.get("index_name", "vector_index"),
        }
    else:
        available = VectorStoreFactory.get_available_providers()
        raise ValueError(
            f"지원하지 않는 벡터 스토어 provider: '{provider}'. "
            f"사용 가능한 provider: {', '.join(available)}"
        )

    logger.info(
        "VectorStore 생성 시작",
        extra={"provider": provider}
    )

    return VectorStoreFactory.create(provider, store_config)


def create_retriever_via_factory(
    config: dict,
    embedder: Any,
    vector_store: Any | None = None,
    weaviate_client: Any | None = None,
    synonym_manager: Any | None = None,
    stopword_filter: Any | None = None,
    user_dictionary: Any | None = None,
) -> Any:
    """
    설정 기반 Retriever 생성 (RetrieverFactory 사용)

    Provider별로 다른 설정 파라미터와 의존성을 매핑하여
    RetrieverFactory를 통해 인스턴스를 생성합니다.

    Args:
        config: 설정 딕셔너리
        embedder: 임베딩 모델 인스턴스
        vector_store: VectorStore 인스턴스 (Weaviate 외 provider용)
        weaviate_client: Weaviate 클라이언트 (Weaviate provider용)
        synonym_manager: 동의어 관리자 (하이브리드 지원 provider용)
        stopword_filter: 불용어 필터 (하이브리드 지원 provider용)
        user_dictionary: 사용자 사전 (하이브리드 지원 provider용)

    Returns:
        IRetriever 구현체 인스턴스

    지원 Provider:
    - weaviate: Dense + BM25 하이브리드 (weaviate_client 필요)
    - chroma: Dense 전용 (store 필요)
    - pinecone: Dense + Sparse 하이브리드 (store 필요)
    - qdrant: Dense + Full-Text 하이브리드 (store 필요)
    - pgvector: Dense 전용 (store 필요)
    - mongodb: Dense 전용 (store 필요)
    """
    provider = config.get("vector_db", {}).get("provider", "weaviate")

    # Provider별 설정 매핑
    retriever_config: dict[str, Any] = {}

    # BM25 전처리 모듈 (하이브리드 지원 provider용)
    bm25_preprocessors: dict[str, Any] | None = None
    if RetrieverFactory.supports_hybrid(provider):
        bm25_preprocessors = {
            "synonym_manager": synonym_manager,
            "stopword_filter": stopword_filter,
            "user_dictionary": user_dictionary,
        }

    if provider == "weaviate":
        # Weaviate: weaviate_client 사용 (store 대신)
        weaviate_config = config.get("weaviate", {})
        retriever_config = {
            "weaviate_client": weaviate_client,
            "collection_name": weaviate_config.get("collection_name", "Documents"),
            "alpha": weaviate_config.get("hybrid_search", {}).get("default_alpha", 0.6),
            "additional_collections": weaviate_config.get("additional_collections", []),
            "collection_properties": config.get("domain", {}).get("retrieval", {}).get(
                "collections", {}
            ),
        }
    elif provider == "chroma":
        # Chroma: Dense 전용
        chroma_config = config.get("chroma", {})
        retriever_config = {
            "store": vector_store,
            "collection_name": chroma_config.get("collection_name", "documents"),
            "top_k": chroma_config.get("retrieval", {}).get("default_top_k", 10),
        }
    elif provider == "pinecone":
        # Pinecone: 하이브리드 지원
        pinecone_config = config.get("pinecone", {})
        retriever_config = {
            "store": vector_store,
            "namespace": pinecone_config.get("namespace", "default"),
            "top_k": pinecone_config.get("retrieval", {}).get("default_top_k", 10),
            "hybrid_alpha": pinecone_config.get("hybrid", {}).get("default_alpha", 0.6),
        }
    elif provider == "qdrant":
        # Qdrant: 하이브리드 지원
        qdrant_config = config.get("qdrant", {})
        retriever_config = {
            "store": vector_store,
            "collection_name": qdrant_config.get("collection_name", "documents"),
            "top_k": qdrant_config.get("retrieval", {}).get("default_top_k", 10),
            "hybrid_alpha": qdrant_config.get("hybrid_search", {}).get("default_alpha", 0.6),
        }
    elif provider == "pgvector":
        # pgvector: Dense 전용
        pgvector_config = config.get("pgvector", {})
        retriever_config = {
            "store": vector_store,
            "table_name": pgvector_config.get("table_name", "documents"),
            "top_k": pgvector_config.get("retrieval", {}).get("default_top_k", 10),
        }
    elif provider == "mongodb":
        # MongoDB Atlas: Dense 전용
        mongodb_config = config.get("mongodb", {}).get("vector_search", {})
        retriever_config = {
            "store": vector_store,
            "collection_name": mongodb_config.get("collection_name", "documents"),
            "top_k": mongodb_config.get("retrieval", {}).get("default_top_k", 10),
        }

    logger.info(
        "Retriever 생성 시작",
        extra={
            "provider": provider,
            "hybrid_support": RetrieverFactory.supports_hybrid(provider),
        }
    )

    return RetrieverFactory.create(
        provider=provider,
        embedder=embedder,
        config=retriever_config,
        bm25_preprocessors=bm25_preprocessors,
    )


# ========================================
# AppContainer
# ========================================


class AppContainer(containers.DeclarativeContainer):
    """
    애플리케이션 DI Container

    RAG 시스템의 모든 의존성을 관리하는 중앙 컨테이너.
    dependency-injector 라이브러리 기반.

    Provider 타입:
    - Configuration: YAML 로딩 + 환경 변수 병합
    - Singleton: 공유 상태 (config, llm_factory, weaviate_client 등)
    - Factory: 요청마다 새 인스턴스 (RAGPipeline, ChatService)

    Provider 그룹:
    ┌─────────────────────────────────────────────────────────────┐
    │ 1. Core Singletons (Phase 1)                               │
    │    - llm_factory, tool_executor, weaviate_client           │
    ├─────────────────────────────────────────────────────────────┤
    │ 2. Session & Privacy (Phase 2)                             │
    │    - session, pii_processor, privacy_masker               │
    ├─────────────────────────────────────────────────────────────┤
    │ 3. Retrieval (Phase 2-3)                                   │
    │    - weaviate_retriever, base_reranker, reranker_chain    │
    │    - memory_cache, semantic_cache, retrieval_orchestrator  │
    ├─────────────────────────────────────────────────────────────┤
    │ 4. MCP & Agent (Phase 4-5)                                 │
    │    - mcp_server, agent_orchestrator                        │
    ├─────────────────────────────────────────────────────────────┤
    │ 5. GraphRAG (Phase 7)                                      │
    │    - graph_store, entity_extractor, knowledge_graph_builder│
    ├─────────────────────────────────────────────────────────────┤
    │ 6. Application Services (Factory)                          │
    │    - rag_pipeline, chat_service                            │
    └─────────────────────────────────────────────────────────────┘

    v3.3.0 리팩토링:
    - Provider 그룹별 주석 구조화
    - 문서화 개선 (Provider 의존성 관계 명시)
    """

    # ========================================
    # 1. Configuration Provider
    # ========================================
    config = providers.Configuration()

    # ========================================
    # 2. Core Singletons (Phase 1)
    # ========================================
    # API Key 인증 (전역 싱글톤 재사용)
    # Note: main.py에서 모듈 import 시점에 생성되므로 get_api_key_auth() 사용
    api_key_auth = providers.Singleton(get_api_key_auth)

    llm_factory = providers.Singleton(initialize_llm_factory_wrapper, config=config)

    tool_loader = providers.Singleton(ToolLoader)

    external_api_caller = providers.Singleton(ExternalAPICaller)

    tool_executor = providers.Singleton(
        ToolExecutor, tool_loader=tool_loader, api_caller=external_api_caller
    )

    # PostgreSQL PromptRepository (Hybrid Mode를 위한 Repository 주입)
    prompt_repository = providers.Singleton(PromptRepository, config=config.prompts)

    # PromptManager (Hybrid Mode: PostgreSQL + JSON Fallback)
    prompt_manager = providers.Singleton(
        PromptManager, repository=prompt_repository, use_database=config.prompts.use_database
    )

    cost_tracker = providers.Singleton(CostTracker)

    weaviate_client = providers.Singleton(WeaviateClient)

    circuit_breaker_factory = providers.Singleton(CircuitBreakerFactory, config=config)

    performance_metrics = providers.Singleton(PerformanceMetrics)

    # ========================================
    # 8. Storage & Ingestion Providers (New Architecture)
    # ========================================
    # VectorStore: Factory 패턴으로 Provider 기반 동적 생성
    # VECTOR_DB_PROVIDER 환경변수로 벡터 DB 선택 (기본값: weaviate)
    # 지원: weaviate, chroma, pinecone, qdrant, pgvector, mongodb
    vector_store = providers.Singleton(
        create_vector_store_via_factory,
        config=config,
    )

    metadata_store = providers.Singleton(
        PostgresMetadataStore,
        database_url=os.getenv("DATABASE_URL")
    )

    # Notion Client (IngestionService용)
    notion_client = providers.Singleton(
        NotionAPIClient,
        api_key=os.getenv("NOTION_API_KEY")
    )

    # Ingestion Connector Factory
    connector_factory = providers.Singleton(IngestionConnectorFactory)

    # Ingestion Service
    ingestion_service = providers.Factory(
        IngestionService,
        vector_store=vector_store,
        metadata_store=metadata_store,
        config=config,
        notion_client=notion_client,
        # chunker는 내부 기본값 사용
    )

    # ========================================
    # 3. Async Singletons (Phase 3 - 병렬 초기화)
    # ========================================
    # IP Geolocation 비활성화 (세션 생성 타임아웃 원인 - 9-14초 지연)
    # ip_geolocation = providers.Singleton(
    #     IPGeolocationModule,
    #     config=config
    # )

    memory_service = providers.Singleton(
        MemoryService,
        max_exchanges=config.session.max_exchanges,
        config=config,
        mongodb_client=None,  # MemoryService는 MongoDB 사용하지 않음 (세션은 PostgreSQL)
    )

    session = providers.Singleton(
        EnhancedSessionModule, config=config, memory_service=memory_service
    )

    document_processor = providers.Singleton(DocumentProcessor, config=config)

    # ----------------------------------------
    # Phase 2: 개인정보 보호 모듈 (Generation 전에 정의)
    # ----------------------------------------
    # 화이트리스트 관리자 (공용 - privacy.yaml에서 로드)
    whitelist_manager = providers.Singleton(WhitelistManager)

    # 개인정보 마스킹 (전화번호, 이름) - 화이트리스트 연동
    privacy_masker = providers.Singleton(
        PrivacyMasker,
        mask_phone=config.privacy.masking.phone,
        mask_name=config.privacy.masking.name,
        mask_email=config.privacy.masking.email,
        phone_mask_char=config.privacy.characters.phone,
        name_mask_char=config.privacy.characters.name,
        whitelist=config.domain.privacy.whitelist,  # 도메인 특화 화이트리스트 (domain.yaml)
        name_suffixes=config.domain.privacy.name_suffixes,  # 도메인 특화 이름 호칭 (domain.yaml)
    )

    # ----------------------------------------
    # Phase 3: PII Review System (문서 전처리용)
    # ----------------------------------------
    # spaCy + Regex 하이브리드 PII 탐지기 (공용 화이트리스트 사용)
    pii_detector = providers.Singleton(
        HybridPIIDetector,
        spacy_model=config.privacy.review.spacy_model,
        enable_ner=config.privacy.review.enable_ner,
        context_window=config.privacy.review.context_window,
        whitelist=config.domain.privacy.whitelist,  # 도메인 특화 화이트리스트 (domain.yaml)
    )

    # 정책 기반 PII 처리 결정 엔진
    pii_policy_engine = providers.Singleton(
        PIIPolicyEngine,
        policy_name=config.privacy.review.policy.name,
        entity_actions=config.privacy.review.policy.entity_actions,
        quarantine_threshold=config.privacy.review.policy.quarantine_threshold,
        min_confidence=config.privacy.review.policy.min_confidence,
    )

    # MongoDB 감사 로거 (collection은 런타임에 주입)
    pii_audit_logger = providers.Singleton(
        PIIAuditLogger,
        collection=None,  # MongoDB collection은 initialize 시점에 주입
        enabled=config.privacy.review.audit.enabled,
    )

    # PII 검토 통합 프로세서
    pii_review_processor = providers.Singleton(
        PIIReviewProcessor,
        detector=pii_detector,
        policy_engine=pii_policy_engine,
        audit_logger=pii_audit_logger,
        enabled=config.privacy.review.enabled,
    )

    # 통합 PII 처리 Facade (권장 진입점)
    # 모든 PII 처리 시나리오 지원: answer, document, filename
    pii_processor = providers.Singleton(
        PIIProcessor,
        whitelist_manager=whitelist_manager,
        review_processor=pii_review_processor,  # Phase 7+ 고도화된 리뷰어 주입
        mask_phone=config.privacy.masking.phone,
        mask_name=config.privacy.masking.name,
        mask_email=config.privacy.masking.email,
        phone_mask_char=config.privacy.characters.phone,
        name_mask_char=config.privacy.characters.name,
    )

    generation = providers.Singleton(
        GenerationModule,
        config=config,
        prompt_manager=prompt_manager,
        privacy_masker=privacy_masker,  # Phase 2: 개인정보 마스킹
    )

    evaluation = providers.Singleton(EvaluationDataManager, config=config.evaluation)

    # ========================================
    # 4. Retrieval System (Phase 5 - 순차, embedder 의존)
    # ========================================

    # ----------------------------------------
    # Phase 2: BM25 고도화 모듈
    # ----------------------------------------
    # 동의어 사전 (도메인 특화 줄임말/은어 정규화)
    synonym_manager = providers.Singleton(
        SynonymManager,
        csv_path=config.domain.retrieval.synonyms.csv_path,  # 도메인 특화 사전 경로 (domain.yaml)
        enabled=config.bm25.synonym.enabled,
    )

    # 불용어 필터 (도메인 특화 단어 제거)
    stopword_filter = providers.Singleton(
        StopwordFilter,
        use_defaults=config.bm25.stopword.use_defaults,
        custom_stopwords=config.domain.retrieval.stopwords,  # 도메인 특화 불용어 (domain.yaml)
        enabled=config.bm25.stopword.enabled,
    )

    # 사용자 사전 (도메인 특화 합성어 보호)
    user_dictionary = providers.Singleton(
        UserDictionary,
        use_defaults=config.bm25.user_dictionary.use_defaults,
        custom_entries=config.domain.retrieval.user_dictionary,  # 도메인 특화 사전 (domain.yaml)
        enabled=config.bm25.user_dictionary.enabled,
    )

    # Retriever: Factory 패턴으로 Provider 기반 동적 생성
    # VECTOR_DB_PROVIDER 환경변수로 Retriever 선택 (기본값: weaviate)
    # 하이브리드 지원: weaviate, pinecone, qdrant
    # Dense 전용: chroma, pgvector, mongodb
    retriever = providers.Singleton(
        create_retriever_via_factory,
        config=config,
        embedder=document_processor.provided.embedder,
        vector_store=vector_store,  # Weaviate 외 provider용
        weaviate_client=weaviate_client,  # Weaviate provider용
        synonym_manager=synonym_manager,  # 하이브리드 지원 provider용
        stopword_filter=stopword_filter,
        user_dictionary=user_dictionary,
    )

    # 하위 호환성: weaviate_retriever 별칭 유지
    weaviate_retriever = retriever

    # ----------------------------------------
    # Phase 6: 고급 리랭킹 시스템
    # ----------------------------------------
    # Base Reranker (Gemini Flash or Jina - 기존 호환성)
    base_reranker = providers.Singleton(
        create_reranker_instance, config=config, llm_factory=llm_factory
    )

    # ColBERT Reranker (Jina ColBERT v2 - 토큰 수준 Late Interaction)
    colbert_reranker = providers.Singleton(create_colbert_reranker_instance, config=config)

    # RerankerChain (다중 리랭커 순차 실행: ColBERT → LLM)
    reranker_chain = providers.Singleton(
        create_reranker_chain_instance,
        config=config,
        colbert_reranker=colbert_reranker,
        llm_reranker=base_reranker,
    )

    # Reranker 선택 로직: chain이 활성화되면 chain 사용, 아니면 base_reranker
    # 실제 사용 시 config.reranking.chain.enabled 값에 따라 결정
    reranker = base_reranker  # 하위 호환성 유지

    # ----------------------------------------
    # Phase 6: 시맨틱 캐시
    # ----------------------------------------
    # Semantic Cache (쿼리 임베딩 유사도 기반)
    semantic_cache = providers.Singleton(
        create_semantic_cache_instance,
        config=config,
        embedder=document_processor.provided.embedder,
    )

    # Cache (Redis 분산 캐시 또는 인메모리 캐시)
    memory_cache = providers.Singleton(create_cache_instance, config=config)

    # 통합 캐시: semantic_cache가 활성화되면 사용, 아니면 memory_cache
    # 실제 사용 시 config.cache.semantic.enabled 값에 따라 결정
    cache = memory_cache  # 하위 호환성 유지

    # ----------------------------------------
    # Phase 7: GraphRAG 저장소 (지식 그래프 검색)
    # ----------------------------------------
    # GraphRAGFactory를 통한 그래프 저장소 생성
    # 설정 기반 활성화/비활성화 (graph_rag.enabled)
    # ⚠️ 중요: RetrievalOrchestrator와 MCP 서버에서 참조하므로 먼저 정의
    graph_store = providers.Singleton(
        create_graph_store_instance,
        config=config,
        embedder=document_processor.provided.embedder,
    )

    # RetrievalOrchestrator (프로덕션 아키텍처)
    # Weaviate Retriever + Reranker + Cache 통합 Facade
    # Phase 7: graph_store 주입 (하이브리드 검색 지원)
    # - graph_rag.enabled=true 시 graph_store가 주입됨
    # - RetrievalOrchestrator가 자동으로 VectorGraphHybridSearch 생성
    # - use_graph=True로 검색 시 벡터+그래프 RRF 결합 검색 수행
    retrieval_orchestrator = providers.Singleton(
        RetrievalOrchestrator,
        retriever=weaviate_retriever,
        reranker=reranker,
        cache=cache,
        graph_store=graph_store,  # Phase 7: 하이브리드 검색용 그래프 저장소
        config=config,
    )

    # Retrieval alias (하위 호환성을 위한 retrieval_orchestrator 참조)
    retrieval = retrieval_orchestrator

    # ----------------------------------------
    # Phase 7: GraphRAG 추출기 및 빌더 (지식 그래프 검색)
    # ----------------------------------------
    # Note: graph_store는 RetrievalOrchestrator에서 사용하므로
    # cache 뒤에 미리 정의됨 (위 "Phase 7: GraphRAG 저장소" 섹션 참조)

    # LLM 기반 엔티티 추출기
    # 텍스트에서 인물, 회사, 장소 등 엔티티 추출
    entity_extractor = providers.Singleton(
        create_entity_extractor_instance,
        config=config,
        llm_factory=llm_factory,
    )

    # LLM 기반 관계 추출기
    # 엔티티 간 파트너십, 위치, 소속 등 관계 추출
    relation_extractor = providers.Singleton(
        create_relation_extractor_instance,
        config=config,
        llm_factory=llm_factory,
    )

    # 지식 그래프 빌더
    # 엔티티 추출 → 관계 추출 → 그래프 저장 파이프라인
    knowledge_graph_builder = providers.Singleton(
        create_knowledge_graph_builder_instance,
        config=config,
        graph_store=graph_store,
        entity_extractor=entity_extractor,
        relation_extractor=relation_extractor,
    )

    # ----------------------------------------
    # Phase 4: MCP 서버 (Model Context Protocol)
    # ----------------------------------------
    # MCP 서버 (설정 기반 도구 활성화/비활성화)
    # retriever와 graph_store를 주입하여 도구에서 사용
    mcp_server = providers.Singleton(
        create_mcp_server_instance,
        config=config,
        retriever=weaviate_retriever,
        graph_store=graph_store,
    )

    # ----------------------------------------
    # Phase 5: Agent Orchestrator (Agentic RAG)
    # ----------------------------------------
    # QA-003: Agent 타임아웃 설정 (환경변수)
    def get_agent_config_with_timeout(base_config: dict) -> dict:
        """
        Agent 설정에 환경변수 타임아웃 추가

        AGENT_TIMEOUT_SECONDS 환경변수를 로드하여
        Agent 설정에 timeout_seconds를 추가합니다.

        Args:
            base_config: 기본 설정 딕셔너리

        Returns:
            타임아웃이 추가된 설정 딕셔너리
        """
        timeout_seconds = get_env_int(
            "AGENT_TIMEOUT_SECONDS",
            default=300,  # 5분
            min_value=10,  # 최소 10초
            max_value=3600,  # 최대 1시간
        )

        # Agent 설정 복사 및 타임아웃 추가
        agent_config = dict(base_config)
        if "agent" not in agent_config:
            agent_config["agent"] = {}
        agent_config["agent"]["timeout_seconds"] = timeout_seconds

        logger.info(
            "Agent 타임아웃 설정 완료",
            extra={"timeout_seconds": timeout_seconds}
        )
        return agent_config

    # AgentFactory를 통한 에이전트 생성
    # MCP 서버와 LLM Factory에 의존
    agent_orchestrator = providers.Singleton(
        AgentFactory.create,
        config=providers.Callable(get_agent_config_with_timeout, base_config=config),
        llm_client=llm_factory,
        mcp_server=mcp_server,
    )

    # ========================================
    # 5. Optional Modules (config-based)
    # ========================================

    # ----------------------------------------
    # Phase 9: Evaluation System (평가 시스템)
    # ----------------------------------------
    # EvaluatorFactory를 통한 평가기 생성
    # 설정 기반 활성화/비활성화 (evaluation.enabled)
    evaluator = providers.Singleton(
        create_evaluator_instance,
        config=config,
        llm_factory=llm_factory,
    )

    # Query Router (optional)
    query_router = providers.Singleton(
        LLMQueryRouter,
        config=config,
        generation_module=generation,
        llm_factory=llm_factory,
        circuit_breaker_factory=circuit_breaker_factory,
    )

    # Query Expansion (optional) - 새 아키텍처 from_config() 사용
    # enabled 설정에 따라 쿼리 확장을 켜고 끌 수 있음
    def create_query_expansion(
        config: dict,
        llm_factory: LLMClientFactory | None,
        cb_factory: CircuitBreakerFactory,
    ) -> GPT5QueryExpansionEngine | None:
        """
        쿼리 확장 엔진 생성 (설정 기반 활성화/비활성화)

        query_expansion.enabled 설정이 False이면 None을 반환하여
        쿼리 확장 기능을 비활성화합니다.

        Args:
            config: 설정 딕셔너리
            llm_factory: LLM Factory 인스턴스
            cb_factory: CircuitBreaker 팩토리

        Returns:
            GPT5QueryExpansionEngine 인스턴스 또는 None (비활성화 시)
        """
        query_expansion_config = config.get("query_expansion", {})
        enabled = query_expansion_config.get("enabled", True)

        if not enabled:
            logger.info(
                "Query Expansion 비활성화",
                extra={"config_key": "query_expansion.enabled", "value": False}
            )
            return None

        return GPT5QueryExpansionEngine.from_config(config, llm_factory, cb_factory)

    query_expansion = providers.Singleton(
        create_query_expansion,
        config=config,
        llm_factory=llm_factory,
        cb_factory=circuit_breaker_factory,
    )

    # Self-RAG (optional)
    complexity_calculator = providers.Singleton(
        ComplexityCalculator,
        threshold=config.self_rag.complexity_threshold,
        length_weight=0.3,
        depth_weight=0.4,
        multi_intent_weight=0.3,
    )

    answer_evaluator = providers.Singleton(
        LLMQualityEvaluator,
        api_key=providers.Callable(lambda: os.getenv("GOOGLE_API_KEY")),
        quality_threshold=config.self_rag.quality_threshold,
        relevance_weight=0.35,
        grounding_weight=0.30,
        completeness_weight=0.25,
        confidence_weight=0.10,
    )

    self_rag = providers.Singleton(
        SelfRAGOrchestrator,
        complexity_calculator=complexity_calculator,
        evaluator=answer_evaluator,
        # retrieval Factory는 async이므로, Singleton인 retrieval_orchestrator 사용
        retrieval_module=retrieval_orchestrator,
        generation_module=generation,
        initial_top_k=config.self_rag.initial_top_k,
        retry_top_k=config.self_rag.retry_top_k,
        max_retries=config.self_rag.max_retries,
        enabled=config.self_rag.enabled,
    )

    # ----------------------------------------
    # Phase 3: SQL Search (메타데이터 검색)
    # ----------------------------------------
    # PostgreSQL DatabaseManager (기존 연결 재사용)
    database_manager = providers.Singleton(DatabaseManager)

    # SQL Search Service (LLM 기반 SQL 생성 + PostgreSQL 실행)
    sql_search_service = providers.Singleton(
        SQLSearchService,
        config=config.sql_search,
        db_manager=database_manager,
        api_key=providers.Callable(lambda: os.getenv("OPENROUTER_API_KEY")),
    )

    # ========================================
    # 6. Factory Providers (요청마다 새 인스턴스)
    # ========================================

    # RAGPipeline Factory
    rag_pipeline = providers.Factory(
        RAGPipeline,
        config=config,
        query_router=query_router,
        query_expansion=query_expansion,
        retrieval_module=retrieval,
        generation_module=generation,
        session_module=session,
        self_rag_module=self_rag,  # ✅ Self-RAG 모듈 주입
        extract_topic_func=extract_topic_default,  # 함수 직접 전달
        circuit_breaker_factory=circuit_breaker_factory,  # ✅ Circuit Breaker Factory 주입
        cost_tracker=cost_tracker,  # ✅ 비용 추적기 주입
        performance_metrics=performance_metrics,  # ✅ 성능 메트릭 주입
        sql_search_service=sql_search_service,  # ✅ SQL Search Service 주입 (Phase 3)
        agent_orchestrator=agent_orchestrator,  # ✅ Agent Orchestrator 주입 (Phase 5)
    )

    # ChatService Factory
    chat_service = providers.Factory(
        ChatService,
        modules=providers.Dict(
            llm_factory=llm_factory,
            session=session,
            query_router=query_router,
            query_expansion=query_expansion,
            retrieval=retrieval,
            generation=generation,
            document_processor=document_processor,
            evaluation=evaluation,
            # ip_geolocation=ip_geolocation,  # 비활성화: 세션 생성 타임아웃 원인
            retrieval_orchestrator=retrieval_orchestrator,
            self_rag=self_rag,
        ),
        config=config,
    )


# ========================================
# Lifecycle Helper Functions
# ========================================


async def initialize_async_resources(container: AppContainer) -> None:
    """
    AsyncIO 리소스 초기화 (main.py의 Phase 3 병렬 초기화 재현)

    Args:
        container: AppContainer 인스턴스
    """

    logger.info("Async 리소스 초기화 시작")

    # Phase 3 병렬 초기화 태스크
    init_tasks = {
        # "IP Geolocation": container.ip_geolocation().initialize(),  # 비활성화: 타임아웃 원인
        "Session": container.session().initialize(),
        "Generation": container.generation().initialize(),
        "Evaluation": container.evaluation().initialize(),
        "Tool Executor": container.tool_executor().initialize(),
        "Prompt Repository": container.prompt_repository().initialize(),  # Hybrid Mode: PostgreSQL PromptRepository
        "Database Manager": container.database_manager().initialize(),  # SQL Search용 PostgreSQL 연결
    }

    task_names = list(init_tasks.keys())
    results = await asyncio.gather(*init_tasks.values(), return_exceptions=True)

    # 결과 검증
    failed_modules = []
    for module_name, result in zip(task_names, results, strict=False):
        if isinstance(result, Exception):
            logger.error(
                "모듈 초기화 실패",
                extra={"module": module_name, "error": str(result)},
                exc_info=True
            )
            failed_modules.append((module_name, result))
        else:
            logger.info("모듈 초기화 성공", extra={"module": module_name})

    if failed_modules:
        error_summary = "\n".join([f"  • {name}: {str(err)}" for name, err in failed_modules])
        logger.error(
            "모듈 초기화 실패 (Graceful Degradation)",
            extra={
                "failed_count": len(failed_modules),
                "error_summary": error_summary
            }
        )

        # Phase 1 MVP: Generation, Evaluation, DB 관련 모듈은 선택사항 (API 키/DB 없이도 실행 가능)
        # Quickstart 환경에서는 PostgreSQL 없이도 동작해야 함
        optional_modules = {"Generation", "Evaluation", "Prompt Repository", "Database Manager"}
        critical_failures = [name for name, _ in failed_modules if name not in optional_modules]

        if critical_failures:
            # 선택사항이 아닌 모듈이 실패한 경우에만 RuntimeError 발생
            raise RuntimeError(f"Critical module initialization failed: {critical_failures}")
        else:
            logger.info(
                "선택적 모듈 실패 (Graceful Degradation 적용)",
                extra={"failed_modules": [name for name, _ in failed_modules]}
            )

    # Phase 5 순차 초기화 (의존성 있는 모듈들)
    logger.info("의존 모듈 초기화 시작")

    # Weaviate Retriever (프로덕션 기본값) - Phase 1 MVP에서 선택사항
    try:
        weaviate_retriever_instance = container.weaviate_retriever()
        if asyncio.iscoroutine(weaviate_retriever_instance) or isinstance(
            weaviate_retriever_instance, asyncio.Future
        ):
            weaviate_retriever_instance = await weaviate_retriever_instance
        if hasattr(weaviate_retriever_instance, "initialize"):
            await weaviate_retriever_instance.initialize()
        logger.info("Weaviate Retriever 초기화 성공")
    except Exception as e:
        logger.warning(
            "Weaviate Retriever 초기화 실패 (Graceful Degradation)",
            extra={"error": str(e)},
            exc_info=True
        )
        # Phase 1 MVP: Weaviate를 사용할 수 없으면 다른 검색 방법으로 대체

    # Reranker와 Cache를 먼저 await (async factory이므로)
    reranker = container.reranker()
    if asyncio.iscoroutine(reranker) or isinstance(reranker, asyncio.Future):
        reranker = await reranker  # type: ignore[assignment]
    logger.info("Reranker 해결 완료")

    cache = container.cache()
    if asyncio.iscoroutine(cache) or isinstance(cache, asyncio.Future):
        cache = await cache  # type: ignore[assignment]
    logger.info("Cache 해결 완료")

    # Retrieval Orchestrator (의존성들이 모두 resolved됨)
    orchestrator = container.retrieval_orchestrator()
    if asyncio.iscoroutine(orchestrator) or isinstance(orchestrator, asyncio.Future):
        orchestrator = await orchestrator
    await orchestrator.initialize()
    logger.info("Retrieval Orchestrator 초기화 성공")

    # Self-RAG (retrieval과 generation에 의존, 초기화 후 override 필요)
    self_rag = container.self_rag()
    if asyncio.iscoroutine(self_rag) or isinstance(self_rag, asyncio.Future):
        self_rag = await self_rag
    logger.info("Self-RAG 모듈 해결 완료")

    # Singleton 패턴: 초기화된 인스턴스를 재사용하도록 override
    container.self_rag.override(self_rag)

    logger.info("Async 리소스 초기화 완료")


async def initialize_async_resources_graceful(container: AppContainer) -> None:
    """
    Graceful Degradation을 지원하는 AsyncIO 리소스 초기화

    기존 initialize_async_resources()의 Graceful Degradation 버전입니다.
    Feature flag로 활성화/비활성화할 수 있습니다.

    주요 개선 사항:
    1. 우선순위 기반 초기화 (CRITICAL → IMPORTANT → OPTIONAL)
    2. 모듈별 재시도 및 타임아웃 지원
    3. IMPORTANT/OPTIONAL 실패 시 Graceful Degradation (시스템 계속 동작)
    4. 모듈 상태 추적 및 모니터링

    Args:
        container: AppContainer 인스턴스

    Raises:
        RuntimeError: CRITICAL 모듈 초기화 실패 시
    """
    from app.core.graceful_initializer import (
        GracefulInitializer,
        ModuleConfig,
        ModulePriority,
    )

    logger.info("Graceful 모듈 초기화 시작 (Graceful Degradation)")

    initializer = GracefulInitializer()

    # 헬퍼 함수: 이미 초기화된 Singleton 모듈용 더미 async 함수
    async def _no_op_init():
        """Singleton이나 이미 초기화된 모듈용 더미 함수"""
        return None

    # ========================================
    # 모듈 우선순위 분류 및 등록
    # ========================================

    # CRITICAL 모듈: 시스템 동작에 필수 (실패 시 전체 중단)
    critical_modules = [
        ModuleConfig(
            name="Session",
            priority=ModulePriority.CRITICAL,
            initializer=container.session().initialize,
            timeout=10.0,  # 15초 → 10초 (healthcheck 여유 확보)
            retry_count=2,  # 3회 → 2회 (재시도 시간 단축)
        ),
        ModuleConfig(
            name="Generation",
            priority=ModulePriority.CRITICAL,
            initializer=container.generation().initialize,
            timeout=12.0,  # 20초 → 12초 (API 응답 시간 최소화)
            retry_count=2,  # 3회 → 2회
        ),
        ModuleConfig(
            name="DatabaseManager",
            priority=ModulePriority.CRITICAL,
            initializer=container.database_manager().initialize,
            timeout=10.0,  # SQL Search용 PostgreSQL 연결
            retry_count=2,
        ),
        ModuleConfig(
            name="RetrievalOrchestrator",
            priority=ModulePriority.CRITICAL,
            initializer=container.retrieval_orchestrator().initialize,
            dependencies=["WeaviateRetriever"],
            timeout=15.0,  # 30초 → 15초 (healthcheck 여유 5초 남김)
            retry_count=1,  # 3회 → 1회 (타임아웃 내 빠른 실패)
        ),
        ModuleConfig(
            name="DocumentProcessor",
            priority=ModulePriority.CRITICAL,
            initializer=_no_op_init,  # Singleton, 초기화 불필요
            timeout=5.0,
        ),
    ]

    # IMPORTANT 모듈: 핵심 기능이지만 제한 모드로 동작 가능
    important_modules = [
        # ModuleConfig(  # 비활성화: 세션 생성 타임아웃 원인 (9-14초 지연)
        #     name="IPGeolocation",
        #     priority=ModulePriority.IMPORTANT,
        #     initializer=container.ip_geolocation().initialize,
        #     timeout=5.0,  # 10초 → 5초 (네트워크 기반 모듈 빠른 타임아웃)
        #     retry_count=1,  # 2회 → 1회
        # ),
        ModuleConfig(
            name="Evaluation",
            priority=ModulePriority.IMPORTANT,
            initializer=container.evaluation().initialize,
            timeout=8.0,  # 10초 → 8초
            retry_count=1,  # 2회 → 1회
        ),
        ModuleConfig(
            name="ToolExecutor",
            priority=ModulePriority.IMPORTANT,
            initializer=container.tool_executor().initialize,
            timeout=10.0,  # 15초 → 10초
            retry_count=1,  # 2회 → 1회
        ),
        ModuleConfig(
            name="WeaviateRetriever",
            priority=ModulePriority.IMPORTANT,
            initializer=container.weaviate_retriever().initialize,
            dependencies=["DocumentProcessor"],
            timeout=8.0,  # 20초 → 8초 (Weaviate 연결 지연 시 빠르게 실패 & graceful degradation)
            retry_count=1,  # 2회 → 1회 (1회 실패 후 즉시 Optional로 전환)
        ),
    ]

    # OPTIONAL 모듈: 선택적 기능 (실패 시 무시 가능)
    optional_modules = [
        ModuleConfig(
            name="QueryExpansion",
            priority=ModulePriority.OPTIONAL,
            initializer=_no_op_init,  # from_config()로 이미 초기화됨
            timeout=5.0,
        ),
        ModuleConfig(
            name="SelfRAG",
            priority=ModulePriority.OPTIONAL,
            initializer=_no_op_init,  # Singleton, 초기화 불필요
            timeout=5.0,
        ),
    ]

    # 모듈 등록
    for module in critical_modules + important_modules + optional_modules:
        initializer.register_module(module)

    # ========================================
    # 초기화 실행
    # ========================================
    try:
        await initializer.initialize_all(enable_graceful_degradation=True)

        # 결과 요약
        initializer.log_summary()

        logger.info("Graceful 초기화 완료")

    except RuntimeError as e:
        logger.error(
            "Critical 모듈 초기화 실패",
            extra={"error": str(e)},
            exc_info=True
        )
        raise


async def cleanup_resources(container: AppContainer) -> None:
    """
    애플리케이션 종료 시 리소스 정리

    이슈 #1 수정: dependency-injector의 DeclarativeContainer는 'resources' 속성을 제공하지 않음.
    따라서 싱글톤 인스턴스를 직접 import하거나 container.provider()를 호출하여 정리해야 함.

    정리 순서 (의존성 역순):
    1. Application Services (RAGPipeline, ChatService 등) - Factory이므로 정리 불필요
    2. Session Manager - CleanupService 백그라운드 태스크 중지
    3. Document Processor - 문서 처리 리소스 정리
    4. Graph Store (Neo4j) - 그래프 DB 연결 종료
    5. Retrieval Orchestrator - 캐시 및 검색 리소스 정리
    6. Vector Store (Weaviate) - 벡터 DB 연결 종료
    7. Metadata Store (PostgreSQL) - 메타데이터 DB 연결 종료
    8. 싱글톤 클라이언트 (Weaviate, MongoDB) - main.py에서 별도 처리
    """
    logger.info("애플리케이션 리소스 정리 시작")
    cleanup_errors: list[str] = []

    # 1. Session Manager (CleanupService 백그라운드 태스크 중지)
    try:
        session = container.session()
        if session and hasattr(session, "destroy"):
            logger.info("Session Manager 종료 중")
            await session.destroy()
            logger.info("Session Manager 종료 완료")
    except Exception as e:
        cleanup_errors.append(f"Session Manager: {e}")
        logger.error(
            "Session Manager 종료 실패",
            extra={"error": str(e)},
            exc_info=True
        )

    # 2. Document Processor (문서 처리 리소스 정리)
    try:
        doc_processor = container.document_processor()
        if doc_processor and hasattr(doc_processor, "destroy"):
            logger.info("Document Processor 종료 중")
            await doc_processor.destroy()
            logger.info("Document Processor 종료 완료")
    except Exception as e:
        cleanup_errors.append(f"Document Processor: {e}")
        logger.error(
            "Document Processor 종료 실패",
            extra={"error": str(e)},
            exc_info=True
        )

    # 3. Graph Store (Neo4j 연결 종료)
    try:
        graph_store = container.graph_store()
        if graph_store and hasattr(graph_store, "close"):
            logger.info("Graph Store 종료 중")
            await graph_store.close()
            logger.info("Graph Store 종료 완료")
    except Exception as e:
        cleanup_errors.append(f"Graph Store: {e}")
        logger.error(
            "Graph Store 종료 실패",
            extra={"error": str(e)},
            exc_info=True
        )

    # 4. Retrieval Orchestrator (캐시 및 검색 리소스 정리)
    try:
        retrieval = container.retrieval_orchestrator()
        if retrieval and hasattr(retrieval, "close"):
            logger.info("Retrieval Orchestrator 종료 중")
            await retrieval.close()
            logger.info("Retrieval Orchestrator 종료 완료")
    except Exception as e:
        cleanup_errors.append(f"Retrieval Orchestrator: {e}")
        logger.error(
            "Retrieval Orchestrator 종료 실패",
            extra={"error": str(e)},
            exc_info=True
        )

    # 5. Vector Store (Weaviate Store 연결 종료)
    try:
        vector_store = container.vector_store()
        if vector_store and hasattr(vector_store, "close"):
            logger.info("Vector Store 종료 중")
            vector_store.close()
            logger.info("Vector Store 종료 완료")
    except Exception as e:
        cleanup_errors.append(f"Vector Store: {e}")
        logger.error(
            "Vector Store 종료 실패",
            extra={"error": str(e)},
            exc_info=True
        )

    # 6. Metadata Store (PostgreSQL 연결 종료)
    try:
        metadata_store = container.metadata_store()
        if metadata_store and hasattr(metadata_store, "close"):
            logger.info("Metadata Store 종료 중")
            await metadata_store.close()
            logger.info("Metadata Store 종료 완료")
    except Exception as e:
        cleanup_errors.append(f"Metadata Store: {e}")
        logger.error(
            "Metadata Store 종료 실패",
            extra={"error": str(e)},
            exc_info=True
        )

    # 7. Generation Module (LLM 클라이언트 정리)
    try:
        generation = container.generation()
        if generation and hasattr(generation, "destroy"):
            logger.info("Generation Module 종료 중")
            await generation.destroy()
            logger.info("Generation Module 종료 완료")
    except Exception as e:
        cleanup_errors.append(f"Generation Module: {e}")
        logger.error(
            "Generation Module 종료 실패",
            extra={"error": str(e)},
            exc_info=True
        )

    # 정리 결과 요약
    if cleanup_errors:
        logger.warning(
            "리소스 정리 완료 (오류 발생)",
            extra={
                "error_count": len(cleanup_errors),
                "errors": cleanup_errors
            }
        )
    else:
        logger.info("리소스 정리 완료")
