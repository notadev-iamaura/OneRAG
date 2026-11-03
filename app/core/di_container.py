"""
DI Container - Dependency Injection Container for OneRAG

TASK-H3: main.py 660줄 → 250줄 리팩토링
dependency-injector 라이브러리 기반 DI Container

Provider 타입:
- Configuration: YAML 로딩 + 환경 변수 병합
- Singleton: 공유 상태 (config, llm_factory 등)
- Coroutine: AsyncIO 초기화 필요 (session, retrieval 등)
- Factory: 요청마다 새 인스턴스 (RAGPipeline, ChatService 등)
"""

from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from dependency_injector import containers, providers

# Core modules
from app.lib.auth import get_api_key_auth
from app.lib.circuit_breaker import CircuitBreakerFactory
from app.lib.config_validator import get_env_int, get_env_url

# from app.lib.ip_geolocation import IPGeolocationModule  # 비활성화: 세션 생성 타임아웃 원인
from app.lib.logger import get_logger
from app.lib.metrics import CostTracker, PerformanceMetrics
from app.lib.rerank_mode import (
    RerankerModeConfigError,
    resolve_rerank_mode,
)
from app.lib.startup_policy import is_retrieval_required
from app.lib.topic_extractor import extract_topic

# Phase 5: Agent 모듈 (Agentic RAG Orchestrator)
from app.modules.core.agent import AgentFactory

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
from app.modules.core.retrieval.grok_answer_provider import GrokAnswerProvider
from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator
from app.modules.core.retrieval.query_expansion.gpt5_engine import GPT5QueryExpansionEngine

# Retriever Factory (다중 벡터 DB 지원 - Factory 패턴 적용)
# RetrieverFactory 는 테스트가 di_container.RetrieverFactory 로 패치하므로 재노출을 유지한다.
from app.modules.core.retrieval.retrievers.factory import RetrieverFactory as RetrieverFactory
from app.modules.core.retrieval.retrievers.wiring import build_retriever_from_config
from app.modules.core.routing.complexity_calculator import ComplexityCalculator
from app.modules.core.routing.llm_query_router import LLMQueryRouter
from app.modules.core.self_rag.evaluator import LLMQualityEvaluator
from app.modules.core.self_rag.orchestrator import SelfRAGOrchestrator
from app.modules.core.self_rag.precheck import build_self_rag_evaluator
from app.modules.core.sql_search import SQLSearchService

# Phase 4: Tools 모듈 (Tool Use / Function Calling)
# MCPServer, MCPToolFactory는 ToolServer, ToolFactory의 하위 호환성 alias
from app.modules.core.tools import MCPServer, MCPToolFactory
from app.modules.core.tools.external_api_caller import ExternalAPICaller
from app.modules.core.tools.tool_executor import ToolExecutor
from app.modules.core.tools.tool_loader import ToolLoader
from app.modules.ingestion.factory import IngestionConnectorFactory
from app.modules.ingestion.service import IngestionService

logger = get_logger(__name__)

if TYPE_CHECKING:
    from app.lib.llm_client import LLMClientFactory
    from app.modules.core.retrieval.interfaces import IReranker
    from app.modules.core.retrieval.rerankers.colbert_reranker import (
        JinaColBERTReranker,
    )
    from app.modules.core.retrieval.rerankers.gemini_reranker import (
        GeminiFlashReranker,
    )
    from app.modules.core.retrieval.rerankers.jina_reranker import JinaReranker
    from app.modules.core.retrieval.rerankers.reranker_chain import RerankerChain

def _create_chat_service(*args: Any, **kwargs: Any) -> Any:
    """Create ChatService lazily so importing the container stays lightweight."""
    from app.api.services.chat_service import ChatService

    return ChatService(*args, **kwargs)


def _create_rag_pipeline(*args: Any, **kwargs: Any) -> Any:
    """Create RAGPipeline lazily so optional tracing imports stay off import path."""
    from app.api.services.rag_pipeline import RAGPipeline

    return RAGPipeline(*args, **kwargs)


def _create_document_processor(*args: Any, **kwargs: Any) -> Any:
    """Create DocumentProcessor lazily so local embedding imports stay optional."""
    from app.modules.core.documents.document_processing import DocumentProcessor

    return DocumentProcessor(*args, **kwargs)


def _create_memory_service(*args: Any, **kwargs: Any) -> Any:
    """Create MemoryService lazily so MongoDB clients stay off import path."""
    from app.modules.core.session.services.memory_service import MemoryService

    return MemoryService(*args, **kwargs)


