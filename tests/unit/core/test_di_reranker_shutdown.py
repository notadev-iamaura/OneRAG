"""An async DI singleton must release its owned client even if retrieval close fails."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.core.di_container import cleanup_resources
from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator
from app.modules.core.retrieval.rerankers.jev_decision_reranker import JevDecisionReranker


@pytest.mark.asyncio
@pytest.mark.parametrize("owned", [True, False])
@pytest.mark.parametrize("retriever_fails", [True, False])
async def test_future_reranker_close_honors_ownership(owned, retriever_fails):
    client = Mock(aclose=AsyncMock())
    with patch("app.modules.core.retrieval.rerankers.jev_decision_reranker.TypeSafeJevClient", return_value=client):
        reranker = JevDecisionReranker(api_key="test-key", mode="enforce",
                                      **({} if owned else {"client": client}))
    retriever = Mock(close=AsyncMock(side_effect=RuntimeError("close failed") if retriever_fails else None))
    # Exercise the actual close implementation without unrelated constructor dependencies.
    retrieval = object.__new__(RetrievalOrchestrator)
    retrieval.retriever, retrieval.reranker, retrieval.cache = retriever, reranker, None
    future = asyncio.get_running_loop().create_future()
    future.set_result(reranker)
    container = SimpleNamespace(
        session=lambda: None, document_processor=lambda: None, graph_store=lambda: None,
        retrieval_orchestrator=lambda: retrieval, reranker=lambda: future,
        vector_store=lambda: None, metadata_store=lambda: None, generation=lambda: None,
        config=SimpleNamespace(self_rag=SimpleNamespace(precheck=SimpleNamespace(mode=lambda: "off"))),
    )
    await cleanup_resources(container)
    retriever.close.assert_awaited_once()
    assert reranker._closed
    assert client.aclose.await_count == (1 if owned else 0)
