"""리랭크 모드 해석기 호환 모듈.

실제 구현은 app.lib.rerank_mode 로 이동했다(설정 스키마가 도메인 모듈에 의존하던 계층 위반 제거).
기존 import 경로와 `python -m app.modules.core.retrieval.rerankers.mode` CLI 는 그대로 동작한다.
"""

from __future__ import annotations

from app.lib.rerank_mode import (
    Effective,
    RerankerModeConfigError,
    RerankMode,
    ResolvedRerankMode,
    Source,
    _require_typesafe_key,
    main,
    normalize_mode_value,
    preflight_rerank_mode,
    resolve_rerank_mode,
)

__all__ = [
    "Effective",
    "RerankMode",
    "RerankerModeConfigError",
    "ResolvedRerankMode",
    "Source",
    "_require_typesafe_key",
    "main",
    "normalize_mode_value",
    "preflight_rerank_mode",
    "resolve_rerank_mode",
]

if __name__ == "__main__":
    raise SystemExit(main())