def _create_pii_policy_engine(policy_config: Any = None) -> Any:
    """config.privacy.review.policy에서 PIIPolicy를 구성해 PIIPolicyEngine을 만든다.

    config의 entity_actions는 문자열 키/값(예: {"phone": "mask"})이므로 PIIType/
    PolicyAction enum으로 정규화한다(value 단축 별칭 'review'→REVIEW_ONLY 등 허용).
    기본 정책(PIIPolicy.default()) 위에 config를 오버라이드하므로 미설정 키는
    기본 동작을 유지하고, 누락/오류 시 기본 정책으로 안전 폴백한다(회귀 0).

    주: 이전에는 provider가 PIIPolicyEngine에 policy_name/entity_actions/...를
    직접 넘겼으나 PIIPolicyEngine.__init__은 policy: PIIPolicy|None만 받아
    인스턴스화 시 TypeError였다(PII 리뷰 활성화 시 크래시). 이 팩토리로 교정한다.
    """
    from app.modules.core.privacy.review.models import (
        PIIPolicy,
        PIIType,
        PolicyAction,
    )
    from app.modules.core.privacy.review.policy import PIIPolicyEngine

    # config 단축 표기 → PolicyAction 별칭 맵
    action_aliases = {
        "review": PolicyAction.REVIEW_ONLY,
        "review_only": PolicyAction.REVIEW_ONLY,
        "mask": PolicyAction.MASK_AND_PROCEED,
        "mask_and_proceed": PolicyAction.MASK_AND_PROCEED,
        "block": PolicyAction.BLOCK_ON_VIOLATION,
        "block_on_violation": PolicyAction.BLOCK_ON_VIOLATION,
        "quarantine": PolicyAction.QUARANTINE,
    }

    default_policy = PIIPolicy.default()
    cfg = policy_config if isinstance(policy_config, dict) else {}
    raw_actions = cfg.get("entity_actions")

    # 기본 정책의 entity_actions 위에 config를 오버라이드(미설정 키는 기본 유지)
    entity_actions = dict(default_policy.entity_actions)
    if isinstance(raw_actions, dict):
        for key, value in raw_actions.items():
            try:
                pii_type = PIIType(str(key).strip().lower())
            except ValueError:
                continue  # 알 수 없는 엔티티 타입은 건너뜀(graceful)
            action = action_aliases.get(str(value).strip().lower())
            if action is not None:
                entity_actions[pii_type] = action

    try:
        policy = PIIPolicy(
            name=str(cfg.get("name", default_policy.name)),
            entity_actions=entity_actions,
            quarantine_threshold=int(
                cfg.get("quarantine_threshold", default_policy.quarantine_threshold)
            ),
            min_confidence=float(cfg.get("min_confidence", default_policy.min_confidence)),
            # whitelist_patterns도 형제 키처럼 config에서 읽는다(미설정 시 한국어
            # 기본 PII 오탐방지 목록 → 회귀 0). 비한국어 운영자가 코드 포크 없이
            # 리뷰 화이트리스트를 교체할 수 있게 한다.
            whitelist_patterns=(
                cfg.get("whitelist_patterns") or default_policy.whitelist_patterns
            ),
        )
    except (TypeError, ValueError):
        policy = default_policy  # 설정 파싱 실패 시 기본 정책으로 안전 폴백

    return PIIPolicyEngine(policy)


def _create_chat_store(config: dict[str, Any] | None, db_manager: Any) -> Any | None:
    """채팅 영속화 스토어를 생성합니다(선택적 백엔드).

    0-dependency 기본 보존: `session.chat_persistence.enabled`가 명시적으로 true일
    때만 PostgresChatStore를 생성하고, 그 외에는 None을 반환하여 MemoryService가
    인메모리만 사용하도록 합니다(추가 인프라 불필요). 활성화하더라도 DATABASE_URL
    미연결 시 스토어 내부에서 graceful 하게 영속화를 건너뜁니다.

    Args:
        config: 전체 설정 딕셔너리(session.chat_persistence.enabled 확인용)
        db_manager: 공유 DatabaseManager (기존 PostgreSQL 연결 재사용)

    Returns:
        PostgresChatStore 또는 None(비활성화 시)
    """
    session_config = (config or {}).get("session", {})
    persistence_config = session_config.get("chat_persistence", {})
    if not persistence_config.get("enabled", False):
        # 기본 비활성화: 인메모리만 사용 (0-dependency 기본)
        return None

    from app.infrastructure.storage.chat.postgres_chat_store import PostgresChatStore

    return PostgresChatStore(db_manager=db_manager)


def _create_enhanced_session_module(*args: Any, **kwargs: Any) -> Any:
    """Create EnhancedSessionModule lazily so session storage imports stay optional."""
    from app.modules.core.session.facade import EnhancedSessionModule

    return EnhancedSessionModule(*args, **kwargs)


def _create_notion_client(api_key: str | None = None) -> Any | None:
    """Create optional Notion client lazily if the integration is installed."""
    try:
        from app.batch.notion_client import NotionAPIClient
    except ImportError:
        return None

    return NotionAPIClient(api_key=api_key)


def _create_database_manager(*args: Any, **kwargs: Any) -> Any:
    from app.infrastructure.persistence.connection import DatabaseManager

    return DatabaseManager(*args, **kwargs)


def _create_evaluation_data_manager(*args: Any, **kwargs: Any) -> Any:
    from app.infrastructure.persistence.evaluation_manager import EvaluationDataManager

    return EvaluationDataManager(*args, **kwargs)


