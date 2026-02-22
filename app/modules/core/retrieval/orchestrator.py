"""
Retrieval Orchestrator - Facade Pattern으로 검색 워크플로우 통합

## 오케스트레이터(Orchestrator)란?
복잡한 검색 시스템의 여러 구성요소(Retriever, Reranker, Cache)를 하나의 간단한 인터페이스로 통합하는
Facade 패턴 구현입니다.

## 왜 오케스트레이터가 필요한가?

### 1. 복잡성 숨김 (Complexity Hiding)
클라이언트가 여러 모듈의 세부사항을 알 필요 없이 `search_and_rerank()` 한 번의 호출로
전체 검색 프로세스를 실행할 수 있습니다.

**Without Orchestrator:**
```python
# 클라이언트가 복잡한 순서를 직접 관리해야 함
retriever = MongoDBRetriever(...)
reranker = JinaReranker(...)
cache = MemoryCacheManager(...)

# 1. 캐시 확인
cache_key = cache.generate_cache_key(query, top_k)
cached = await cache.get(cache_key)
if cached:
    return cached

# 2. 검색 실행
results = await retriever.search(query, top_k)

# 3. 리랭킹 실행
reranked = await reranker.rerank(query, results, top_k)

# 4. 캐시 저장
await cache.set(cache_key, reranked)
```

**With Orchestrator:**
```python
# 간단한 한 줄 호출
results = await orchestrator.search_and_rerank(query, top_k)
```

### 2. 워크플로우 조율 (Workflow Coordination)
검색 → 캐싱 → 리랭킹의 복잡한 순서와 에러 처리를 내부에서 자동으로 관리합니다.

### 3. 유연한 구성 (Flexible Configuration)
Dependency Injection을 통해 다양한 Retriever/Reranker 조합을 쉽게 교체할 수 있습니다.

```python
# MongoDB + Gemini Flash 조합 (프로덕션)
orchestrator1 = RetrievalOrchestrator(
    retriever=MongoDBRetriever(...),
    reranker=GeminiFlashReranker(...),
    cache=MemoryCacheManager(...)
)

# MongoDB + Jina 조합 (대안)
orchestrator2 = RetrievalOrchestrator(
    retriever=MongoDBRetriever(...),
    reranker=CohereReranker(...),
    cache=RedisCacheManager(...)
)
```

### 4. 관심사 분리 (Separation of Concerns)
- Retriever: 벡터 검색에만 집중
- Reranker: 리랭킹에만 집중
- Cache: 캐싱에만 집중
- Orchestrator: 전체 흐름 조율에만 집중

### 5. 테스트 용이성 (Testability)
각 구성요소를 독립적으로 Mock/Test할 수 있습니다.

```python
# 테스트 시 Mock 주입 가능
mock_retriever = MockRetriever()
mock_reranker = MockReranker()
orchestrator = RetrievalOrchestrator(mock_retriever, mock_reranker, cache)
```

## 아키텍처 다이어그램

```
┌─────────────────────────────────────────────────┐
│          Client (chat.py, APIs)                 │
└────────────────┬────────────────────────────────┘
                 │ search_and_rerank(query, top_k)
                 ▼
┌─────────────────────────────────────────────────┐
│     RetrievalOrchestrator (Facade)              │
│  ┌───────────────────────────────────────────┐  │
│  │ 1. 캐시 확인 → ICacheManager              │  │
│  │ 2. 검색 실행 → IRetriever                 │  │
│  │ 3. 리랭킹 → IReranker (선택적)            │  │
│  │ 4. 캐시 저장 → ICacheManager              │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
         │              │              │
         ▼              ▼              ▼
┌──────────────┐ ┌─────────────┐ ┌──────────────┐
│ MongoDBRet...│ │GeminiFlash..│ │ MemoryCache..│
└──────────────┘ └─────────────┘ └──────────────┘
```

## 기존 코드 기반
이 코드는 기존 `retrieval_rerank.py`의 RetrievalModule의 워크플로우를 추출하여
Facade 패턴으로 재구성한 것입니다.

⚠️ 주의: 기존 검증된 워크플로우를 재사용합니다. 새로 작성하지 않았습니다.
"""

from typing import TYPE_CHECKING, Any

from ....lib.logger import get_logger
from ....lib.types import HealthCheckDict, OrchestratorStatsDict
from .interfaces import ICacheManager, IReranker, IRetriever, SearchResult
from .query_expansion import IQueryExpansionEngine
from .scoring import ScoringService

# 순환 참조 방지를 위한 TYPE_CHECKING 블록
if TYPE_CHECKING:
    from ...graph.interfaces import IGraphStore
    from .hybrid_search.interfaces import IHybridSearchStrategy

logger = get_logger(__name__)


