"""Exercise real rerankers with fake provider boundaries and forbidden network I/O."""

import asyncio
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.modules.core.retrieval.interfaces import SearchResult
from app.modules.core.retrieval.rerankers.factory import RerankerFactory, RerankerFactoryV2
from app.modules.core.retrieval.rerankers.jev_client import JevAnswer, JevAPIError
from app.modules.core.retrieval.rerankers.mode import RerankerModeConfigError

PREFIX = "app.modules.core.retrieval.rerankers."
LLMS = [
    ("gemini_reranker", "GeminiFlashReranker"),
    ("openai_llm_reranker", "OpenAILLMReranker"),
    ("openrouter_reranker", "OpenRouterReranker"),
]


@pytest.fixture(autouse=True)
def no_network():
    with patch.object(httpx.AsyncClient, "send", side_effect=AssertionError("Unexpected HTTP")) as send:
        yield send
        send.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "jev"])
@pytest.mark.parametrize("keys", [
    {"GOOGLE_API_KEY": "test-key", "TYPESAFE_API_KEY": "test-key"},
    {"GOOGLE_API_KEY": "test-key"}, {"TYPESAFE_API_KEY": "test-key"},
])
async def test_mode_key_matrix(mode, keys):
    from app.modules.core.retrieval.rerankers.gemini_reranker import GeminiFlashReranker
    from app.modules.core.retrieval.rerankers.jev_client import TypeSafeJevClient
    from app.modules.core.retrieval.rerankers.jev_decision_reranker import JevDecisionReranker

    env = {"RERANK_MODE": mode, **keys}
    config = {"reranking": {"approach": "llm", "provider": "google"}}
    docs = [SearchResult(id="a", content="passage", score=0.5, metadata={})]
    with ExitStack() as stack:
        jev_ctor = stack.enter_context(patch(PREFIX + "jev_decision_reranker.JevDecisionReranker",
                                            wraps=JevDecisionReranker))
        client_ctor = stack.enter_context(patch(PREFIX + "jev_decision_reranker.TypeSafeJevClient",
                                               wraps=TypeSafeJevClient))
        llm_ctors = [stack.enter_context(patch(PREFIX + module + "." + name,
                    wraps=GeminiFlashReranker if name == "GeminiFlashReranker" else None))
                    for module, name in LLMS]
        jev_call = stack.enter_context(patch.object(TypeSafeJevClient, "ask", new_callable=AsyncMock,
                                                   return_value={"relevant": JevAnswer(0.9)}))
        jev_rerank = stack.enter_context(patch.object(JevDecisionReranker, "rerank", autospec=True,
                                                     side_effect=JevDecisionReranker.rerank))
        llm_rerank = stack.enter_context(patch.object(GeminiFlashReranker, "rerank", autospec=True,
                                                     side_effect=GeminiFlashReranker.rerank))
        required = "GOOGLE_API_KEY" if mode == "legacy" else "TYPESAFE_API_KEY"
        if required not in keys:
            with pytest.raises(ValueError if mode == "legacy" else RerankerModeConfigError):
                RerankerFactoryV2.create(config, env=env)
            assert not any(ctor.called for ctor in [jev_ctor, client_ctor, *llm_ctors])
            assert not jev_call.called and not llm_rerank.called and not jev_rerank.called
            return
        reranker = RerankerFactoryV2.create(config, env=env)
        google_call = AsyncMock(return_value=httpx.Response(200, request=httpx.Request("POST", "https://example.test"),
            json={"candidates": [{"content": {"parts": [{"text": '{"results":[{"index":0,"score":0.9}]}'}]}}]}))
        if mode == "legacy":
            stack.enter_context(patch.object(reranker.http_client, "post", google_call))
        try:
            for _ in range(3):
                assert len(await reranker.rerank("query", docs, 1)) == 1
            if mode == "legacy":
                assert llm_ctors[0].call_count == 1
                assert llm_rerank.call_count == google_call.await_count == 3
                assert jev_ctor.call_count == client_ctor.call_count == 0
                assert jev_rerank.call_count == jev_call.await_count == 0
            else:
                assert reranker.mode == "enforce"
                assert jev_ctor.call_count == client_ctor.call_count == 1
                assert jev_rerank.call_count == jev_call.await_count == 3
                assert all(ctor.call_count == 0 for ctor in llm_ctors)
                assert llm_rerank.call_count == google_call.await_count == 0
        finally:
            await (reranker.cleanup() if mode == "legacy" else reranker.close())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["all_error", "deadline", "circuit_open"])
async def test_jev_failure_never_constructs_or_calls_llm(failure):
    async def slow(*args, **kwargs):
        await asyncio.sleep(10)

    with ExitStack() as stack:
        ctors = [stack.enter_context(patch(PREFIX + module + "." + name)) for module, name in LLMS]
        ask = stack.enter_context(patch(PREFIX + "jev_client.TypeSafeJevClient.ask",
            side_effect=slow if failure == "deadline" else JevAPIError("transport")))
        reranker = RerankerFactoryV2.create({"reranking": {"typesafe": {"deadline_seconds": 0.01}}},
            env={"RERANK_MODE": "jev", "TYPESAFE_API_KEY": "test-key"})
        if failure == "circuit_open":
            reranker._circuit_open_until = time.monotonic() + 60
        try:
            docs = [SearchResult(id="a", content="passage", score=0.5, metadata={})]
            for _ in range(3):
                assert await reranker.rerank("query", docs, top_n=1) == docs
            assert ask.await_count == (0 if failure == "circuit_open" else 3)
            assert all(not ctor.called for ctor in ctors)
        finally:
            await reranker.close()


@pytest.mark.parametrize("old_mode", [None, "shadow", "off"])
def test_migration_error_constructs_neither_side(old_mode):
    with patch(PREFIX + "factory.RerankerFactoryV2._create_llm_reranker") as llm, \
         patch(PREFIX + "factory.RerankerFactoryV2._create_jev_reranker") as jev:
        with pytest.raises(RerankerModeConfigError):
            RerankerFactoryV2.create({"reranking": {"approach": "decision",
                "typesafe": {"mode": old_mode}}}, env={})
        llm.assert_not_called()
        jev.assert_not_called()


@pytest.mark.asyncio
async def test_old_api_delegates_before_stale_provider_validation():
    with patch(PREFIX + "factory.RerankerFactoryV2._create_llm_reranker") as llm:
        reranker = RerankerFactory.create({"reranking": {"provider": "stale"}},
            env={"RERANK_MODE": "jev", "TYPESAFE_API_KEY": "test-key"})
        try:
            assert reranker.mode == "enforce"
            llm.assert_not_called()
        finally:
            await reranker.close()


@pytest.mark.parametrize("mode, forbidden", [
    ("legacy", ["jev_decision_reranker", "jev_client"]),
    ("jev", ["gemini_reranker", "openai_llm_reranker", "openrouter_reranker"]),
])
def test_provider_import_isolation_in_fresh_process(mode, forbidden):
    code = f"""
import asyncio, sys
from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2
reranker = RerankerFactoryV2.create(
    {{'reranking': {{'approach': 'llm', 'provider': 'google'}}}},
    env={{'RERANK_MODE': {mode!r}, 'GOOGLE_API_KEY': 'test-key', 'TYPESAFE_API_KEY': 'test-key'}})
assert all('app.modules.core.retrieval.rerankers.' + name not in sys.modules for name in {forbidden!r})
asyncio.run(reranker.{'cleanup' if mode == 'legacy' else 'close'}())
"""
    env = {**os.environ, "PYTHON_DOTENV_DISABLED": "1"}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
