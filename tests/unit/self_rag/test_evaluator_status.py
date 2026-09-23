"""Evaluation failures must never become invented quality scores."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.core.self_rag.evaluator import EvalStatus, LLMQualityEvaluator

pytestmark = pytest.mark.unit


def evaluator_with_response(response: str, *, timeout: float = 10.0) -> LLMQualityEvaluator:
    evaluator = LLMQualityEvaluator(api_key=None, timeout_seconds=timeout)
    evaluator.llm = MagicMock(ainvoke=AsyncMock(return_value=SimpleNamespace(content=response)))
    return evaluator


@pytest.mark.asyncio
async def test_unavailable() -> None:
    evaluator = LLMQualityEvaluator(api_key=None)
    result = await evaluator.evaluate("query", "answer", [])
    assert not evaluator.is_available
    assert result.status is EvalStatus.UNAVAILABLE
    assert result.score is None


@pytest.mark.asyncio
@pytest.mark.parametrize("fenced", [False, True])
async def test_valid_scores(fenced: bool) -> None:
    payload = json.dumps({"relevance": 0.2, "grounding": 0.4, "completeness": 0.6,
                          "confidence": 0.8, "reasoning": "ok"})
    evaluator = evaluator_with_response(f"```json\n{payload}\n```" if fenced else payload)
    result = await evaluator.evaluate("query", "answer", [])
    assert result.status is EvalStatus.OK
    assert result.score is not None
    assert result.score.overall == pytest.approx(0.35 * 0.2 + 0.30 * 0.4 + 0.25 * 0.6 + 0.10 * 0.8)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    "not json",
    '{"relevance": 0.5, "completeness": 0.5, "confidence": 0.5}',
    '{"relevance": "high", "grounding": 0.5, "completeness": 0.5, "confidence": 0.5}',
    '{"relevance": 8, "grounding": 0.5, "completeness": 0.5, "confidence": 0.5}',
])
async def test_invalid_scores_fail(response: str) -> None:
    result = await evaluator_with_response(response).evaluate("query", "answer", [])
    assert result.status is EvalStatus.FAILED
    assert result.score is None


@pytest.mark.asyncio
async def test_invoke_error() -> None:
    evaluator = evaluator_with_response("{}")
    evaluator.llm.ainvoke.side_effect = RuntimeError("model unavailable")
    result = await evaluator.evaluate("query", "answer", [])
    assert result.status is EvalStatus.FAILED
    assert result.score is None
    assert "model unavailable" in (result.error or "")


@pytest.mark.asyncio
async def test_timeout() -> None:
    evaluator = evaluator_with_response("{}", timeout=0.01)

    async def slow_response(_prompt: str) -> None:
        await asyncio.sleep(0.1)

    evaluator.llm.ainvoke.side_effect = slow_response
    result = await evaluator.evaluate("query", "answer", [])
    assert result.status is EvalStatus.TIMEOUT
    assert result.score is None


def test_no_default_score() -> None:
    assert not hasattr(LLMQualityEvaluator, "_default_quality_score")