class RetrievalOrchestrator:
    """
    검색 워크플로우를 조율하는 Facade 클래스

    역할:
    1. Retriever, Reranker, Cache를 하나의 인터페이스로 통합
    2. 검색 → 캐싱 → 리랭킹의 복잡한 순서를 내부에서 자동 관리
    3. 에러 핸들링 및 폴백 로직 제공
    4. 통계 수집 및 모니터링

    기존 코드 기반: retrieval_rerank.py의 RetrievalModule 워크플로우
    """

    def __init__(
        self,
        retriever: IRetriever,
        reranker: IReranker | None = None,
        cache: ICacheManager | None = None,
        query_expansion: IQueryExpansionEngine | None = None,
        graph_store: "IGraphStore | None" = None,
        hybrid_strategy: "IHybridSearchStrategy | None" = None,
        config: dict[str, Any] | None = None,
    ):
        """
        Args:
            retriever: 벡터 검색을 담당하는 Retriever (필수)
            reranker: 리랭킹을 담당하는 Reranker (선택적)
            cache: 캐싱을 담당하는 CacheManager (선택적)
            query_expansion: 쿼리 확장 엔진 (선택적)
            graph_store: 그래프 저장소 (선택적, 하이브리드 검색용)
            hybrid_strategy: 하이브리드 검색 전략 (선택적, 직접 제공)
            config: 추가 설정 (검색 옵션, 리랭킹 옵션 등)
                - hybrid_search: 하이브리드 검색 설정
                    - enabled: 활성화 여부 (기본값: False)
                    - vector_weight: 벡터 검색 가중치 (기본값: 0.6)
                    - graph_weight: 그래프 검색 가중치 (기본값: 0.4)
                    - rrf_k: RRF 상수 (기본값: 60)
        """
        self.retriever = retriever
        self.reranker = reranker
        self.cache = cache
        self.query_expansion = query_expansion
        self.graph_store = graph_store
        self.config = config or {}

        # 🆕 ScoringService 초기화 (설정 기반 가중치 적용)
        scoring_config = self.config.get("scoring", {})
        self.scoring_service = ScoringService(scoring_config)

        # 🆕 하이브리드 검색 전략 설정
        # 우선순위: 직접 주입 > graph_store 기반 자동 생성
        self._hybrid_strategy = hybrid_strategy

        # graph_rag 설정에서 hybrid_search 읽기
        graph_rag_config = self.config.get("graph_rag", {})
        hybrid_config = graph_rag_config.get("hybrid_search", {})

        if self._hybrid_strategy is None and graph_store is not None:
            # 하이브리드 검색 설정 확인
            hybrid_enabled = hybrid_config.get("enabled", True)  # graph_store가 있으면 기본 활성화

            if hybrid_enabled:
                # VectorGraphHybridSearch 자동 생성
                from .hybrid_search import VectorGraphHybridSearch

                self._hybrid_strategy = VectorGraphHybridSearch(
                    retriever=retriever,
                    graph_store=graph_store,
                    config=hybrid_config,
                )
                logger.info("하이브리드 검색 활성화 (벡터+그래프 RRF)")

        # 🆕 자동 하이브리드 검색 활성화 플래그 설정
        # YAML 설정의 graph_rag.hybrid_search.auto_enable 값을 기반으로 결정
        # 조건: enabled=true AND auto_enable=true AND hybrid_strategy 존재
        self._auto_use_graph = (
            hybrid_config.get("enabled", True)
            and hybrid_config.get("auto_enable", False)
            and self._hybrid_strategy is not None
        )

        if self._auto_use_graph:
            logger.info("하이브리드 검색 자동 활성화됨 (auto_enable=true)")

        # 통계
        self.stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "retrieval_count": 0,
            "rerank_count": 0,
            "query_expansion_count": 0,
            "hybrid_search_count": 0,  # 🆕 하이브리드 검색 횟수
        }

        logger.info(
            "RetrievalOrchestrator 초기화",
            extra={
                "retriever": type(retriever).__name__,
                "reranker": type(reranker).__name__ if reranker else "None",
                "cache": type(cache).__name__ if cache else "None",
                "query_expansion": type(query_expansion).__name__ if query_expansion else "None",
                "graph_store": type(graph_store).__name__ if graph_store else "None",
                "hybrid_strategy": type(self._hybrid_strategy).__name__ if self._hybrid_strategy else "None",
                "scoring_service": self.scoring_service
            }
        )

    async def initialize(self) -> None:
        """오케스트레이터 및 모든 구성요소 초기화"""
        try:
            logger.info("RetrievalOrchestrator 초기화 시작...")

            # Retriever 초기화
            if hasattr(self.retriever, "initialize"):
                await self.retriever.initialize()
                logger.debug(
                    "Retriever 초기화 완료",
                    extra={"retriever": type(self.retriever).__name__}
                )

            # Reranker 초기화 (선택적)
            if self.reranker and hasattr(self.reranker, "initialize"):
                await self.reranker.initialize()
                logger.debug(
                    "Reranker 초기화 완료",
                    extra={"reranker": type(self.reranker).__name__}
                )

            # Cache 초기화 (선택적)
            if self.cache and hasattr(self.cache, "initialize"):
                await self.cache.initialize()
                logger.debug(
                    "Cache 초기화 완료",
                    extra={"cache": type(self.cache).__name__}
                )

            logger.info("RetrievalOrchestrator 초기화 완료")

        except Exception as e:
            logger.error(
                "RetrievalOrchestrator 초기화 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            raise

    async def close(self) -> None:
        """모든 구성요소 리소스 정리"""
        try:
            if hasattr(self.retriever, "close"):
                await self.retriever.close()

            if self.reranker and hasattr(self.reranker, "close"):
                await self.reranker.close()

            if self.cache and hasattr(self.cache, "close"):
                await self.cache.close()

            logger.info("RetrievalOrchestrator 종료 완료")

        except Exception as e:
            logger.error(
                "RetrievalOrchestrator 종료 실패",
                extra={"error": str(e)},
                exc_info=True
            )

    async def search_and_rerank(
        self,
        query: str,
        top_k: int = 15,
        filters: dict[str, Any] | None = None,
        rerank_enabled: bool = True,
        query_expansion_enabled: bool | None = None,  # None = 자동 판단
        use_graph: bool | None = None,  # 🆕 None = auto_enable 설정에 따라 자동 결정
    ) -> list[SearchResult]:
        """
        통합 검색 + 리랭킹 워크플로우 (Facade 메서드)

        기존 코드: retrieval_rerank.py의 search() + rerank() 조합

        워크플로우:
        1. 캐시 확인 (캐시 매니저가 있는 경우)
        2. 쿼리 확장 (Query Expansion 엔진이 있는 경우)
        3. 검색 실행:
           - use_graph=True && 하이브리드 전략 있음: 벡터+그래프 RRF 결합 검색
           - 그 외: 기존 벡터 검색
        4. 결과 병합 및 중복 제거
        5. 리랭킹 실행 (Reranker, 활성화된 경우)
        6. 캐시 저장 (캐시 매니저가 있는 경우)

        Args:
            query: 검색 쿼리
            top_k: 반환할 결과 수
            filters: 검색 필터 (메타데이터 등)
            rerank_enabled: 리랭킹 활성화 여부
            query_expansion_enabled: 쿼리 확장 활성화 여부
                - None: 자동 판단 (config 또는 쿼리 복잡도 기반)
                - True: 강제 활성화
                - False: 강제 비활성화
            use_graph: 그래프 검색 포함 여부
                - None: auto_enable 설정에 따라 자동 결정 (기본값)
                - True: 하이브리드 검색 (벡터+그래프 RRF) 강제 사용
                - False: 기존 벡터 검색만 강제 사용

        Returns:
            검색 및 리랭킹된 결과 리스트
        """
        self.stats["total_requests"] += 1

        # 🆕 use_graph 자동 결정
        # None이면 _auto_use_graph 설정값 사용, 명시적 값이면 그대로 사용
        effective_use_graph = use_graph if use_graph is not None else self._auto_use_graph

        cache_key = None  # 캐시 키 초기화

        try:
            # Step 1: 캐시 확인 (선택적)
            if self.cache:
                try:
                    cache_key = self.cache.generate_cache_key(query, top_k, filters)  # type: ignore[attr-defined]
                    cached_results = await self.cache.get(cache_key)

                    if cached_results:
                        self.stats["cache_hits"] += 1
                        logger.info(
                            f"캐시 히트: query='{query[:50]}...', results={len(cached_results)}"
                        )
                        return cached_results

                    self.stats["cache_misses"] += 1
                except Exception as e:
                    logger.warning(
                        f"캐시 조회 실패, 직접 검색으로 우회: {e}",
                        exc_info=True,
                        extra={"query": query[:100]}
                    )
                    # 캐시 실패 시 직접 검색 진행

            # Step 2: 쿼리 확장 (선택적)
            search_queries = [query]  # 기본값: 원본 쿼리만 사용
            expanded_query_obj = None

            if self.query_expansion:
                # 쿼리 확장 활성화 여부 판단
                should_expand = query_expansion_enabled

                if should_expand is None:
                    # 자동 판단: config 또는 쿼리 복잡도 기반
                    # config.yaml의 query_expansion.enabled 또는 multi_query.enable_query_expansion 사용
                    query_exp_config = self.config.get("query_expansion", {})
                    multi_query_config = self.config.get("multi_query", {})
                    should_expand = query_exp_config.get(
                        "enabled", multi_query_config.get("enable_query_expansion", True)
                    )

                if should_expand:
                    try:
                        logger.debug(
                            "쿼리 확장 시작",
                            extra={"query": query[:50]}
                        )
                        expanded_query_obj = await self.query_expansion.expand(query)
                        search_queries = expanded_query_obj.all_queries
                        self.stats["query_expansion_count"] += 1

                        logger.info(
                            "쿼리 확장 완료",
                            extra={
                                "query_count": len(search_queries),
                                "complexity": expanded_query_obj.complexity.value,
                                "intent": expanded_query_obj.intent.value
                            }
                        )
                    except Exception as e:
                        logger.warning(
                            "쿼리 확장 실패, 원본 쿼리 사용",
                            extra={"error": str(e)},
                            exc_info=True
                        )
                        search_queries = [query]

            # Step 3: 검색 실행 (하이브리드 또는 벡터 검색)
            # 🆕 하이브리드 검색: effective_use_graph=True && 하이브리드 전략 존재
            if effective_use_graph and self._hybrid_strategy is not None:
                logger.info(
                    "하이브리드 검색 시작",
                    extra={"query": query[:50], "top_k": top_k}
                )

                try:
                    # 하이브리드 검색 실행 (벡터 + 그래프 RRF 결합)
                    hybrid_result = await self._hybrid_strategy.search(
                        query=query,
                        top_k=top_k * 2,  # 리랭킹용 여유분
                    )
                    search_results = hybrid_result.documents
                    self.stats["hybrid_search_count"] += 1

                    logger.info(
                        "하이브리드 검색 완료",
                        extra={
                            "result_count": len(search_results),
                            "vector_count": hybrid_result.vector_count,
                            "graph_count": hybrid_result.graph_count
                        }
                    )
                except Exception as e:
                    logger.error(
                        f"하이브리드 검색 실패: {e}, 빈 결과 반환 (서비스 계속 동작)",
                        exc_info=True,
                        extra={"query": query[:100]}
                    )
                    # 하이브리드 검색 실패 시 빈 결과 반환 (서비스 중단 방지)
                    search_results = []

            # 기존 벡터 검색 (다중 쿼리 지원)
            else:
                logger.info(
                    "벡터 검색 시작",
                    extra={"query_count": len(search_queries), "top_k": top_k}
                )

                try:
                    if len(search_queries) == 1:
                        # 단일 쿼리: 기존 로직 유지
                        search_results = await self.retriever.search(query, top_k, filters)
                        self.stats["retrieval_count"] += 1
                    else:
                        # 다중 쿼리: 병렬 검색 및 결과 병합
                        search_results = await self._search_and_merge(search_queries, top_k, filters)
                        self.stats["retrieval_count"] += len(search_queries)

                    logger.info(
                        "벡터 검색 완료",
                        extra={"result_count": len(search_results)}
                    )
                except Exception as e:
                    logger.error(
                        f"벡터 검색 실패: {e}, 빈 결과 반환 (서비스 계속 동작)",
                        exc_info=True,
                        extra={"query": query[:100]}
                    )
                    # Retriever 실패 시 빈 결과 반환 (서비스 중단 방지)
                    search_results = []

            # Step 3: 리랭킹 실행 (선택적)
            final_results = search_results

            if rerank_enabled and self.reranker and search_results:
                logger.info(
                    "리랭킹 시작",
                    extra={"result_count": len(search_results)}
                )
                try:
                    reranked_results = await self.reranker.rerank(query, search_results, top_k)
                    self.stats["rerank_count"] += 1

                    if reranked_results:
                        final_results = reranked_results
                        logger.info(
                            "리랭킹 완료",
                            extra={"result_count": len(final_results)}
                        )
                    else:
                        logger.warning("리랭킹 결과 없음, 원본 검색 결과 사용")
                except Exception as e:
                    logger.error(
                        f"리랭킹 실패: {e}, 원본 검색 결과 사용",
                        exc_info=True,
                        extra={"query": query[:100]}
                    )
                    # 리랭킹 실패 시 원본 결과로 fallback

            # Step 4: 캐시 저장 (선택적)
            if self.cache and cache_key:
                try:
                    await self.cache.set(cache_key, final_results)
                    logger.debug(
                        "캐시 저장 완료",
                        extra={"result_count": len(final_results)}
                    )
                except Exception as e:
                    logger.warning(
                        f"캐시 저장 실패: {e}",
                        exc_info=True,
                        extra={"query": query[:100]}
                    )
                    # 캐시 저장 실패는 무시 (검색 결과는 정상 반환)

            logger.info(
                "search_and_rerank 완료",
                extra={
                    "query": query[:50],
                    "result_count": len(final_results),
                    "reranked": rerank_enabled and self.reranker is not None
                }
            )

            return final_results

        except Exception as e:
            logger.error(
                f"search_and_rerank 예상치 못한 에러: {e}, 빈 결과 반환",
                exc_info=True,
                extra={"query": query[:100]}
            )
            # 예상치 못한 에러 발생 시 빈 결과 반환 (서비스 중단 방지)
            return []

    async def _rerank_only(
        self,
        query: str,
        results: list[SearchResult],
        top_k: int = 15,
    ) -> list[SearchResult]:
        """
        리랭킹만 수행하는 내부 메서드 (검색 없음)

        Args:
            query: 검색 쿼리
            results: 검색 결과
            top_k: 반환할 결과 수

        Returns:
            리랭킹된 결과 리스트
        """
        if not self.reranker:
            logger.warning("Reranker가 설정되지 않았습니다. 원본 결과 반환")
            return results

        try:
            reranked = await self.reranker.rerank(query, results, top_k)
            self.stats["rerank_count"] += 1
            return reranked

        except Exception as e:
            logger.error(
                f"리랭킹 실패: {e}, 원본 결과 반환",
                exc_info=True,
                extra={"query": query[:100]}
            )
            return results

    async def health_check(self) -> HealthCheckDict:
        """
        모든 구성요소의 헬스 체크

        Returns:
            각 구성요소의 상태 딕셔너리
        """
        health: HealthCheckDict = {}

        try:
            # Retriever 헬스 체크
            if hasattr(self.retriever, "health_check"):
                health["retriever"] = await self.retriever.health_check()
            else:
                health["retriever"] = True

            # Reranker 헬스 체크
            if self.reranker:
                if hasattr(self.reranker, "health_check"):
                    health["reranker"] = await self.reranker.health_check()
                else:
                    health["reranker"] = True
            else:
                health["reranker"] = None  # Not configured

            # Cache 헬스 체크
            if self.cache:
                if hasattr(self.cache, "health_check"):
                    health["cache"] = await self.cache.health_check()
                else:
                    health["cache"] = True
            else:
                health["cache"] = None  # Not configured

        except Exception as e:
            logger.error(
                "헬스 체크 실패",
                extra={"error": str(e)},
                exc_info=True
            )
            health["error"] = str(e)

        return health

    def get_stats(self) -> OrchestratorStatsDict:  # type: ignore[return-value]
        """
        오케스트레이터 및 모든 구성요소의 통계 반환

        Returns:
            통합 통계 딕셔너리
        """
        stats = {
            "orchestrator": {
                "total_requests": self.stats["total_requests"],
                "cache_hits": self.stats["cache_hits"],
                "cache_misses": self.stats["cache_misses"],
                "retrieval_count": self.stats["retrieval_count"],
                "rerank_count": self.stats["rerank_count"],
                "query_expansion_count": self.stats["query_expansion_count"],
                "cache_hit_rate": (
                    self.stats["cache_hits"] / self.stats["total_requests"] * 100
                    if self.stats["total_requests"] > 0
                    else 0.0
                ),
            }
        }

        # Retriever 통계
        if hasattr(self.retriever, "get_stats"):
            stats["retriever"] = self.retriever.get_stats()

        # Reranker 통계
        if self.reranker and hasattr(self.reranker, "get_stats"):
            stats["reranker"] = self.reranker.get_stats()

        # Cache 통계
        if self.cache and hasattr(self.cache, "get_stats"):
            stats["cache"] = self.cache.get_stats()

        # Query Expansion 통계
        if self.query_expansion and hasattr(self.query_expansion, "get_stats"):
            stats["query_expansion"] = self.query_expansion.get_stats()

        return stats  # type: ignore[return-value]

    # ========================================
    # 레거시 호환성 어댑터 메서드 (Backward Compatibility)
    # ========================================

    async def search(self, query: str, options: dict[str, Any] | None = None) -> list[SearchResult]:
        """
        레거시 RetrievalModule.search() 호환 어댑터

        RAGPipeline에서 사용하는 인터페이스:
        retrieval_module.search(query, options)

        Args:
            query: 검색 쿼리
            options: 검색 옵션 딕셔너리
                - limit: 반환할 결과 수 (기본값: 15)
                - min_score: 최소 점수 임계값 (기본값: 0.5) - 현재 무시됨
                - context: 세션 컨텍스트 (선택적)

        Returns:
            검색된 Document 객체 리스트 (SearchResult 형식)

        Note:
            search_and_rerank()로 위임하되, 리랭킹은 비활성화
            (리랭킹은 별도 rerank() 메서드로 호출됨)
        """
        options = options or {}
        top_k = options.get("limit", 15)
        # min_score는 현재 Orchestrator에서 지원하지 않음 (향후 추가 가능)
        # context는 query_expansion에서 사용 가능

        logger.debug(
            "[Adapter] search() 호출",
            extra={"query": query[:50], "top_k": top_k}
        )

        # search_and_rerank() 호출 (리랭킹 비활성화)
        results = await self.search_and_rerank(
            query=query,
            top_k=top_k,
            rerank_enabled=False,  # 리랭킹은 별도 rerank() 메서드에서 수행
            query_expansion_enabled=self.config.get("query_expansion_enabled", True),
        )

        logger.debug(
            "[Adapter] search() 완료",
            extra={"result_count": len(results)}
        )
        return results

    async def rerank(
        self, query: str, results: list[SearchResult], top_n: int | None = None
    ) -> list[SearchResult]:
        """
        레거시 RetrievalModule.rerank() 호환 어댑터

        RAGPipeline에서 사용하는 인터페이스:
        retrieval_module.rerank(query, results, top_n)

        Args:
            query: 검색 쿼리
            results: 검색 결과 리스트
            top_n: 반환할 상위 N개 결과 (None이면 모든 결과 반환)

        Returns:
            리랭킹된 결과 리스트

        Note:
            _rerank_results() 내부 메서드로 위임
        """
        if not results:
            logger.debug("[Adapter] rerank() 호출: 결과 없음")
            return []

        logger.debug(
            "[Adapter] rerank() 호출",
            extra={
                "query": query[:50],
                "result_count": len(results),
                "top_n": top_n
            }
        )

        # 내부 리랭킹 메서드 호출
        reranked = await self._rerank_only(
            query=query, results=results, top_k=top_n if top_n else 15
        )

        logger.debug(
            "[Adapter] rerank() 완료",
            extra={"result_count": len(reranked)}
        )
        return reranked

    async def add_documents(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        """
        레거시 RetrievalModule.add_documents() 호환 어댑터

        upload.py에서 사용하는 인터페이스:
        retrieval_module.add_documents(embedded_chunks)

        Args:
            documents: 업로드할 문서 리스트
                각 문서는 다음 구조를 가져야 함:
                {
                    "content": str,           # 필수: 문서 내용
                    "embedding": list[float], # 필수: 임베딩 벡터
                    "metadata": dict,         # 선택: 메타데이터
                }

        Returns:
            업로드 결과 딕셔너리:
            {
                "success_count": int,
                "error_count": int,
                "total_count": int,
                "errors": list[str],
            }

        Note:
            WeaviateRetriever.add_documents()로 위임
        """
        if not hasattr(self.retriever, "add_documents"):
            raise NotImplementedError(
                f"Retriever {type(self.retriever).__name__}는 add_documents를 지원하지 않습니다."
            )

        logger.debug(
            "[Adapter] add_documents() 호출",
            extra={"document_count": len(documents)}
        )

        # WeaviateRetriever.add_documents()로 위임
        result = await self.retriever.add_documents(documents)  # type: ignore[no-any-return]

        logger.debug(
            f"[Adapter] add_documents() 완료: "
            f"성공 {result['success_count']}개, 실패 {result['error_count']}개"
        )

        return result  # type: ignore[no-any-return]

    # ========== 문서 관리 위임 메서드 ==========

    async def get_document_chunks(self, document_id: str) -> list[dict[str, Any]]:
        """
        문서의 모든 청크를 조회 (Retriever 위임)

        Args:
            document_id: 조회할 문서 ID

        Returns:
            청크 리스트 (각 청크는 id, content, metadata를 포함하는 dict)
        """
        if not hasattr(self.retriever, "get_document_chunks"):
            raise NotImplementedError(
                f"Retriever {type(self.retriever).__name__}는 "
                f"get_document_chunks를 지원하지 않습니다."
            )

        logger.debug(
            "[Adapter] get_document_chunks() 호출",
            extra={"document_id": document_id}
        )
        return await self.retriever.get_document_chunks(document_id)  # type: ignore[no-any-return]

    async def delete_document(self, document_id: str) -> bool:
        """
        문서와 관련된 모든 청크를 삭제 (Retriever 위임)

        Args:
            document_id: 삭제할 문서 ID

        Returns:
            삭제 성공 여부
        """
        if not hasattr(self.retriever, "delete_document"):
            raise NotImplementedError(
                f"Retriever {type(self.retriever).__name__}는 "
                f"delete_document를 지원하지 않습니다."
            )

        logger.debug(
            "[Adapter] delete_document() 호출",
            extra={"document_id": document_id}
        )
        result = await self.retriever.delete_document(document_id)

        logger.info(
            "[Adapter] delete_document() 완료",
            extra={"document_id": document_id, "success": result}
        )
        return result  # type: ignore[no-any-return]

    async def list_documents(
        self, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        """
        문서 목록 조회 (Retriever 위임)

        Args:
            page: 페이지 번호 (1부터 시작)
            page_size: 페이지 당 문서 수

        Returns:
            {"documents": [...], "total_count": int} 형식의 딕셔너리
        """
        if not hasattr(self.retriever, "list_documents"):
            raise NotImplementedError(
                f"Retriever {type(self.retriever).__name__}는 "
                f"list_documents를 지원하지 않습니다."
            )

        logger.debug(
            "[Adapter] list_documents() 호출",
            extra={"page": page, "page_size": page_size}
        )
        return await self.retriever.list_documents(page=page, page_size=page_size)  # type: ignore[no-any-return]

    async def get_document_details(
        self, document_id: str
    ) -> dict[str, Any] | None:
        """
        문서 상세 정보 조회 (Retriever 위임)

        Args:
            document_id: 조회할 문서 ID

        Returns:
            문서 상세 정보 딕셔너리 또는 None (미존재 시)
        """
        if not hasattr(self.retriever, "get_document_details"):
            raise NotImplementedError(
                f"Retriever {type(self.retriever).__name__}는 "
                f"get_document_details를 지원하지 않습니다."
            )

        logger.debug(
            "[Adapter] get_document_details() 호출",
            extra={"document_id": document_id}
        )
        return await self.retriever.get_document_details(document_id)  # type: ignore[no-any-return]

    async def get_document_stats(self) -> dict[str, Any]:
        """
        문서 통계 조회 (Retriever 위임)

        기존 get_stats()는 오케스트레이터 통계(캐시 히트율 등)를 반환합니다.
        이 메서드는 벡터 DB의 문서/벡터 수량 통계를 반환합니다.

        Returns:
            {"total_documents": int, "vector_count": int, ...} 형식의 딕셔너리
        """
        if not hasattr(self.retriever, "get_document_stats"):
            raise NotImplementedError(
                f"Retriever {type(self.retriever).__name__}는 "
                f"get_document_stats를 지원하지 않습니다."
            )

        logger.debug("[Adapter] get_document_stats() 호출")
        return await self.retriever.get_document_stats()  # type: ignore[no-any-return]

    async def get_collection_info(self) -> dict[str, Any]:
        """
        컬렉션 정보 조회 (Retriever 위임)

        Returns:
            {"size_mb": float, "oldest_document": str, "newest_document": str, ...}
        """
        if not hasattr(self.retriever, "get_collection_info"):
            raise NotImplementedError(
                f"Retriever {type(self.retriever).__name__}는 "
                f"get_collection_info를 지원하지 않습니다."
            )

        logger.debug("[Adapter] get_collection_info() 호출")
        return await self.retriever.get_collection_info()  # type: ignore[no-any-return]

    async def delete_all_documents(self) -> bool:
        """
        전체 문서 삭제 (Retriever 위임)

        Returns:
            삭제 성공 여부
        """
        if not hasattr(self.retriever, "delete_all_documents"):
            raise NotImplementedError(
                f"Retriever {type(self.retriever).__name__}는 "
                f"delete_all_documents를 지원하지 않습니다."
            )

        logger.warning("[Adapter] delete_all_documents() 호출 - 전체 문서 삭제 시작")
        result = await self.retriever.delete_all_documents()

        logger.warning(
            "[Adapter] delete_all_documents() 완료",
            extra={"success": result}
        )
        return result  # type: ignore[no-any-return]

    async def recreate_collection(self) -> bool:
        """
        컬렉션 재생성 (Retriever 위임)

        Returns:
            재생성 성공 여부
        """
        if not hasattr(self.retriever, "recreate_collection"):
            raise NotImplementedError(
                f"Retriever {type(self.retriever).__name__}는 "
                f"recreate_collection을 지원하지 않습니다."
            )

        logger.warning("[Adapter] recreate_collection() 호출 - 컬렉션 재생성 시작")
        result = await self.retriever.recreate_collection()

        logger.info(
            "[Adapter] recreate_collection() 완료",
            extra={"success": result}
        )
        return result  # type: ignore[no-any-return]

    async def backup_metadata(self) -> list[dict[str, Any]]:
        """
        문서 메타데이터 백업 (Retriever 위임)

        Returns:
            메타데이터 리스트
        """
        if not hasattr(self.retriever, "backup_metadata"):
            raise NotImplementedError(
                f"Retriever {type(self.retriever).__name__}는 "
                f"backup_metadata를 지원하지 않습니다."
            )

        logger.debug("[Adapter] backup_metadata() 호출")
        return await self.retriever.backup_metadata()  # type: ignore[no-any-return]

    # ========== 내부 헬퍼 메서드 ==========

    async def _search_and_merge(
        self,
        queries: list[str],
        top_k: int,
        filters: dict[str, Any] | None = None,
        weights: list[float] | None = None,
        use_rrf: bool = True,
    ) -> list[SearchResult]:
        """
        다중 쿼리 병렬 검색 및 RRF 기반 결과 병합

        **RRF (Reciprocal Rank Fusion) 알고리즘**:
        각 쿼리 결과에서 문서의 순위를 기반으로 점수를 계산하여 통합합니다.

        Score(doc) = Σ [weight_i / (k + rank_i)]
        - k: RRF 상수 (기본값 60)
        - rank_i: i번째 쿼리 결과에서의 순위 (0-based)
        - weight_i: i번째 쿼리의 가중치 (기본값 1.0)

        **장점**:
        - 다양한 쿼리 관점의 결과 통합
        - 여러 쿼리에서 공통으로 상위 랭크된 문서 우대
        - 개별 점수보다 순위 기반으로 공정한 통합

        **스코어링 (Scoring)**:
        ScoringService를 통해 설정 기반 가중치가 적용됩니다.
        - collection_weight_enabled: 컬렉션별 가중치
        - file_type_weight_enabled: 파일 타입별 가중치

        Args:
            queries: 검색할 쿼리 리스트
            top_k: 최종 반환할 결과 수
            filters: 검색 필터
            weights: 각 쿼리의 가중치 (기본값: 모두 1.0)
            use_rrf: RRF 사용 여부 (False면 단순 점수 병합)

        Returns:
            RRF 점수로 정렬된 검색 결과 리스트

        Example:
            queries = ["부산 주민등록 발급", "부산시 등본 신청", "주민등록 온라인"]
            weights = [1.0, 0.8, 0.6]
            results = await _search_and_merge(queries, 15, weights=weights)
        """
        import asyncio

        # 가중치 기본값 설정
        if weights is None:
            weights = [1.0] * len(queries)
        elif len(weights) != len(queries):
            logger.warning(
                f"쿼리 수({len(queries)})와 가중치 수({len(weights)}) 불일치, "
                f"가중치를 1.0으로 패딩"
            )
            weights = weights + [1.0] * (len(queries) - len(weights))

        # 모든 쿼리를 병렬로 검색 (각각 top_k*2개 검색)
        # top_k*2로 검색하는 이유: RRF 통합 시 더 많은 후보 확보
        search_top_k = top_k * 2
        search_tasks = [self.retriever.search(q, search_top_k, filters) for q in queries]

        logger.info(
            "Multi-Query 병렬 검색 시작",
            extra={
                "query_count": len(queries),
                "search_top_k": search_top_k,
                "rrf": "활성화" if use_rrf else "비활성화"
            }
        )

        start_time = asyncio.get_event_loop().time()
        results_per_query = await asyncio.gather(*search_tasks, return_exceptions=True)
        search_time = (asyncio.get_event_loop().time() - start_time) * 1000

        logger.info(
            "병렬 검색 완료",
            extra={"search_time_ms": search_time}
        )

        # RRF 또는 단순 병합
        if use_rrf:
            merged_results = self._rrf_merge(
                results_per_query, queries, weights, top_k
            )
        else:
            merged_results = self._simple_merge(results_per_query, queries, top_k)

        logger.info(
            "결과 병합 완료",
            extra={
                "merged_count": len(merged_results),
                "search_time_ms": search_time
            }
        )

        return merged_results

    def _rrf_merge(
        self,
        results_per_query: list[
            list[SearchResult] | BaseException
        ],  # asyncio.gather with return_exceptions=True
        queries: list[str],
        weights: list[float],
        top_k: int,
        rrf_k: int = 60,
    ) -> list[SearchResult]:
        """
        RRF (Reciprocal Rank Fusion) 알고리즘으로 결과 통합

        스코어링:
            ScoringService를 통해 설정 기반 가중치가 적용됩니다.
            - collection_weight_enabled: 컬렉션별 가중치
            - file_type_weight_enabled: 파일 타입별 가중치
            기본값은 모두 비활성화 (순수 RRF 점수 반환)

        Args:
            results_per_query: 각 쿼리의 검색 결과 리스트
            queries: 쿼리 리스트 (로깅용)
            weights: 각 쿼리의 가중치
            top_k: 최종 반환할 결과 수
            rrf_k: RRF 상수 (일반적으로 60)

        Returns:
            RRF 점수로 정렬된 결과 리스트
        """
        # 문서별 RRF 점수 계산
        doc_scores: dict[str, float] = {}  # {doc_id: rrf_score}
        doc_objects: dict[str, SearchResult] = {}  # {doc_id: SearchResult}
        doc_appearances: dict[str, int] = {}  # {doc_id: 등장 횟수}

        for query_idx, results in enumerate(results_per_query):
            if isinstance(results, BaseException):  # asyncio.gather with return_exceptions=True
                logger.warning(
                    "쿼리 실패",
                    extra={
                        "query_index": query_idx + 1,
                        "total_queries": len(queries),
                        "error": str(results)
                    },
                    exc_info=True
                )
                continue

            weight = weights[query_idx]

            for rank, result in enumerate(results):
                # 문서 ID 추출
                doc_id = self._get_doc_id(result)

                if not doc_id:
                    continue

                # RRF 점수 계산: weight / (k + rank)
                rrf_score = weight / (rrf_k + rank)

                # 점수 누적
                doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + rrf_score

                # 문서 객체 저장 (첫 등장 시)
                if doc_id not in doc_objects:
                    doc_objects[doc_id] = result

                # 등장 횟수 카운트
                doc_appearances[doc_id] = doc_appearances.get(doc_id, 0) + 1

        # 설정 기반 가중치 적용 (ScoringService 사용)
        # 기본값: 비활성화 → 순수 RRF 점수 반환 (Blank System 원칙)
        scoring_active = (
            self.scoring_service.collection_weight_enabled or
            self.scoring_service.file_type_weight_enabled
        )

        if scoring_active:
            logger.info(
                "ScoringService 가중치 적용 시작",
                extra={"document_count": len(doc_objects)}
            )
            weight_applied_count = 0

            for doc_id, result in doc_objects.items():
                original_score = doc_scores[doc_id]

                # 메타데이터에서 컬렉션과 파일타입 추출
                metadata = result.metadata or {}
                collection = metadata.get("_collection", "Documents")
                file_type = metadata.get("file_type", "")

                # ScoringService를 통한 가중치 적용
                adjusted_score = self.scoring_service.apply_weight(
                    score=original_score,
                    collection=collection,
                    file_type=file_type,
                )

                # 점수가 변경된 경우 메타데이터에 기록
                if adjusted_score != original_score:
                    result.metadata = metadata
                    result.metadata["_score_before_weight"] = original_score
                    weight_applied_count += 1

                doc_scores[doc_id] = adjusted_score

            logger.info(
                "가중치 적용 완료",
                extra={"weighted_documents": weight_applied_count}
            )

        # RRF 점수로 정렬 (가중치 적용 후)
        sorted_doc_ids = sorted(
            doc_scores.keys(), key=lambda doc_id: doc_scores[doc_id], reverse=True
        )

        # SearchResult 객체에 RRF 점수 적용
        merged_results = []
        for doc_id in sorted_doc_ids[:top_k]:
            result = doc_objects[doc_id]
            rrf_score = doc_scores[doc_id]

            # 원본 점수 유지하면서 RRF 점수 추가
            if hasattr(result, "score"):
                result.metadata = result.metadata or {}
                result.metadata["original_score"] = result.score
                result.metadata["rrf_score"] = rrf_score
                result.metadata["query_appearances"] = doc_appearances[doc_id]
                result.score = rrf_score  # RRF 점수로 교체
            elif isinstance(result, dict):
                result["metadata"] = result.get("metadata", {})
                result["metadata"]["original_score"] = result.get("score", 0.0)
                result["metadata"]["rrf_score"] = rrf_score
                result["metadata"]["query_appearances"] = doc_appearances[doc_id]
                result["score"] = rrf_score

            merged_results.append(result)

        if len(doc_appearances) > 0:
            avg_appearances = sum(doc_appearances.values()) / len(doc_appearances)
            logger.info(
                "RRF 병합 완료",
                extra={
                    "merged_count": len(merged_results),
                    "avg_appearances": avg_appearances
                }
            )
        else:
            logger.info(
                "RRF 병합 완료",
                extra={"merged_count": len(merged_results)}
            )

        # 상위 결과 로그 (디버깅용, 가중치 적용 시)
        if merged_results and scoring_active:
            top3 = merged_results[:3]
            top3_info = [
                {
                    "collection": r.metadata.get('_collection', 'unknown'),
                    "score": r.score
                }
                for r in top3
            ]
            logger.info(
                "상위 3개 결과",
                extra={"top_results": top3_info}
            )

        return merged_results

    def _simple_merge(
        self,
        results_per_query: list[
            list[SearchResult] | BaseException
        ],  # asyncio.gather with return_exceptions=True
        queries: list[str],
        top_k: int,
    ) -> list[SearchResult]:
        """
        단순 병합 (중복 제거 + 점수순 정렬)

        RRF를 사용하지 않는 경우의 폴백 로직
        """
        merged_results = []
        seen_ids = set()

        for i, results in enumerate(results_per_query):
            if isinstance(results, BaseException):  # asyncio.gather with return_exceptions=True
                logger.warning(
                    "쿼리 검색 실패",
                    extra={
                        "query_index": i + 1,
                        "total_queries": len(queries),
                        "error": str(results)
                    },
                    exc_info=True
                )
                continue

            for result in results:
                doc_id = self._get_doc_id(result)

                if doc_id and doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    merged_results.append(result)

        # 원본 점수 기준 정렬
        merged_results.sort(
            key=lambda x: getattr(x, "score", 0.0),  # SearchResult는 dataclass, .get() 불필요
            reverse=True,
        )

        return merged_results[:top_k]

    def _get_doc_id(self, result: SearchResult | dict) -> str | None:
        """
        SearchResult에서 문서 ID 추출

        Args:
            result: SearchResult 객체 또는 dict

        Returns:
            문서 ID 또는 None
        """
        if hasattr(result, "id"):
            return result.id
        elif isinstance(result, dict):
            return result.get("id")

        # ID가 없는 경우 content 기반 해시 생성
        if hasattr(result, "content"):
            return str(hash(result.content))
        elif isinstance(result, dict) and "content" in result:
            return str(hash(result["content"]))

        return None
