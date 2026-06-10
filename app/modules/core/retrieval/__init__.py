"""Retrieval Module lazy compatibility exports."""

from importlib import import_module
from typing import Any

__all__ = [
    "IRetriever",
    "IReranker",
    "ICacheManager",
    "BaseRetriever",
    "BaseReranker",
    "BaseCacheManager",
    "SearchResult",
    "MemoryCacheManager",
    "JinaReranker",
    "OpenAILLMReranker",
    "GeminiFlashReranker",
    "RetrievalOrchestrator",
    "ExpandedQuery",
    "IQueryExpansionEngine",
    "QueryComplexity",
    "SearchIntent",
]

_EXPORTS = {
    "IRetriever": ("app.modules.core.retrieval.interfaces", "IRetriever"),
    "IReranker": ("app.modules.core.retrieval.interfaces", "IReranker"),
    "ICacheManager": ("app.modules.core.retrieval.interfaces", "ICacheManager"),
    "BaseRetriever": ("app.modules.core.retrieval.interfaces", "BaseRetriever"),
    "BaseReranker": ("app.modules.core.retrieval.interfaces", "BaseReranker"),
    "BaseCacheManager": ("app.modules.core.retrieval.interfaces", "BaseCacheManager"),
    "SearchResult": ("app.modules.core.retrieval.interfaces", "SearchResult"),
    "MemoryCacheManager": (
        "app.modules.core.retrieval.cache.memory_cache",
        "MemoryCacheManager",
    ),
    "JinaReranker": ("app.modules.core.retrieval.rerankers.jina_reranker", "JinaReranker"),
    "OpenAILLMReranker": (
        "app.modules.core.retrieval.rerankers.openai_llm_reranker",
        "OpenAILLMReranker",
    ),
    "GeminiFlashReranker": (
        "app.modules.core.retrieval.rerankers.gemini_reranker",
        "GeminiFlashReranker",
    ),
    "RetrievalOrchestrator": (
        "app.modules.core.retrieval.orchestrator",
        "RetrievalOrchestrator",
    ),
    "ExpandedQuery": (
        "app.modules.core.retrieval.query_expansion.interface",
        "ExpandedQuery",
    ),
    "IQueryExpansionEngine": (
        "app.modules.core.retrieval.query_expansion.interface",
        "IQueryExpansionEngine",
    ),
    "QueryComplexity": (
        "app.modules.core.retrieval.query_expansion.interface",
        "QueryComplexity",
    ),
    "SearchIntent": (
        "app.modules.core.retrieval.query_expansion.interface",
        "SearchIntent",
    ),
}


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        module_name, attr_name = _EXPORTS[name]
        module = import_module(module_name)
        return getattr(module, attr_name)
    raise AttributeError(f"module 'app.modules.core.retrieval' has no attribute {name!r}")
