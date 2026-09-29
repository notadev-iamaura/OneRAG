"""Bounded fallbacks and cache isolation at the retrieval boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.core.retrieval.interfaces import SearchResult
from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator


def documents():
    return [SearchResult(str(i), f"passage {i}", 0.9, {}) for i in range(6)]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "jev"])
@pytest.mark.parametrize("failure", ["exception", "empty"])
async def test_search_fallback_is_bounded(mode, failure):
    incoming = documents()
    reranker = SimpleNamespace(
        name="jev-decision" if mode == "jev" else "legacy", model="test",
        rerank=AsyncMock(return_value=[]),
    )
    if failure == "exception":
        reranker.rerank.side_effect = RuntimeError("unavailable")
    orchestrator = RetrievalOrchestrator(AsyncMock(search=AsyncMock(return_value=incoming)), reranker)
    output = await orchestrator.search_and_rerank("q", top_k=2)
    assert [doc.id for doc in output] == [doc.id for doc in incoming[:2]]
    if mode == "jev":
        assert all(doc.metadata["jev_outcome"] == "fallback" for doc in output)
        assert all(doc.metadata == {} for doc in incoming)
    else:
        assert output == incoming[:2]


@pytest.mark.asyncio
@pytest.mark.parametrize("top_n", [None, 0, 2])
async def test_adapter_exception_respects_limit(top_n):
    incoming = documents()
    reranker = AsyncMock(rerank=AsyncMock(side_effect=RuntimeError("unavailable")))
    orchestrator = RetrievalOrchestrator(AsyncMock(), reranker)
    assert await orchestrator.rerank("q", incoming, top_n) == incoming[:top_n]
    if top_n == 0:
        reranker.rerank.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_rerank_only_stays_empty():
    orchestrator = RetrievalOrchestrator(AsyncMock(), AsyncMock(rerank=AsyncMock(return_value=[])))
    assert await orchestrator._rerank_only("q", documents(), 2) == []


@pytest.mark.asyncio
async def test_zero_and_negative_limits():
    retriever = AsyncMock()
    orchestrator = RetrievalOrchestrator(retriever)
    assert await orchestrator.search_and_rerank("q", top_k=0) == []
    retriever.search.assert_not_awaited()
    with pytest.raises(ValueError):
        await orchestrator.search_and_rerank("q", top_k=-1)
    with pytest.raises(ValueError):
        await orchestrator._rerank_only("q", [], -1)
    with pytest.raises(ValueError):
        await orchestrator.rerank("q", [], -1)


@pytest.mark.asyncio
async def test_shared_cache_separates_modes():
    class Cache:
        def __init__(self):
            self.values = {}

        def generate_cache_key(self, query, top_k, filters):
            return (query, top_k, tuple(sorted(filters.items())))

        async def get(self, key):
            return self.values.get(key)

        async def set(self, key, value):
            self.values[key] = value

    incoming = documents()
    cache = Cache()
    retriever = AsyncMock(search=AsyncMock(return_value=incoming))
    legacy = RetrievalOrchestrator(
        retriever, SimpleNamespace(rerank=AsyncMock(return_value=incoming[:2])), cache
    )
    jev = RetrievalOrchestrator(
        retriever, SimpleNamespace(name="jev-decision", model="test",
                                   rerank=AsyncMock(return_value=incoming[2:4])), cache
    )
    assert await legacy.search_and_rerank("q", 2) == incoming[:2]
    assert await jev.search_and_rerank("q", 2) == incoming[2:4]
    assert await legacy.search_and_rerank("q", 2) == incoming[:2]
    assert retriever.search.await_count == 2
    assert len(cache.values) == 2


@pytest.mark.asyncio
async def test_close_failure_does_not_skip_other_components():
    retriever = AsyncMock(close=AsyncMock(side_effect=RuntimeError("retriever")))
    reranker = AsyncMock(close=AsyncMock(side_effect=RuntimeError("reranker")))
    cache = AsyncMock()
    await RetrievalOrchestrator(retriever, reranker, cache).close()
    reranker.close.assert_awaited_once()
    cache.close.assert_awaited_once()
