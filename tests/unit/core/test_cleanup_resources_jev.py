"""Jev precheck provider cleanup without constructing unrelated DI singletons."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core import di_container


def fake_container(mode: str | dict | None, evaluator: object) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            self_rag=SimpleNamespace(precheck=SimpleNamespace(mode=Mock(return_value=mode)))
        ),
        self_rag_evaluator=Mock(return_value=evaluator),
        session=Mock(return_value=None),
        document_processor=Mock(return_value=None),
        graph_store=Mock(return_value=None),
        retrieval_orchestrator=Mock(return_value=None),
        vector_store=Mock(return_value=None),
        metadata_store=Mock(return_value=None),
        generation=Mock(return_value=None),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["shadow", {"mode": "enforce"}])
async def test_cleanup_closes_precheck_provider(mode) -> None:
    evaluator = SimpleNamespace(aclose=AsyncMock())
    container = fake_container(mode, evaluator)
    await di_container.cleanup_resources(container)
    container.self_rag_evaluator.assert_called_once()
    evaluator.aclose.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["off", None, {}])
async def test_cleanup_off_does_not_instantiate_evaluator(mode) -> None:
    container = fake_container(mode, SimpleNamespace(aclose=AsyncMock()))
    await di_container.cleanup_resources(container)
    container.self_rag_evaluator.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_records_precheck_close_error(monkeypatch) -> None:
    evaluator = SimpleNamespace(aclose=AsyncMock(side_effect=RuntimeError("close failed")))
    container = fake_container("shadow", evaluator)
    warning = Mock()
    monkeypatch.setattr(di_container.logger, "warning", warning)
    await di_container.cleanup_resources(container)
    assert warning.call_args.kwargs["extra"]["errors"] == [
        "Self-RAG precheck provider: close failed"
    ]
