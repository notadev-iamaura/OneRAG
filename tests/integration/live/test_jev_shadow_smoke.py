"""Key-gated TypeSafe shadow and precheck API smoke tests."""

import os

import pytest

from app.modules.core.decision import JevDecisionProvider
from app.modules.core.retrieval.interfaces import SearchResult
from app.modules.core.retrieval.rerankers.jev_decision_reranker import JevDecisionReranker

pytestmark = [pytest.mark.integration, pytest.mark.e2e]

_API_KEY = os.getenv("TYPESAFE_API_KEY", "")
if not _API_KEY.strip():
    pytest.skip("TYPESAFE_API_KEY not set", allow_module_level=True)


@pytest.mark.asyncio
async def test_shadow_records_live_decisions_without_mutating_results() -> None:
    incoming = [
        SearchResult("0", "서울은 대한민국의 수도입니다.", 0.9, {"source": "synthetic"}),
        SearchResult("1", "Seoul is the capital of South Korea.", 0.8, {"source": "synthetic"}),
        SearchResult("2", "The moon orbits Earth.", 0.7, {"source": "synthetic"}),
    ]
    reranker = JevDecisionReranker(_API_KEY, mode="shadow", shadow_background=False)
    try:
        output = await reranker.rerank("What is the capital of South Korea?", incoming)
        assert output is incoming
        batches = reranker.get_recent_decisions()
        assert len(batches) == 1
        assert any(
            decision.status == "ok"
            and decision.probability is not None
            and 0 <= decision.probability <= 1
            for decision in batches[0].decisions
        )
    finally:
        await reranker.close()


@pytest.mark.asyncio
async def test_precheck_provider_returns_live_probability() -> None:
    provider = JevDecisionProvider()
    try:
        result = await provider.noul(
            instructions="Is the answer supported by the context?",
            state={
                "query": "What is the capital of South Korea?",
                "context": "서울은 대한민국의 수도입니다.",
                "answer": "Seoul.",
            },
            timeout_s=5.0,
        )
        assert result.status == "ok"
        assert result.probability is not None and 0 <= result.probability <= 1
    finally:
        await provider.aclose()
