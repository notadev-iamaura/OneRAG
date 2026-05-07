"""Modules package initialization.

The package historically re-exported many core classes. Keep those exports lazy so
importing one submodule does not initialize the entire RAG stack.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "DocumentProcessor",
    "SearchResult",
    "GenerationModule",
    "GenerationResult",
    "EnhancedSessionModule",
    "GeminiEmbeddings",
    "GPT5QueryExpansionEngine",
    "ExpandedQuery",
    "LLMQueryRouter",
    "QueryProfile",
    "RoutingDecision",
    "ComplexityCalculator",
    "ComplexityResult",
    "SelfRAGOrchestrator",
    "SelfRAGResult",
    "PromptManager",
    "RuleBasedRouter",
    "RuleMatch",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        core = import_module("app.modules.core")
        return getattr(core, name)
    raise AttributeError(f"module 'app.modules' has no attribute {name!r}")
