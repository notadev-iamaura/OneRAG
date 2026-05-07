"""Core RAG pipeline modules with lazy compatibility exports."""

from importlib import import_module
from typing import Any

__all__ = [
    "DocumentProcessor",
    "GeminiEmbeddings",
    "GeminiEmbedder",
    "SearchResult",
    "QueryExpansionEngine",
    "GPT5QueryExpansionEngine",
    "ExpandedQuery",
    "QueryComplexity",
    "SearchIntent",
    "RetrievalOrchestrator",
    "LLMQueryRouter",
    "QueryProfile",
    "RoutingDecision",
    "ComplexityCalculator",
    "ComplexityResult",
    "SelfRAGOrchestrator",
    "SelfRAGResult",
    "GenerationModule",
    "GenerationResult",
    "PromptManager",
    "EnhancedSessionModule",
    "RuleBasedRouter",
    "RuleMatch",
]

_EXPORTS = {
    "DocumentProcessor": ("app.modules.core.documents", "DocumentProcessor"),
    "GeminiEmbeddings": ("app.modules.core.embedding", "GeminiEmbeddings"),
    "GeminiEmbedder": ("app.modules.core.embedding", "GeminiEmbedder"),
    "SearchResult": ("app.modules.core.retrieval.interfaces", "SearchResult"),
    "QueryExpansionEngine": (
        "app.modules.core.retrieval.query_expansion",
        "IQueryExpansionEngine",
    ),
    "GPT5QueryExpansionEngine": (
        "app.modules.core.retrieval.query_expansion",
        "GPT5QueryExpansionEngine",
    ),
    "ExpandedQuery": ("app.modules.core.retrieval.query_expansion", "ExpandedQuery"),
    "QueryComplexity": (
        "app.modules.core.retrieval.query_expansion.interface",
        "QueryComplexity",
    ),
    "SearchIntent": ("app.modules.core.retrieval.query_expansion.interface", "SearchIntent"),
    "RetrievalOrchestrator": (
        "app.modules.core.retrieval.orchestrator",
        "RetrievalOrchestrator",
    ),
    "LLMQueryRouter": ("app.modules.core.routing", "LLMQueryRouter"),
    "QueryProfile": ("app.modules.core.routing", "QueryProfile"),
    "RoutingDecision": ("app.modules.core.routing", "RoutingDecision"),
    "ComplexityCalculator": ("app.modules.core.routing", "ComplexityCalculator"),
    "ComplexityResult": ("app.modules.core.routing", "ComplexityResult"),
    "SelfRAGOrchestrator": ("app.modules.core.self_rag", "SelfRAGOrchestrator"),
    "SelfRAGResult": ("app.modules.core.self_rag", "SelfRAGResult"),
    "GenerationModule": ("app.modules.core.generation", "GenerationModule"),
    "GenerationResult": ("app.modules.core.generation", "GenerationResult"),
    "PromptManager": ("app.modules.core.generation", "PromptManager"),
    "EnhancedSessionModule": ("app.modules.core.session", "EnhancedSessionModule"),
    "RuleBasedRouter": ("app.modules.core.routing", "RuleBasedRouter"),
    "RuleMatch": ("app.modules.core.routing", "RuleMatch"),
}


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        module_name, attr_name = _EXPORTS[name]
        module = import_module(module_name)
        return getattr(module, attr_name)
    raise AttributeError(f"module 'app.modules.core' has no attribute {name!r}")