def _create_prompt_repository(*args: Any, **kwargs: Any) -> Any:
    from app.infrastructure.persistence.prompt_repository import PromptRepository

    return PromptRepository(*args, **kwargs)


def _create_postgres_metadata_store(*args: Any, **kwargs: Any) -> Any:
    from app.infrastructure.storage.metadata.postgres_store import PostgresMetadataStore

    return PostgresMetadataStore(*args, **kwargs)


def _create_weaviate_client(*args: Any, **kwargs: Any) -> Any:
    from app.lib.weaviate_client import WeaviateClient

    return WeaviateClient(*args, **kwargs)


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
    from app.lib.llm_client import get_llm_factory, initialize_llm_factory

    initialize_llm_factory(config)
    return get_llm_factory()


def extract_topic_default(message: object) -> str:
    """RAGPipeline 주입용 기본 토픽 추출 함수(lib.extract_topic 위임).

    config 미주입 경로이므로 코드 내장 한국어 기본 키워드를 사용한다.
    토픽 추출 로직의 단일 소스는 app.lib.topic_extractor이다.
    """
    return str(extract_topic(message))


def build_extract_topic_func(config: dict) -> Callable[[object], str]:
    """config의 routing.topic_keywords를 바인딩한 토픽 추출 함수를 생성한다.

    RAGPipeline에 주입되는 extract_topic_func은 (message) 단일 인자만
    받으므로, config에서 읽은 키워드 맵을 클로저로 바인딩해 단일 소스
    함수(lib.extract_topic)에 위임한다. 미설정 시 한국어 기본 맵을 쓴다(회귀 0).
    """
    topic_keywords = config.get("routing", {}).get("topic_keywords")

    def _extract(message: object) -> str:
        return str(extract_topic(message, topic_keywords))

    return _extract


async def create_reranker_instance_v2(
    config: dict, llm_factory: LLMClientFactory | None = None
) -> IReranker | None:
    """
    Reranker 인스턴스 생성 (v2 - 새로운 설정 구조)

    approach/provider/model 3단계 구조 지원.
    Legacy API 키 누락 시 None 반환. Jev 설정 오류는 시작 실패로 전파.

    Args:
        config: 설정 딕셔너리
        llm_factory: LLM Factory (optional, 향후 확장용)

    Returns:
        Reranker 인스턴스 또는 None
    """
    from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

    reranking_config = config.get("reranking", {})

    resolved = resolve_rerank_mode(reranking_config, os.environ)
    if resolved.effective == "disabled":
        logger.info("Reranker 비활성화 (enabled=false)", extra={"effective": "disabled"})
        return None

    details: dict[str, Any] = {"effective": resolved.effective, "source": resolved.source}
    if resolved.effective == "legacy":
        details.update(approach=resolved.legacy_approach, provider=resolved.legacy_provider)
    logger.info("Reranker v2 초기화", extra=details)

    try:
        reranker = RerankerFactoryV2.create(config)
        logger.info(
            f"{reranker.__class__.__name__} 초기화 성공",
            extra=details,
        )
        return reranker
    except RerankerModeConfigError:
        logger.error("reranker_mode_config_error", extra=details)
        raise
    except ValueError as e:
        if resolved.effective == "jev":
            raise RerankerModeConfigError("Jev reranker initialization failed") from e
        # API 키 누락 등 설정 오류
        logger.warning(
            "Reranker v2 초기화 실패",
            extra={"error_type": type(e).__name__, "status": "proceeding_without_reranker",
                   "effective_reranker": "none"},
        )
        return None
    except Exception as e:
        if resolved.effective == "jev":
            raise RerankerModeConfigError("Jev reranker initialization failed") from e
        logger.error(
            "Reranker v2 초기화 중 예외 발생",
            extra={"error_type": type(e).__name__, "effective_reranker": "none"},
        )
        return None


