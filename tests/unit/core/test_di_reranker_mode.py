"""Fatal Jev configuration, deferred chains, and process-lifetime singletons."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from dependency_injector import providers

from app.core.di_container import (
    AppContainer,
    create_reranker_chain_instance,
    create_reranker_instance_v2,
)
from app.modules.core.retrieval.rerankers.mode import RerankerModeConfigError


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("RERANK_MODE", "TYPESAFE_JEV_MODE", "TYPESAFE_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RerankerModeConfigError("invalid mode"),
                                        RuntimeError("test-key"), ValueError("test-key")])
async def test_jev_errors_propagate(monkeypatch, error):
    monkeypatch.setenv("RERANK_MODE", "jev")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    with patch("app.modules.core.retrieval.rerankers.factory.RerankerFactoryV2.create", side_effect=error), \
         patch("app.core.di_container.logger") as logger:
        with pytest.raises(RerankerModeConfigError) as result:
            await create_reranker_instance_v2({})
    if isinstance(error, RerankerModeConfigError):
        assert result.value is error
    else:
        assert result.value.__cause__ is error
    assert "test-key" not in str(result.value)
    assert "test-key" not in str(logger.mock_calls)


@pytest.mark.asyncio
async def test_missing_jev_key_never_returns_none(monkeypatch):
    monkeypatch.setenv("RERANK_MODE", "jev")
    with pytest.raises(RerankerModeConfigError, match="TYPESAFE_API_KEY"):
        await create_reranker_instance_v2({})


@pytest.mark.asyncio
async def test_legacy_missing_key_retains_graceful_behavior():
    with patch("app.core.di_container.logger") as logger:
        assert await create_reranker_instance_v2({"reranking": {
            "approach": "llm", "provider": "google",
        }}) is None
    assert logger.warning.call_args.kwargs["extra"]["effective_reranker"] == "none"


@pytest.mark.asyncio
async def test_disabled_never_constructs_reranker(monkeypatch):
    monkeypatch.setenv("RERANK_MODE", "jev")
    with patch("app.modules.core.retrieval.rerankers.factory.RerankerFactoryV2.create") as factory:
        assert await create_reranker_instance_v2({"reranking": {"enabled": False},
                                                  "retrieval": {"enable_reranking": True}}) is None
        factory.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_still_validates_syntax(monkeypatch):
    monkeypatch.setenv("RERANK_MODE", "")
    with pytest.raises(RerankerModeConfigError):
        await create_reranker_instance_v2({"reranking": {"enabled": False}})


@pytest.mark.asyncio
async def test_jev_chain_does_not_evaluate_di_dependencies(monkeypatch):
    monkeypatch.setenv("RERANK_MODE", "jev")
    container = AppContainer()
    container.config.from_dict({"reranking": {"chain": {"enabled": True}}})
    colbert, llm = Mock(side_effect=AssertionError("ColBERT constructed")), Mock(side_effect=AssertionError("LLM constructed"))
    with container.colbert_reranker.override(providers.Factory(colbert)), \
         container.base_reranker.override(providers.Factory(llm)):
        assert await container.reranker_chain() is None
    colbert.assert_not_called()
    llm.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_chain_resolves_deferred_providers():
    colbert, llm = Mock(name="colbert"), Mock(name="llm")
    first, second = AsyncMock(return_value=colbert), Mock(return_value=llm)
    chain = await create_reranker_chain_instance({"reranking": {"chain": {"enabled": True}}},
        colbert_reranker_provider=first, llm_reranker_provider=second)
    assert chain.rerankers == [colbert, llm]
    first.assert_awaited_once()
    second.assert_called_once()


@pytest.mark.asyncio
async def test_singleton_does_not_hot_switch(monkeypatch):
    monkeypatch.setenv("RERANK_MODE", "jev")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    container = AppContainer()
    container.config.from_dict({})
    with container.llm_factory.override(providers.Object(None)):
        first = await container.reranker()
        monkeypatch.setenv("RERANK_MODE", "legacy")
        try:
            assert await container.reranker() is first
            assert first.mode == "enforce"
        finally:
            await first.close()
