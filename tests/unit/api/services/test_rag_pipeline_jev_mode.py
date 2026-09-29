"""Jev outcome policy through DI, the orchestrator, and the pipeline."""

import asyncio
import time
from contextlib import ExitStack
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from openai.resources.responses import Responses

from app.api.services.rag_pipeline import (
    FormattedSources,
    PreparedContext,
    RAGPipeline,
    RetrievalResults,
    RouteDecision,
)
from app.core.di_container import create_reranker_instance_v2
from app.modules.core.generation.generator import GenerationResult
from app.modules.core.retrieval.interfaces import SearchResult
from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator
from app.modules.core.retrieval.rerankers.gemini_reranker import GeminiFlashReranker
from app.modules.core.retrieval.rerankers.jev_client import (
    JevAnswer,
    JevAPIError,
    TypeSafeJevClient,
)
from app.modules.core.retrieval.rerankers.jev_decision_reranker import JevDecisionReranker

PREFIX = "app.modules.core.retrieval.rerankers."


def documents():
    return [SearchResult(str(i), f"passage {i}", 0.01, {"original_score": i / 10})
            for i in range(5)]


def pipeline_for(retrieval, config):
    return RAGPipeline(
        config=config, query_router=None, query_expansion=None,
        retrieval_module=retrieval, generation_module=AsyncMock(), session_module=None,
        self_rag_module=None, extract_topic_func=lambda q: q,
        circuit_breaker_factory=MagicMock(), cost_tracker=MagicMock(),
        performance_metrics=MagicMock(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("top_n", [None, 0, 2])
async def test_pipeline_exception_is_bounded(top_n):
    incoming = documents()
    pipeline = pipeline_for(AsyncMock(rerank=AsyncMock(side_effect=RuntimeError("unavailable"))),
                            {"reranking": {"enabled": True}})
    result = await pipeline.rerank_documents("q", incoming, {"top_n": top_n})
    assert result.documents == incoming[:top_n]
    assert result.count == len(incoming[:top_n])
    assert result.reranked is False


@pytest.mark.asyncio
async def test_pipeline_rejects_negative_limit():
    pipeline = pipeline_for(AsyncMock(), {"reranking": {"enabled": True}})
    with pytest.raises(ValueError):
        await pipeline.rerank_documents("q", [], {"top_n": -1})


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,scenario", [
    ("legacy", "keep"), ("jev", "keep"), ("jev", "drop"), ("jev", "select"),
    ("jev", "deadline"), ("jev", "all_error"), ("jev", "circuit_open"),
])
@pytest.mark.parametrize("fusion", [False, True])
async def test_di_to_pipeline_isolation_and_outcome(monkeypatch, mode, scenario, fusion):
    monkeypatch.setenv("RERANK_MODE", mode)
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.delenv("TYPESAFE_JEV_MODE", raising=False)
    config = {"reranking": {
        "enabled": True, "approach": "llm", "provider": "google", "min_score": 0.05,
        "typesafe": {"deadline_seconds": 0.02, "min_keep": 1},
        "fusion": {"enabled": fusion},
    }}
    incoming = documents()
    original = deepcopy(incoming)

    async def ask(state, questions):
        if scenario == "deadline":
            await asyncio.Event().wait()
        if scenario == "all_error":
            raise JevAPIError("http_503")
        position = int(state["passage"].split()[-1])
        probability = 0.1 if scenario == "drop" or (scenario == "select" and position == 1) else 0.9
        return {"relevant": JevAnswer(probability)}

    with ExitStack() as stack:
        network = stack.enter_context(patch.object(httpx.AsyncClient, "send",
                                                   side_effect=AssertionError("Unexpected HTTP")))
        jev_ctor = stack.enter_context(patch(PREFIX + "jev_decision_reranker.JevDecisionReranker",
                                            wraps=JevDecisionReranker))
        client_ctor = stack.enter_context(patch(PREFIX + "jev_decision_reranker.TypeSafeJevClient",
                                               wraps=TypeSafeJevClient))
        jev_call = stack.enter_context(patch.object(TypeSafeJevClient, "ask", side_effect=ask))
        jev_rerank = stack.enter_context(patch.object(JevDecisionReranker, "rerank", autospec=True,
                                                     side_effect=JevDecisionReranker.rerank))
        llm_ctor = stack.enter_context(patch(PREFIX + "gemini_reranker.GeminiFlashReranker",
                                            wraps=GeminiFlashReranker))
        llm_rerank = stack.enter_context(patch.object(GeminiFlashReranker, "rerank", autospec=True,
                                                     side_effect=GeminiFlashReranker.rerank))
        other_calls = [stack.enter_context(patch(PREFIX + name)) for name in (
            "openai_llm_reranker.OpenAILLMReranker.rerank", "openrouter_reranker.OpenRouterReranker.rerank")]
        other_ctors = [stack.enter_context(patch(PREFIX + name)) for name in (
            "openai_llm_reranker.OpenAILLMReranker", "openrouter_reranker.OpenRouterReranker")]
        openai_call = stack.enter_context(patch.object(Responses, "create",
            side_effect=AssertionError("Unexpected OpenAI call")))
        google_call = stack.enter_context(patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock,
            return_value=httpx.Response(200, request=httpx.Request("POST", "https://example.test"),
                json={"candidates": [{"content": {"parts": [{"text":
                    '{"results":[{"index":0,"score":0.9},{"index":1,"score":0.8},{"index":2,"score":0.7}]}'
                }]}}]})))
        reranker = await create_reranker_instance_v2(config)
        if scenario == "circuit_open":
            reranker._circuit_open_until = time.monotonic() + 60
        retrieval = RetrievalOrchestrator(AsyncMock(search=AsyncMock(return_value=incoming)), reranker)
        pipeline = pipeline_for(retrieval, config)
        # Execute the real fusion guard, replacing only unrelated pipeline stages.
        stack.enter_context(patch.object(pipeline, "route_query", return_value=RouteDecision(True, {})))
        stack.enter_context(patch.object(pipeline, "prepare_context", return_value=PreparedContext(
            session_context=None, expanded_query="q", original_query="q")))
        stack.enter_context(patch.object(pipeline, "_execute_parallel_search",
            return_value=(RetrievalResults(incoming, len(incoming)), None)))
        stack.enter_context(patch.object(pipeline, "expand_context_documents",
            side_effect=lambda docs, options: docs))
        generated = GenerationResult(answer="answer", text="answer", tokens_used=0,
            model_used="fake", provider="fake", generation_time=0)
        generate = stack.enter_context(patch.object(pipeline, "generate_answer", return_value=generated))
        stack.enter_context(patch.object(pipeline, "self_rag_verify", return_value=generated))
        stack.enter_context(patch.object(pipeline, "format_sources", return_value=FormattedSources([], 0)))
        stack.enter_context(patch.object(pipeline, "build_result", return_value={"processing_time": 0}))
        fuse = stack.enter_context(patch.object(pipeline, "_fuse_reranked_results_with_original_signals",
            wraps=pipeline._fuse_reranked_results_with_original_signals))
        outcomes = []
        real_rerank = pipeline.rerank_documents

        async def capture(*args, **kwargs):
            result = await real_rerank(*args, **kwargs)
            outcomes.append(result)
            return result

        stack.enter_context(patch.object(pipeline, "rerank_documents", side_effect=capture))
        try:
            await pipeline.execute("q", "session", {"top_n": 3})
            result = outcomes[0]
            output = generate.call_args.args[1]
            assert len(output) <= 3
            assert {doc.id for doc in output} <= {doc.id for doc in result.documents}
            fallback = scenario in ("deadline", "all_error", "circuit_open")
            assert result.reranked is not fallback
            assert fuse.call_count == (0 if fallback else 1)
            if mode == "jev":
                assert incoming == original
                assert all(doc.metadata["jev_outcome"] == ("fallback" if fallback else "judged")
                           for doc in output)
                if fallback:
                    assert [doc.id for doc in output] == ["0", "1", "2"]
                    assert all("rerank_method" not in doc.metadata for doc in output)
                elif scenario == "drop":
                    assert [doc.id for doc in output] == ["0"]
                elif scenario == "select":
                    assert {doc.id for doc in output} == {"0", "2", "3"}
                assert all(doc.score == 0.01 for doc in output)
                assert jev_ctor.call_count == client_ctor.call_count == jev_rerank.call_count == 1
                expected_calls = {"circuit_open": 0, "deadline": 4}.get(scenario, 5)
                assert jev_call.await_count == expected_calls
                llm_ctor.assert_not_called()
                llm_rerank.assert_not_called()
                google_call.assert_not_called()
            else:
                assert llm_ctor.call_count == llm_rerank.call_count == google_call.await_count == 1
                for spy in (jev_ctor, client_ctor, jev_rerank, jev_call):
                    spy.assert_not_called()
            for spy in (*other_ctors, *other_calls, openai_call):
                spy.assert_not_called()
            network.assert_not_called()
        finally:
            await (reranker.cleanup() if mode == "legacy" else reranker.close())
