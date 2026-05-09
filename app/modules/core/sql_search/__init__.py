"""SQL Search 모듈."""

from importlib import import_module
from typing import Any

__all__ = [
    # Service (통합)
    "SQLSearchService",
    "SQLSearchResult",
    "SingleQueryResult",  # 멀티 쿼리 개별 결과
    # Generator
    "SQLGenerator",
    "SQLGenerationResult",
    "SingleSQLQuery",  # 멀티 쿼리 단일 쿼리 정보
    # Executor
    "QueryExecutor",
    "QueryResult",
    # Formatter
    "ResultFormatter",
]

_LAZY_EXPORTS = {
    "SQLSearchService": ".service",
    "SQLSearchResult": ".service",
    "SingleQueryResult": ".service",
    "SQLGenerator": ".sql_generator",
    "SQLGenerationResult": ".sql_generator",
    "SingleSQLQuery": ".sql_generator",
    "QueryExecutor": ".query_executor",
    "QueryResult": ".query_executor",
    "ResultFormatter": ".result_formatter",
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(_LAZY_EXPORTS[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
