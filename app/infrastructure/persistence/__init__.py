"""데이터베이스 패키지 초기화."""

from importlib import import_module

__all__ = [
    "Base",
    "db_manager",
    "get_db",
    "EvaluationModel",
    "EvaluationStatisticsCache",
    "EvaluationDataManager",
    "DuplicateEvaluationError",
]

_LAZY_EXPORTS = {
    "Base": ".connection",
    "db_manager": ".connection",
    "get_db": ".connection",
    "EvaluationModel": ".models",
    "EvaluationStatisticsCache": ".models",
    "EvaluationDataManager": ".evaluation_manager",
    "DuplicateEvaluationError": ".evaluation_manager",
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(_LAZY_EXPORTS[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
