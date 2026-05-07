"""API package initialization with lazy router exports."""

from importlib import import_module
from types import ModuleType

__all__ = ["chat", "upload", "admin", "health", "prompts"]


def __getattr__(name: str) -> ModuleType:
    if name in __all__:
        return import_module(f"app.api.{name}")
    raise AttributeError(f"module 'app.api' has no attribute {name!r}")
