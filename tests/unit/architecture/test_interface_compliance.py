"""
인터페이스 일관성 검증 테스트

Phase 3 R3.2: retrieval/interfaces.py 인터페이스 일관성 검증
TDD - 구현체가 Protocol/ABC를 준수하는지 확인
"""

import inspect


class TestRerankerInterfaceCompliance:
    """모든 Reranker 구현체가 IReranker Protocol을 준수하는지 검증"""

    def test_all_rerankers_have_rerank_method(self) -> None:
        """모든 리랭커가 rerank 메서드를 가져야 함"""
        from app.modules.core.retrieval.rerankers import (
            GeminiFlashReranker,
            JinaColBERTReranker,
            JinaReranker,
            OpenAILLMReranker,
        )

        rerankers = [
            JinaReranker,
            JinaColBERTReranker,
            OpenAILLMReranker,
            GeminiFlashReranker,
        ]

        for reranker_cls in rerankers:
            assert hasattr(reranker_cls, "rerank"), (
                f"{reranker_cls.__name__}에 rerank 메서드 없음"
            )

            # 시그니처 검증
            rerank_method = reranker_cls.rerank
            sig = inspect.signature(rerank_method)
            params = list(sig.parameters.keys())

            assert "query" in params, f"{reranker_cls.__name__}.rerank에 query 파라미터 없음"
            assert "results" in params, (
                f"{reranker_cls.__name__}.rerank에 results 파라미터 없음"
            )

    def test_all_rerankers_have_supports_caching(self) -> None:
        """모든 리랭커가 supports_caching 메서드를 가져야 함"""
        from app.modules.core.retrieval.rerankers import (
            GeminiFlashReranker,
            JinaColBERTReranker,
            JinaReranker,
            OpenAILLMReranker,
        )

        rerankers = [
            JinaReranker,
            JinaColBERTReranker,
            OpenAILLMReranker,
            GeminiFlashReranker,
        ]

        for reranker_cls in rerankers:
            assert hasattr(reranker_cls, "supports_caching"), (
                f"{reranker_cls.__name__}에 supports_caching 메서드 없음"
            )

    def test_reranker_protocol_compliance(self) -> None:
        """리랭커가 IReranker Protocol을 구조적으로 만족"""
        from app.modules.core.retrieval.rerankers import JinaReranker

        # JinaReranker가 IReranker Protocol 시그니처 만족 확인
        # (인스턴스 생성 없이 클래스 레벨 검사)
        assert callable(getattr(JinaReranker, "rerank", None))
        assert callable(getattr(JinaReranker, "supports_caching", None))


class TestRetrieverInterfaceCompliance:
    """모든 Retriever 구현체가 IRetriever Protocol을 준수하는지 검증"""

    def test_retriever_has_search_method(self) -> None:
        """Retriever가 search 메서드를 가져야 함"""
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        assert hasattr(WeaviateRetriever, "search"), (
            "WeaviateRetriever에 search 메서드 없음"
        )

        sig = inspect.signature(WeaviateRetriever.search)
        params = list(sig.parameters.keys())

        assert "query" in params
        assert "top_k" in params

    def test_retriever_has_health_check(self) -> None:
        """Retriever가 health_check 메서드를 가져야 함"""
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        assert hasattr(WeaviateRetriever, "health_check"), (
            "WeaviateRetriever에 health_check 메서드 없음"
        )


class TestCacheManagerInterfaceCompliance:
    """모든 CacheManager 구현체가 ICacheManager Protocol을 준수하는지 검증"""

    def test_all_cache_managers_have_required_methods(self) -> None:
        """모든 캐시 매니저가 필수 메서드를 가져야 함"""
        from app.modules.core.retrieval.cache import (
            InMemorySemanticCache,
            MemoryCacheManager,
        )

        cache_managers = [MemoryCacheManager, InMemorySemanticCache]
        required_methods = ["get", "set", "invalidate", "clear", "get_stats"]

        for cache_cls in cache_managers:
            for method_name in required_methods:
                assert hasattr(cache_cls, method_name), (
                    f"{cache_cls.__name__}에 {method_name} 메서드 없음"
                )


class TestSearchResultDataclass:
    """SearchResult 데이터 클래스 검증"""

    def test_search_result_has_required_fields(self) -> None:
        """SearchResult가 필수 필드를 가져야 함"""
        from app.modules.core.retrieval.interfaces import SearchResult

        result = SearchResult(
            id="test-id",
            content="테스트 내용",
            score=0.95,
            metadata={"source": "test"},
        )

        assert result.id == "test-id"
        assert result.content == "테스트 내용"
        assert result.score == 0.95
        assert result.metadata == {"source": "test"}

    def test_search_result_metadata_as_attributes(self) -> None:
        """SearchResult 메타데이터가 속성으로 접근 가능해야 함"""
        from app.modules.core.retrieval.interfaces import SearchResult

        result = SearchResult(
            id="test-id",
            content="테스트",
            score=0.9,
            metadata={"source": "structured", "page_id": "abc123"},
        )

        # 메타데이터가 속성으로 접근 가능
        assert result.source == "structured"
        assert result.page_id == "abc123"


class TestProtocolVsABCConsistency:
    """Protocol과 ABC가 동일한 인터페이스를 정의하는지 검증"""

    def test_retriever_protocol_matches_abc(self) -> None:
        """IRetriever Protocol과 BaseRetriever ABC가 동일한 메서드 정의"""
        from app.modules.core.retrieval.interfaces import BaseRetriever, IRetriever

        protocol_methods = {
            name
            for name, _ in inspect.getmembers(IRetriever, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        abc_methods = {
            name
            for name, _ in inspect.getmembers(BaseRetriever, predicate=inspect.isfunction)
            if not name.startswith("_")
        }

        # Protocol의 메서드가 ABC에도 있어야 함
        assert protocol_methods == abc_methods, (
            f"Protocol과 ABC 불일치: Protocol={protocol_methods}, ABC={abc_methods}"
        )

    def test_reranker_protocol_matches_abc(self) -> None:
        """IReranker Protocol과 BaseReranker ABC가 동일한 메서드 정의"""
        from app.modules.core.retrieval.interfaces import BaseReranker, IReranker

        protocol_methods = {
            name
            for name, _ in inspect.getmembers(IReranker, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        abc_methods = {
            name
            for name, _ in inspect.getmembers(BaseReranker, predicate=inspect.isfunction)
            if not name.startswith("_")
        }

        assert protocol_methods == abc_methods, (
            f"Protocol과 ABC 불일치: Protocol={protocol_methods}, ABC={abc_methods}"
        )

    def test_cache_manager_protocol_matches_abc(self) -> None:
        """ICacheManager Protocol과 BaseCacheManager ABC가 동일한 메서드 정의"""
        from app.modules.core.retrieval.interfaces import BaseCacheManager, ICacheManager

        protocol_methods = {
            name
            for name, _ in inspect.getmembers(ICacheManager, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        abc_methods = {
            name
            for name, _ in inspect.getmembers(
                BaseCacheManager, predicate=inspect.isfunction
            )
            if not name.startswith("_")
        }

        assert protocol_methods == abc_methods, (
            f"Protocol과 ABC 불일치: Protocol={protocol_methods}, ABC={abc_methods}"
        )
