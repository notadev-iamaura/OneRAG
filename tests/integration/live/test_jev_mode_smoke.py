"""Opt-in factory smoke; only synthetic passages are sent to TypeSafe."""

import os

import pytest

from app.modules.core.retrieval.interfaces import SearchResult
from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2
from app.modules.core.retrieval.rerankers.jev_decision_reranker import JevDecisionReranker

pytestmark = [
    pytest.mark.integration,
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.environ.get("TYPESAFE_API_KEY", "").strip(), reason="TYPESAFE_API_KEY not set",
    ),
]


@pytest.mark.asyncio
async def test_jev_mode_factory_judges_live_passage() -> None:
    reranker = RerankerFactoryV2.create(
        {"reranking": {"typesafe": {
            "model": os.environ.get("TYPESAFE_JEV_MODEL", "jev-1.13.0"),
        }}},
        env={"RERANK_MODE": "jev", "TYPESAFE_API_KEY": os.environ["TYPESAFE_API_KEY"]},
    )
    assert isinstance(reranker, JevDecisionReranker)
    try:
        assert reranker.mode == "enforce"
        docs = [SearchResult("synthetic", "Seoul is the capital of South Korea.", 0.9, {})]
        output = await reranker.rerank("What is the capital of South Korea?", docs, top_n=1)
        assert len(output) == 1
        assert output[0].metadata["jev_outcome"] == "judged"
        batches = reranker.get_recent_decisions()
        assert len(batches) == 1
        # Fail-open output alone does not prove the live API worked.
        assert any(decision.status == "ok" for decision in batches[0].decisions)
    finally:
        await reranker.close()