async def create_cache_instance(config: dict) -> Any:
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

            cache: Any = RedisCacheManager(
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
                return cache
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
        cache = MemoryCacheManager(
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
        return cache
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
        from app.modules.core.retrieval.rerankers.colbert_reranker import (
            ColBERTRerankerConfig,
            JinaColBERTReranker,
        )

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
    colbert_reranker_provider: Callable[[], Any] | None = None,
    llm_reranker_provider: Callable[[], Any] | None = None,
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
    resolved = resolve_rerank_mode(config.get("reranking", {}), os.environ)
    if resolved.effective == "jev":
        logger.warning("RerankerChain 은 jev 모드에서 사용 안 함")
        return None
    if resolved.effective == "disabled":
        return None
    chain_config = config.get("reranking", {}).get("chain", {})

    # 비활성화 체크
    if not chain_config.get("enabled", False):
        logger.info(
            "RerankerChain 비활성화",
            extra={"config_key": "reranking.chain.enabled", "value": False}
        )
        return None

    # Resolve deferred DI providers only after the mode and chain gates.
    if colbert_reranker_provider is not None:
        colbert_reranker = colbert_reranker_provider()
        if inspect.isawaitable(colbert_reranker):
            colbert_reranker = await colbert_reranker
    if llm_reranker_provider is not None:
        llm_reranker = llm_reranker_provider()
        if inspect.isawaitable(llm_reranker):
            llm_reranker = await llm_reranker

    # 활성화된 리랭커 수집
    rerankers: list[Any] = []
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
        from app.modules.core.retrieval.rerankers.reranker_chain import (
            RerankerChain,
            RerankerChainConfig,
        )

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
    retriever: Any = None,
    graph_store: Any = None,
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
) -> Any:
    """
    Evaluator 인스턴스 생성 헬퍼 함수

    설정 기반 평가기 생성 (EvaluatorFactory 사용).
    기존 create_cache_instance 패턴과 동일.

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
) -> Any:
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
            # BaseLLMClient 의 텍스트 생성 메서드는 generate_text 다(예전 .generate 는 존재하지 않아
            # 평가기 호출 시 AttributeError 가 났다).
            response = await client.generate_text(prompt, model=self._model)
            return str(response)

    return EvaluatorLLMClient(llm_factory, model)


async def create_graph_store_instance(config: dict, embedder: Any = None) -> Any:
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
                # 프롬프트 외부화: graph_rag.extraction.llm.prompt_template.
                # 미설정 시 None → LLMEntityExtractor가 코드 내장 한국어 기본
                # 프롬프트를 사용한다 (회귀 0).
                "prompt_template": llm_config.get("prompt_template"),
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
                # 프롬프트 외부화: graph_rag.extraction.llm.relation_prompt_template.
                # 엔티티 추출기의 prompt_template와 키를 분리해 관계 프롬프트만 교체 가능.
                # 미설정 시 None → LLMRelationExtractor가 코드 내장 한국어 기본
                # 프롬프트를 사용한다 (회귀 0).
                "prompt_template": llm_config.get("relation_prompt_template"),
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
    graph_store: Any = None,
    entity_extractor: Any = None,
    relation_extractor: Any = None,
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


def _create_graph_llm_client(llm_factory: LLMClientFactory, model: str) -> Any:
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
            # BaseLLMClient 의 텍스트 생성 메서드는 generate_text 다(예전 .generate 는 존재하지 않아
            # GraphRAG 엔티티/관계 추출이 DI 경로에서 AttributeError 로 실패했다).
            response = await client.generate_text(
                prompt,
                model=self._model_id,
                max_tokens=2000,
                temperature=0.1,  # 정확한 추출을 위해 낮은 온도
            )
            return str(response)

    return GraphLLMClient(llm_factory, model)


async def create_semantic_cache_instance(
    config: dict,
    embedder: Any = None,
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
    from app.infrastructure.storage.vector.factory import VectorStoreFactory

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
    vector_store_provider: Any | None = None,
    weaviate_client: Any | None = None,
    weaviate_client_provider: Any | None = None,
    synonym_manager: Any | None = None,
    stopword_filter: Any | None = None,
    user_dictionary: Any | None = None,
) -> Any:
    """설정 기반 Retriever 생성 (RetrieverFactory 사용).

    provider별 설정/의존성 매핑은 app.modules.core.retrieval.retrievers.wiring 에 있다.
    컨테이너는 의존성(VectorStore/Weaviate 지연 provider)만 넘기고 배선 로직을 갖지 않는다.
    """
    return build_retriever_from_config(
        config,
        embedder,
        vector_store=vector_store,
        vector_store_provider=vector_store_provider,
        vector_store_factory=create_vector_store_via_factory,
        weaviate_client=weaviate_client,
        weaviate_client_provider=weaviate_client_provider,
        synonym_manager=synonym_manager,
        stopword_filter=stopword_filter,
        user_dictionary=user_dictionary,
    )



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
    prompt_repository = providers.Singleton(_create_prompt_repository, config=config.prompts)

    # PromptManager (Hybrid Mode: PostgreSQL + JSON Fallback)
    prompt_manager = providers.Singleton(
        PromptManager,
        repository=prompt_repository,
        use_database=config.prompts.use_database,
        cache_ttl=config.prompts.cache_ttl,
        # 시드 프롬프트 오버라이드 외부화: prompts.seed_prompts(미설정 시 None →
        # 코드 내장 DEFAULT_SEED_PROMPTS 한국어 기본, 회귀 0). 생성자에 노출만 돼
        # 있고 라이브 배선이 없던 데드 주입 경로를 해소한다.
        default_prompts=config.prompts.seed_prompts,
    )

    cost_tracker = providers.Singleton(CostTracker)

    weaviate_client = providers.Singleton(_create_weaviate_client)

    circuit_breaker_factory = providers.Singleton(CircuitBreakerFactory, config=config)

    performance_metrics = providers.Singleton(PerformanceMetrics)

    # ========================================
    # 8. Storage & Ingestion Providers (New Architecture)
    # ========================================
    # VectorStore: Factory 패턴으로 VectorStore 기반 Provider 동적 생성
    # VECTOR_DB_PROVIDER 환경변수로 벡터 DB 선택 (기본값: weaviate)
    # 지원: weaviate, chroma, pinecone, qdrant, pgvector, mongodb
    vector_store = providers.Singleton(
        create_vector_store_via_factory,
        config=config,
    )

    metadata_store = providers.Singleton(
        _create_postgres_metadata_store,
        database_url=os.getenv("DATABASE_URL")
    )

    # 외부 데이터 소스 클라이언트 (선택적 모듈 - Notion 등)
    notion_client = providers.Singleton(
        _create_notion_client,
        api_key=os.getenv("NOTION_API_KEY"),
    )

    # Ingestion Connector Factory
    connector_factory = providers.Singleton(IngestionConnectorFactory)

    # Ingestion Service
    # chunker를 주입하지 않으면 IngestionService가 config의
    # domain.batch.section_keywords/target_fields를 읽어 MetadataChunker를 생성한다
    # (데드 config 키 해소). 미설정 시 도메인 중립 기본값 사용.
    ingestion_service = providers.Factory(
        IngestionService,
        vector_store=vector_store,
        metadata_store=metadata_store,
        config=config,
        notion_client=notion_client,
    )

    # ========================================
    # 3. Async Singletons (Phase 3 - 병렬 초기화)
    # ========================================
    # IP Geolocation 비활성화 (세션 생성 타임아웃 원인 - 9-14초 지연)
    # ip_geolocation = providers.Singleton(
    #     IPGeolocationModule,
    #     config=config
    # )

    # PostgreSQL DatabaseManager (기존 연결 재사용) — chat_store/sql_search 공용 싱글톤.
    # memory_service보다 먼저 정의해야 chat_store가 참조할 수 있다(정의 순서 중요).
    database_manager = providers.Singleton(_create_database_manager)

    # 채팅 영속화 스토어 (선택적 백엔드). session.chat_persistence.enabled=true 일 때만
    # PostgresChatStore 생성, 그 외에는 None(인메모리 기본 — 0-dependency 보존).
    chat_store = providers.Singleton(
        _create_chat_store,
        config=config,
        db_manager=database_manager,
    )

    memory_service = providers.Singleton(
        _create_memory_service,
        max_exchanges=config.session.max_exchanges,
        config=config,
        mongodb_client=None,  # MemoryService는 MongoDB 사용하지 않음 (세션은 PostgreSQL)
        chat_store=chat_store,  # 선택적 영속화 백엔드 (비활성화 시 None)
    )

    session = providers.Singleton(
        _create_enhanced_session_module, config=config, memory_service=memory_service
    )

    document_processor = providers.Singleton(_create_document_processor, config=config)

    # ----------------------------------------
    # Phase 2: 개인정보 보호 모듈 (Generation 전에 정의)
    # ----------------------------------------
    # 화이트리스트 관리자 (공용 - privacy.yaml에서 로드)
    whitelist_manager = providers.Singleton(WhitelistManager)

    # 개인정보 마스킹 (전화번호, 이름) - 화이트리스트 연동
    # PII 정규식 패턴/이름 글자클래스/파일명 라벨은 privacy.yaml에서 외부화한다.
    # 미설정 시 PrivacyMasker 내부의 한국 기본 패턴으로 폴백한다(보안 회귀 0).
    privacy_masker = providers.Singleton(
        PrivacyMasker,
        mask_phone=config.privacy.masking.phone,
        mask_name=config.privacy.masking.name,
        mask_email=config.privacy.masking.email,
        phone_mask_char=config.privacy.characters.phone,
        name_mask_char=config.privacy.characters.name,
        whitelist=config.domain.privacy.whitelist,  # 도메인 특화 화이트리스트 (domain.yaml)
        name_suffixes=config.domain.privacy.name_suffixes,  # 도메인 특화 이름 호칭 (domain.yaml)
        patterns=config.privacy.patterns,  # PII 정규식 패턴 오버라이드 (privacy.yaml)
        name_char_class=config.privacy.name_char_class,  # 이름 글자클래스 (privacy.yaml)
        filename_mask_label=config.privacy.filename_mask_label,  # 파일명 라벨 (privacy.yaml)
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
        patterns=config.privacy.review.patterns,  # PII 정규식 오버라이드 (privacy.yaml)
        # spaCy NER 라벨→PIIType 매핑 오버라이드 (privacy.yaml). 비우면 코드 기본
        # 한국/KLUE 라벨 매핑으로 폴백한다(회귀 0). 타 언어 모델 교체 시 주입.
        ner_label_mapping=config.privacy.review.ner_label_mapping,
    )

    # 정책 기반 PII 처리 결정 엔진
    # PIIPolicyEngine은 policy: PIIPolicy만 받으므로, config의 정책 값을 팩토리에서
    # PIIPolicy로 구성해 주입한다(이전 직접 kwargs 전달은 TypeError였음).
    pii_policy_engine = providers.Singleton(
        _create_pii_policy_engine,
        policy_config=config.privacy.review.policy,
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
        # PII 마스킹 치환 라벨 오버라이드 (privacy.yaml). 비우면 코드 기본
        # 한국어 라벨(DEFAULT_MASK_TEMPLATES)로 폴백한다(회귀 0). 비한국어
        # 운영자는 review.mask_templates로 자국어 라벨을 코드 포크 없이 주입.
        mask_templates=config.privacy.review.mask_templates,
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

    evaluation = providers.Singleton(_create_evaluation_data_manager, config=config.evaluation)

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
    # 하이브리드 지원: weaviate, chroma, pinecone, qdrant, grok
    # Dense 전용: pgvector, mongodb
    retriever = providers.Singleton(
        create_retriever_via_factory,
        config=config,
        embedder=document_processor.provided.embedder,
        vector_store_provider=vector_store.provider,  # Weaviate 외 provider용, 지연 생성
        weaviate_client_provider=weaviate_client.provider,  # Weaviate provider용, 지연 생성
        synonym_manager=synonym_manager,  # 하이브리드 지원 provider용
        stopword_filter=stopword_filter,
        user_dictionary=user_dictionary,
    )

    # 하위 호환성: weaviate_retriever 별칭 유지
    weaviate_retriever = retriever

    # ----------------------------------------
    # Phase 6: 고급 리랭킹 시스템
    # ----------------------------------------
    # Base Reranker (reranking.yaml v2.1: approach/provider/model 3단계 구조)
    # create_reranker_instance_v2가 RerankerFactoryV2를 통해 설정대로 생성한다.
    base_reranker = providers.Singleton(
        create_reranker_instance_v2, config=config, llm_factory=llm_factory
    )

    # ColBERT Reranker (Jina ColBERT v2 - 토큰 수준 Late Interaction)
    colbert_reranker = providers.Singleton(create_colbert_reranker_instance, config=config)

    # RerankerChain (다중 리랭커 순차 실행: ColBERT → LLM)
    reranker_chain = providers.Singleton(
        create_reranker_chain_instance,
        config=config,
        colbert_reranker_provider=colbert_reranker.provider,
        llm_reranker_provider=base_reranker.provider,
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
        # 복잡도 마커 외부화: routing.complexity.{depth_indicators,multi_intent_indicators}.
        # 미설정 시 None → ComplexityCalculator가 코드 내장 한국어 기본 마커를
        # 사용한다(회귀 0). 비한국어 운영자는 routing.yaml로 자국어 마커를 주입한다.
        depth_indicators=config.routing.complexity.depth_indicators,
        multi_intent_indicators=config.routing.complexity.multi_intent_indicators,
        # 언어 중립 신호 보강 토글(기본 False — 기존 동작 동치).
        use_language_neutral_signals=config.routing.complexity.use_language_neutral_signals,
    )

    answer_evaluator = providers.Singleton(
        LLMQualityEvaluator,
        api_key=providers.Callable(lambda: os.getenv("GOOGLE_API_KEY")),
        model_name=config.self_rag.evaluation.model,
        timeout_seconds=config.self_rag.evaluation.timeout,
        quality_threshold=config.self_rag.quality_threshold,
        relevance_weight=0.35,
        grounding_weight=0.30,
        completeness_weight=0.25,
        confidence_weight=0.10,
        # 평가 프롬프트 외부화: self_rag.evaluation.prompt_template.
        # 미설정 시 None → LLMQualityEvaluator가 코드 내장 한국어 기본 프롬프트를
        # 사용한다 (회귀 0).
        evaluation_prompt_template=config.self_rag.evaluation.prompt_template,
        # 컨텍스트 문서 라벨 외부화: self_rag.evaluation.document_label_template.
        document_label_template=config.self_rag.evaluation.document_label_template,
    )

    # off에서는 answer_evaluator와 동일한 인스턴스 반환 (provider/HTTP 생성 없음).
    self_rag_evaluator = providers.Singleton(
        build_self_rag_evaluator,
        base_evaluator=answer_evaluator,
        precheck_config=config.self_rag.precheck,
    )

    self_rag = providers.Singleton(
        SelfRAGOrchestrator,
        complexity_calculator=complexity_calculator,
        evaluator=self_rag_evaluator,
        # retrieval Factory는 async이므로, Singleton인 retrieval_orchestrator 사용
        retrieval_module=retrieval_orchestrator,
        generation_module=generation,
        initial_top_k=config.self_rag.initial_top_k,
        retry_top_k=config.self_rag.retry_top_k,
        max_retries=config.self_rag.max_retries,
        enabled=config.self_rag.enabled,
        enable_rollback=config.self_rag.enable_rollback,
        rollback_threshold=config.self_rag.rollback_threshold,
    )

    # ----------------------------------------
    # Phase 3: SQL Search (메타데이터 검색)
    # ----------------------------------------
    # NOTE: database_manager 싱글톤은 memory_service보다 먼저 정의되도록 위로 이동했습니다
    # (chat_store가 database_manager를 참조하므로 정의 순서가 중요). 아래 sql_search_service는
    # 동일한 공유 database_manager 싱글톤을 그대로 재사용합니다.

    # SQL Search Service (LLM 기반 SQL 생성 + PostgreSQL 실행)
    sql_search_service = providers.Singleton(
        SQLSearchService,
        config=config.sql_search,
        db_manager=database_manager,
        api_key=providers.Callable(lambda: os.getenv("OPENROUTER_API_KEY")),
    )

    # Grok Managed RAG answer mode (optional)
    grok_answer_provider = providers.Singleton(
        GrokAnswerProvider,
        api_key=config.grok.api_key,
        collection_ids=config.grok.collection_ids,
        model=config.grok.model,
        api_url=config.grok.answer_api_url,
        timeout=config.grok.timeout,
        top_k=config.grok.top_k,
    )

    # ========================================
    # 6. Factory Providers (요청마다 새 인스턴스)
    # ========================================

    # RAGPipeline Factory
    rag_pipeline = providers.Factory(
        _create_rag_pipeline,
        config=config,
        query_router=query_router,
        query_expansion=query_expansion,
        retrieval_module=retrieval,
        generation_module=generation,
        session_module=session,
        self_rag_module=self_rag,  # ✅ Self-RAG 모듈 주입
        # 토픽 추출 함수: config(routing.topic_keywords) 바인딩.
        # 미설정 시 한국어 기본 키워드로 동작한다(회귀 0).
        extract_topic_func=providers.Callable(
            build_extract_topic_func, config=config
        ),
        circuit_breaker_factory=circuit_breaker_factory,  # ✅ Circuit Breaker Factory 주입
        cost_tracker=cost_tracker,  # ✅ 비용 추적기 주입
        performance_metrics=performance_metrics,  # ✅ 성능 메트릭 주입
        sql_search_service=sql_search_service,  # ✅ SQL Search Service 주입 (Phase 3)
        agent_orchestrator=agent_orchestrator,  # ✅ Agent Orchestrator 주입 (Phase 5)
        grok_answer_provider=grok_answer_provider,  # Grok managed RAG answer mode
    )

    # ChatService Factory
    chat_service = providers.Factory(
        _create_chat_service,
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


async def _await_if_needed(value: Any) -> Any:
    """async Singleton provider 가 돌려주는 코루틴/Future 를 실제 인스턴스로 풀어준다."""
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        return await value
    return value


async def _init_weaviate_retriever(container: AppContainer) -> None:
    """Weaviate Retriever 를 해결하고 initialize() 가 있으면 호출한다."""
    instance = await _await_if_needed(container.weaviate_retriever())
    if hasattr(instance, "initialize"):
        await instance.initialize()


async def _init_retrieval_orchestrator(container: AppContainer) -> None:
    """Reranker/Cache(async 팩토리)를 먼저 해결한 뒤 Retrieval Orchestrator 를 초기화한다."""
    await _await_if_needed(container.reranker())
    await _await_if_needed(container.cache())
    orchestrator = await _await_if_needed(container.retrieval_orchestrator())
    await orchestrator.initialize()


async def _init_self_rag(container: AppContainer) -> None:
    """Self-RAG(async Singleton)를 해결하고 같은 인스턴스를 재사용하도록 override 한다."""
    self_rag = await _await_if_needed(container.self_rag())
    container.self_rag.override(self_rag)


async def _no_op_init() -> None:
    """Singleton 이거나 from_config() 로 이미 초기화된 모듈용 더미 초기화 함수."""
    return None


def _build_startup_modules(
    container: AppContainer, *, retrieval_required: bool, graceful: bool
) -> list[Any]:
    """두 기동 모드가 공유하는 모듈 그래프를 만든다.

    graceful=True 는 healthcheck 안에 끝나도록 짧은 타임아웃/재시도를 쓰고,
    graceful=False(표준)는 넉넉한 타임아웃으로 한 번만 시도한다. 모듈 목록과 의존성,
    우선순위는 두 모드가 같다. (예전에는 두 함수가 서로 다른 모듈 집합을 따로 들고 있어
    한쪽만 고쳐지는 일이 반복됐다.)
    """
    from app.core.graceful_initializer import ModuleConfig, ModulePriority

    def timing(graceful_timeout: float, graceful_retry: int) -> dict[str, Any]:
        if graceful:
            return {"timeout": graceful_timeout, "retry_count": graceful_retry}
        return {"timeout": 30.0, "retry_count": 1}

    orchestrator_priority = (
        ModulePriority.CRITICAL if retrieval_required else ModulePriority.IMPORTANT
    )
    return [
        ModuleConfig(
            name="Session",
            priority=ModulePriority.CRITICAL,
            initializer=container.session().initialize,
            **timing(10.0, 2),
        ),
        ModuleConfig(
            name="Generation",
            # Quickstart 는 LLM 키 없이도 떠야 하므로 CRITICAL 이 아니다.
            priority=ModulePriority.IMPORTANT,
            initializer=container.generation().initialize,
            **timing(12.0, 2),
        ),
        ModuleConfig(
            name="DatabaseManager",
            priority=ModulePriority.IMPORTANT,
            initializer=container.database_manager().initialize,
            **timing(10.0, 2),
        ),
        ModuleConfig(
            name="PromptRepository",
            priority=ModulePriority.OPTIONAL,
            initializer=container.prompt_repository().initialize,
            **timing(8.0, 1),
        ),
        ModuleConfig(
            name="DocumentProcessor",
            priority=ModulePriority.CRITICAL,
            initializer=_no_op_init,
            timeout=5.0,
        ),
        ModuleConfig(
            name="Evaluation",
            priority=ModulePriority.IMPORTANT,
            initializer=container.evaluation().initialize,
            **timing(8.0, 1),
        ),
        ModuleConfig(
            name="ToolExecutor",
            priority=ModulePriority.CRITICAL,
            initializer=container.tool_executor().initialize,
            **timing(10.0, 1),
        ),
        ModuleConfig(
            name="WeaviateRetriever",
            priority=ModulePriority.CRITICAL if retrieval_required else ModulePriority.IMPORTANT,
            initializer=lambda: _init_weaviate_retriever(container),
            dependencies=["DocumentProcessor"],
            **timing(8.0, 1),
        ),
        ModuleConfig(
            name="RetrievalOrchestrator",
            priority=orchestrator_priority,
            initializer=lambda: _init_retrieval_orchestrator(container),
            dependencies=["WeaviateRetriever"],
            **timing(15.0, 1),
        ),
        ModuleConfig(
            name="SelfRAG",
            priority=ModulePriority.OPTIONAL,
            initializer=lambda: _init_self_rag(container),
            dependencies=["RetrievalOrchestrator"],
            timeout=10.0,
        ),
        ModuleConfig(
            name="QueryExpansion",
            priority=ModulePriority.OPTIONAL,
            initializer=_no_op_init,
            timeout=5.0,
        ),
    ]


async def _run_startup(container: AppContainer, *, graceful: bool) -> None:
    """공통 기동 루틴: 모듈 그래프 등록 → 우선순위 순 초기화 → 요약 로그."""
    from app.core.graceful_initializer import GracefulInitializer

    retrieval_required = is_retrieval_required()
    mode = "graceful" if graceful else "standard"
    logger.info(
        "Async 리소스 초기화 시작",
        extra={"mode": mode, "retrieval_required": retrieval_required},
    )
    initializer = GracefulInitializer()
    for module in _build_startup_modules(
        container, retrieval_required=retrieval_required, graceful=graceful
    ):
        initializer.register_module(module)
    try:
        # IMPORTANT/OPTIONAL 실패는 두 모드 모두 degraded 로 계속 뜬다(퀵스타트: DB/LLM 키 없이 기동).
        # CRITICAL 실패(Session/ToolExecutor/필수 검색)는 RuntimeError 로 기동을 중단한다.
        await initializer.initialize_all(enable_graceful_degradation=True)
    except RuntimeError as e:
        logger.error("Critical 모듈 초기화 실패", extra={"mode": mode, "error": str(e)}, exc_info=True)
        raise
    initializer.log_summary()
    logger.info("Async 리소스 초기화 완료", extra={"mode": mode})


async def initialize_async_resources(container: AppContainer) -> None:
    """표준 기동 모드(넉넉한 타임아웃, 재시도 1회). 모듈 그래프는 graceful 모드와 같다."""
    await _run_startup(container, graceful=False)


async def initialize_async_resources_graceful(container: AppContainer) -> None:
    """Graceful 기동 모드(healthcheck 안에 끝나도록 짧은 타임아웃/재시도)."""
    await _run_startup(container, graceful=True)


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
    6. Self-RAG precheck provider - HTTP 클라이언트 정리
    7. Vector Store (Weaviate) - 벡터 DB 연결 종료
    8. Metadata Store (PostgreSQL) - 메타데이터 DB 연결 종료
    9. 싱글톤 클라이언트 (Weaviate, MongoDB) - main.py에서 별도 처리
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
            close_result = graph_store.close()
            if inspect.isawaitable(close_result):
                await close_result
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

    # The reranker singleton may be a Future. Close independently even if retrieval
    # cleanup failed before reaching it; Jev.close is idempotent and honors ownership.
    try:
        reranker_provider = getattr(container, "reranker", None)
        reranker = reranker_provider() if reranker_provider is not None else None
        if inspect.isawaitable(reranker):
            reranker = await reranker
        if reranker is not None and hasattr(reranker, "close"):
            await reranker.close()
    except Exception as e:
        cleanup_errors.append(f"Reranker: {type(e).__name__}")
        logger.error("Reranker 종료 실패", extra={"error_type": type(e).__name__})

    # 4a. Self-RAG precheck provider (off일 때 싱글톤 체인을 만들지 않음)
    try:
        mode = container.config.self_rag.precheck.mode()
        if isinstance(mode, dict):
            mode = mode.get("mode")
        if mode and mode != "off":
            evaluator = container.self_rag_evaluator()
            if hasattr(evaluator, "aclose"):
                logger.info("Self-RAG precheck provider 종료 중")
                await evaluator.aclose()
                logger.info("Self-RAG precheck provider 종료 완료")
    except Exception as e:
        cleanup_errors.append(f"Self-RAG precheck provider: {e}")
        logger.error(
            "Self-RAG precheck provider 종료 실패",
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
