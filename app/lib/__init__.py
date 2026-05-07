"""Library package initialization.

Keep this package import lightweight. Submodules such as ``app.lib.errors`` are used
throughout tests and request paths; eagerly importing config validation and LangSmith
clients here makes unrelated imports pay a large startup cost.
"""

from typing import Any

__all__ = [
    "ConfigLoader",
    "load_config",
    "get_logger",
    "create_chat_logging_middleware",
    "LangSmithSDKClient",
    "QueryLogSDK",
    # 'IPGeolocationModule',  # 비활성화: 세션 생성 타임아웃 원인
]


def __getattr__(name: str) -> Any:
    """Lazily expose historical app.lib exports without eager side effects."""
    if name in {"ConfigLoader", "load_config"}:
        from .config_loader import ConfigLoader, load_config

        exports = {
            "ConfigLoader": ConfigLoader,
            "load_config": load_config,
        }
        return exports[name]

    if name in {"LangSmithSDKClient", "QueryLogSDK"}:
        from .langsmith_client import LangSmithSDKClient, QueryLogSDK

        exports = {
            "LangSmithSDKClient": LangSmithSDKClient,
            "QueryLogSDK": QueryLogSDK,
        }
        return exports[name]

    if name in {"create_chat_logging_middleware", "get_logger"}:
        from .logger import create_chat_logging_middleware, get_logger

        exports = {
            "create_chat_logging_middleware": create_chat_logging_middleware,
            "get_logger": get_logger,
        }
        return exports[name]

    raise AttributeError(f"module 'app.lib' has no attribute {name!r}")
