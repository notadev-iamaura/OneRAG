"""Routing Module lazy compatibility exports."""

from importlib import import_module
from typing import Any

__all__ = [
    "LLMQueryRouter",
    "QueryProfile",
    "RoutingDecision",
    "RuleBasedRouter",
    "RuleMatch",
    "ComplexityCalculator",
    "ComplexityResult",
]

_EXPORTS = {
    "LLMQueryRouter": ("app.modules.core.routing.llm_query_router", "LLMQueryRouter"),
    "QueryProfile": ("app.modules.core.routing.llm_query_router", "QueryProfile"),
    "RoutingDecision": ("app.modules.core.routing.llm_query_router", "RoutingDecision"),
    "RuleBasedRouter": ("app.modules.core.routing.rule_based_router", "RuleBasedRouter"),
    "RuleMatch": ("app.modules.core.routing.rule_based_router", "RuleMatch"),
    "ComplexityCalculator": (
        "app.modules.core.routing.complexity_calculator",
        "ComplexityCalculator",
    ),
    "ComplexityResult": (
        "app.modules.core.routing.complexity_calculator",
        "ComplexityResult",
    ),
}


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        module_name, attr_name = _EXPORTS[name]
        module = import_module(module_name)
        return getattr(module, attr_name)
    raise AttributeError(f"module 'app.modules.core.routing' has no attribute {name!r}")
