"""DI 컨테이너 기동 경로 단일화 테스트.

표준/graceful 두 함수는 같은 모듈 그래프(_build_startup_modules)를 공유하고,
타임아웃/재시도 프로파일만 다르다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import di_container
from app.core.graceful_initializer import ModulePriority


def _container() -> MagicMock:
    container = MagicMock()
    for name in (
        "session", "generation", "database_manager", "prompt_repository",
        "evaluation", "tool_executor",
    ):
        getattr(container, name).return_value.initialize = AsyncMock()
    return container


def test_both_profiles_share_the_same_module_graph() -> None:
    container = _container()
    standard = di_container._build_startup_modules(container, retrieval_required=False, graceful=False)
    graceful = di_container._build_startup_modules(container, retrieval_required=False, graceful=True)
    assert [m.name for m in standard] == [m.name for m in graceful]
    assert {m.name for m in standard} >= {
        "Session", "Generation", "DatabaseManager", "PromptRepository", "ToolExecutor",
        "WeaviateRetriever", "RetrievalOrchestrator", "SelfRAG",
    }
    by_name = {m.name: m for m in graceful}
    assert by_name["RetrievalOrchestrator"].dependencies == ["WeaviateRetriever"]
    assert by_name["SelfRAG"].dependencies == ["RetrievalOrchestrator"]


def test_profiles_differ_only_in_timing() -> None:
    container = _container()
    standard = {m.name: m for m in di_container._build_startup_modules(container, retrieval_required=False, graceful=False)}
    graceful = {m.name: m for m in di_container._build_startup_modules(container, retrieval_required=False, graceful=True)}
    assert standard["Session"].timeout == 120.0 and standard["Session"].retry_count == 1
    assert graceful["Session"].timeout == 10.0 and graceful["Session"].retry_count == 2
    assert standard["Session"].priority == graceful["Session"].priority


@pytest.mark.parametrize("required", [True, False])
def test_retrieval_priority_follows_startup_policy(required: bool) -> None:
    container = _container()
    modules = {m.name: m for m in di_container._build_startup_modules(container, retrieval_required=required, graceful=True)}
    expected = ModulePriority.CRITICAL if required else ModulePriority.IMPORTANT
    assert modules["RetrievalOrchestrator"].priority == expected
    assert modules["WeaviateRetriever"].priority == expected


@pytest.mark.asyncio
async def test_orchestrator_initializer_resolves_async_singletons_first() -> None:
    container = MagicMock()
    order: list[str] = []

    async def reranker():
        order.append("reranker")

    async def cache():
        order.append("cache")

    orchestrator = MagicMock()
    orchestrator.initialize = AsyncMock(side_effect=lambda: order.append("orchestrator"))

    async def orchestrator_provider():
        return orchestrator

    container.reranker.return_value = reranker()
    container.cache.return_value = cache()
    container.retrieval_orchestrator.return_value = orchestrator_provider()

    await di_container._init_retrieval_orchestrator(container)
    assert order == ["reranker", "cache", "orchestrator"]


@pytest.mark.asyncio
async def test_initialize_async_resources_delegates_to_shared_runner(monkeypatch) -> None:
    calls: list[bool] = []

    async def fake_run(container, *, graceful):
        calls.append(graceful)

    monkeypatch.setattr(di_container, "_run_startup", fake_run)
    await di_container.initialize_async_resources(MagicMock())
    await di_container.initialize_async_resources_graceful(MagicMock())
    assert calls == [False, True]


@pytest.mark.asyncio
async def test_orchestrator_waits_for_weaviate_retriever_in_same_priority_group() -> None:
    """같은 우선순위 그룹에서 동시에 실행되어도 오케스트레이터는 Weaviate 초기화 완료를 기다린다."""
    import asyncio

    container = MagicMock()
    order: list[str] = []
    signals = di_container._StartupSignals()

    retriever = MagicMock()

    async def slow_init():
        await asyncio.sleep(0.05)
        order.append("weaviate")

    retriever.initialize = slow_init

    async def retriever_provider():
        return retriever

    container.weaviate_retriever.return_value = retriever_provider()

    async def reranker():
        return None

    async def cache():
        return None

    orchestrator = MagicMock()
    orchestrator.initialize = AsyncMock(side_effect=lambda: order.append("orchestrator"))

    async def orchestrator_provider():
        return orchestrator

    container.reranker.return_value = reranker()
    container.cache.return_value = cache()
    container.retrieval_orchestrator.return_value = orchestrator_provider()

    # 오케스트레이터를 먼저 띄워도 Weaviate 완료 이후에 초기화된다
    await asyncio.gather(
        di_container._init_retrieval_orchestrator(container, signals),
        di_container._init_weaviate_retriever(container, signals),
    )
    assert order == ["weaviate", "orchestrator"]
