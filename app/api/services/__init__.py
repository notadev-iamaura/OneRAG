"""API Services - 비즈니스 로직 레이어."""

from importlib import import_module

__all__ = ["ChatService"]

_LAZY_EXPORTS = {
    "ChatService": ".chat_service",
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(_LAZY_EXPORTS[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
