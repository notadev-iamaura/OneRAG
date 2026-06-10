"""
검색 캐시 키 파라미터 구분 테스트 (Phase 5.4)

목적:
    캐시 키가 rerank_enabled/use_graph 설정을 구분해, 리랭킹 여부나 그래프
    사용 여부가 다른 호출이 같은 캐시 항목을 공유하지 않도록 보장한다.
"""

from __future__ import annotations

import inspect

from app.modules.core.retrieval.cache.memory_cache import MemoryCacheManager


def test_cache_key_differs_by_rerank_flag() -> None:
    """rerank 플래그가 다르면 캐시 키가 달라야 한다."""
    key_true = MemoryCacheManager.generate_cache_key("q", 5, {"_rerank_enabled": True})
    key_false = MemoryCacheManager.generate_cache_key(
        "q", 5, {"_rerank_enabled": False}
    )
    assert key_true != key_false


def test_cache_key_differs_by_use_graph_flag() -> None:
    """use_graph 플래그가 다르면 캐시 키가 달라야 한다."""
    key_g = MemoryCacheManager.generate_cache_key("q", 5, {"_use_graph": True})
    key_v = MemoryCacheManager.generate_cache_key("q", 5, {"_use_graph": False})
    assert key_g != key_v


def test_orchestrator_includes_flags_in_cache_key() -> None:
    """orchestrator가 캐시 키에 rerank/graph 플래그를 포함해야 한다."""
    from app.modules.core.retrieval import orchestrator

    source = inspect.getsource(orchestrator)
    assert '"_rerank_enabled"' in source
    assert '"_use_graph"' in source
