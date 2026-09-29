"""The reranker switch leaves the independent Self-RAG precheck operational."""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from app.modules.core.decision import JevDecisionProvider, NoulResult
from app.modules.core.retrieval.interfaces import SearchResult
from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2
from app.modules.core.self_rag.evaluator import EvalStatus, QualityEvaluation, QualityScore
from app.modules.core.self_rag.precheck import build_self_rag_evaluator


@pytest.mark.asyncio
@pytest.mark.parametrize("precheck_mode", ["shadow", "off"])
async def test_legacy_reranker_does_not_control_precheck(monkeypatch, precheck_mode):
    monkeypatch.setenv("RERANK_MODE", "legacy")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    docs = [SearchResult("a", "synthetic passage", 0.9, {})]
    legacy = Mock(rerank=AsyncMock(return_value=docs))
    base = Mock(evaluate=AsyncMock(return_value=QualityEvaluation(
        EvalStatus.OK, QualityScore(0.8, 0.8, 0.8, 0.8, 0.8, "synthetic", {}),
    )))
    prefix = "app.modules.core.retrieval.rerankers."
    with (
        patch.object(httpx.AsyncClient, "send", side_effect=AssertionError("Unexpected HTTP")) as http,
        patch(prefix + "gemini_reranker.GeminiFlashReranker", return_value=legacy) as google,
        patch(prefix + "jev_decision_reranker.JevDecisionReranker") as jev_ctor,
        patch(prefix + "jev_client.TypeSafeJevClient") as jev_client,
        patch(prefix + "jev_decision_reranker.JevDecisionReranker.rerank") as jev_rerank,
        patch(prefix + "jev_client.TypeSafeJevClient.ask") as jev_ask,
        patch.object(JevDecisionProvider, "noul", new_callable=AsyncMock, return_value=NoulResult(
            probability=0.9, status="ok", latency_ms=1, provider="jev",
        )) as precheck_call,
    ):
        reranker = RerankerFactoryV2.create(
            {"reranking": {"approach": "llm", "provider": "google"}},
            env={"RERANK_MODE": "legacy", "GOOGLE_API_KEY": "test-key"},
        )
        evaluator = build_self_rag_evaluator(base, {
            "mode": precheck_mode, "provider": "jev", "api_key": "test-key",
        })
        try:
            assert await reranker.rerank("query", docs, top_n=1) == docs
            result = await evaluator.evaluate("query", "answer", [docs[0].content])
            assert result.status is EvalStatus.OK
            google.assert_called_once()
            legacy.rerank.assert_awaited_once()
            base.evaluate.assert_awaited_once()
            assert precheck_call.await_count == (1 if precheck_mode == "shadow" else 0)
            for spy in (jev_ctor, jev_client, jev_rerank, jev_ask, http):
                spy.assert_not_called()
        finally:
            if precheck_mode != "off":
                await evaluator.aclose()
