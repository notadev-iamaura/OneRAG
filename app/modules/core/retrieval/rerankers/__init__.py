"""
Reranker Module lazy compatibility exports.

Keep package import cheap. Some optional rerankers import heavyweight model
runtime packages, so concrete implementations are loaded only when requested.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "IReranker",
    "JinaReranker",
    "JinaColBERTReranker",
    "ColBERTRerankerConfig",
    "CohereReranker",
    "OpenAILLMReranker",
    "GeminiFlashReranker",
    "OpenRouterReranker",
    "RerankerChain",
    "RerankerChainConfig",
    "RerankerFactory",
    "RerankerFactoryV2",
    "SUPPORTED_RERANKERS",
    "LocalReranker",
]

_EXPORTS = {
    "IReranker": ("app.modules.core.retrieval.interfaces", "IReranker"),
    "JinaReranker": ("app.modules.core.retrieval.rerankers.jina_reranker", "JinaReranker"),
    "JinaColBERTReranker": (
        "app.modules.core.retrieval.rerankers.colbert_reranker",
        "JinaColBERTReranker",
    ),
    "ColBERTRerankerConfig": (
        "app.modules.core.retrieval.rerankers.colbert_reranker",
        "ColBERTRerankerConfig",
    ),
    "CohereReranker": (
        "app.modules.core.retrieval.rerankers.cohere_reranker",
        "CohereReranker",
    ),
    "OpenAILLMReranker": (
        "app.modules.core.retrieval.rerankers.openai_llm_reranker",
        "OpenAILLMReranker",
    ),
    "GeminiFlashReranker": (
        "app.modules.core.retrieval.rerankers.gemini_reranker",
        "GeminiFlashReranker",
    ),
    "OpenRouterReranker": (
        "app.modules.core.retrieval.rerankers.openrouter_reranker",
        "OpenRouterReranker",
    ),
    "RerankerChain": (
        "app.modules.core.retrieval.rerankers.reranker_chain",
        "RerankerChain",
    ),
    "RerankerChainConfig": (
        "app.modules.core.retrieval.rerankers.reranker_chain",
        "RerankerChainConfig",
    ),
    "RerankerFactory": ("app.modules.core.retrieval.rerankers.factory", "RerankerFactory"),
    "RerankerFactoryV2": ("app.modules.core.retrieval.rerankers.factory", "RerankerFactoryV2"),
    "SUPPORTED_RERANKERS": (
        "app.modules.core.retrieval.rerankers.factory",
        "SUPPORTED_RERANKERS",
    ),
    "LocalReranker": (
        "app.modules.core.retrieval.rerankers.local_reranker",
        "LocalReranker",
    ),
}


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        module_name, attr_name = _EXPORTS[name]
        module = import_module(module_name)
        return getattr(module, attr_name)
    raise AttributeError(f"module 'app.modules.core.retrieval.rerankers' has no attribute {name!r}")
