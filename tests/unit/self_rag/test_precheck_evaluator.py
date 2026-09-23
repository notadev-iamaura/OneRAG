"""precheck 모드별 점수 보존, 단축 판정, fail-open 및 위임 검증."""

import asyncio
from dataclasses import dataclass, replace
from unittest.mock import Mock

import pytest

from app.modules.core.decision import JevDecisionProvider, MockDecisionProvider, NoulResult
from app.modules.core.self_rag.evaluator import LLMQualityEvaluator, QualityScore
from app.modules.core.self_rag.precheck import (
    PrecheckQualityEvaluator,
    PrecheckSettings,
    build_self_rag_evaluator,
)
from tests.unit.self_rag.test_orchestrator_options import _FakeEvaluator


class _RecordingEvaluator(_FakeEvaluator):
    """기존 fake의 점수를 재사용하고 실제 임계값 판정과 호출 기록을 추가한다."""

    requires_regeneration = LLMQualityEvaluator.requires_regeneration

    def __init__(self, requires_regen=False):
        super().__init__(requires_regen)
        self.calls = []
        self.last_score = None

    async def evaluate(self, query, answer, context):
        self.calls.append({"query": query, "answer": answer, "context": context})
        self.last_score = await super().evaluate(query, answer, context)
        self.last_score.raw_response["base_metadata"] = {"preserved": True}
        return self.last_score


@pytest.mark.parametrize(
    "config",
    [None, {}, {"mode": False}, "off", {"mode": "off"}, {"mode": "bogus"},
     {"mode": "enforce", "provider": "bogus"}, {"mode": "enforce", "timeout_ms": -1}],
)
def test_off_identity_and_no_provider_creation(monkeypatch, config):
    factory = Mock(side_effect=AssertionError("provider must not be created"))
    monkeypatch.setattr("app.modules.core.self_rag.precheck.create_decision_provider", factory)
    base = _RecordingEvaluator()
    assert build_self_rag_evaluator(base, config) is base
    factory.assert_not_called()


def test_provider_initialization_error_returns_base(monkeypatch):
    factory = Mock(side_effect=RuntimeError("unavailable"))
    monkeypatch.setattr("app.modules.core.self_rag.precheck.create_decision_provider", factory)
    base = _RecordingEvaluator()
    assert build_self_rag_evaluator(base, {"mode": "enforce"}) is base
    factory.assert_called_once()


@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_missing_jev_key_warns_without_key_material(mode, capsys):
    base = _RecordingEvaluator()
    evaluator = build_self_rag_evaluator(base, {"mode": mode, "provider": "jev", "api_key": ""})
    assert isinstance(evaluator, PrecheckQualityEvaluator)
    output = capsys.readouterr().out
    assert "self_rag_precheck_missing_api_key" in output
    assert f"mode={mode}" in output
    assert "has_key=False" in output
    assert "api_key=" not in output
    build_self_rag_evaluator(base, {"mode": mode, "provider": "jev", "api_key": "test-secret"})
    output_with_key = capsys.readouterr().out
    assert "self_rag_precheck_missing_api_key" not in output_with_key
    assert "test-secret" not in output_with_key


@pytest.mark.asyncio
@pytest.mark.parametrize("requires_regen", [False, True])
async def test_shadow_low_preserves_base_score_and_regeneration(requires_regen):
    base = _RecordingEvaluator(requires_regen)
    provider = MockDecisionProvider(0.01)
    evaluator = PrecheckQualityEvaluator(base, provider, PrecheckSettings(mode="shadow"))
    score = await evaluator.evaluate("q", "a", ["ctx"])
    assert len(base.calls) == len(provider.calls) == 1
    assert score is not base.last_score
    assert replace(score, raw_response=base.last_score.raw_response) == base.last_score
    assert "precheck" not in base.last_score.raw_response
    assert score.raw_response["base_metadata"] == {"preserved": True}
    assert evaluator.requires_regeneration(score) == requires_regen
    assert score.raw_response["precheck"]["decision"] == "shadow"
    assert score.raw_response["precheck"]["p_grounded"] == 0.01
    assert evaluator.stats["calls"] == evaluator.stats["shadow"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["shadow", "enforce"])
@pytest.mark.parametrize("status", ["timeout", "http_error", "parse_error", "missing_api_key", "error"])
async def test_provider_failures_preserve_base_result(mode, status):
    base = _RecordingEvaluator()
    evaluator = PrecheckQualityEvaluator(
        base, MockDecisionProvider(status=status), PrecheckSettings(mode=mode)
    )
    score = await evaluator.evaluate("q", "a", ["ctx"])
    assert len(base.calls) == 1
    assert score.overall == 0.9
    assert not evaluator.requires_regeneration(score)
    metadata = score.raw_response["precheck"]
    assert metadata["status"] == status
    assert metadata["decision"] == ("shadow" if mode == "shadow" else "fail_open")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["shadow", "enforce"])
@pytest.mark.parametrize("failure", ["raise", "deadline"])
async def test_exception_and_wall_clock_timeout_fail_open(mode, failure):
    base = _RecordingEvaluator()
    provider = (
        MockDecisionProvider(error=RuntimeError("private context"))
        if failure == "raise" else MockDecisionProvider(delay_s=2)
    )
    evaluator = PrecheckQualityEvaluator(base, provider, PrecheckSettings(mode=mode, timeout_ms=10))
    score = await asyncio.wait_for(evaluator.evaluate("q", "a", ["ctx"]), timeout=1)
    assert len(base.calls) == 1
    assert score.overall == 0.9
    assert score.raw_response["precheck"]["status"] == ("error" if failure == "raise" else "timeout")
    assert "private context" not in repr(score)


@pytest.mark.asyncio
@pytest.mark.parametrize(("threshold", "probability"), [(0.35, 0.1), (0.9, 0.85), (0.35, 0.0)])
async def test_enforce_low_short_circuits_and_triggers_real_regeneration(threshold, probability):
    base = _RecordingEvaluator()
    evaluator = PrecheckQualityEvaluator(
        base, MockDecisionProvider(probability), PrecheckSettings(mode="enforce", threshold=threshold)
    )
    score = await evaluator.evaluate("q", "a", ["ctx"])
    assert base.calls == []
    assert score.grounding == probability
    assert score.overall == pytest.approx(
        max(0.0, min(probability, base.quality_threshold - 1e-6))
    )
    assert evaluator.requires_regeneration(score)
    assert "jev_precheck" in score.reasoning
    assert score.raw_response["source"] == "jev_precheck"
    assert score.raw_response["precheck"]["decision"] == "short_circuit"


@pytest.mark.asyncio
@pytest.mark.parametrize("probability", [0.35, 0.6, 1.0])
async def test_enforce_threshold_or_higher_still_calls_base(probability):
    base = _RecordingEvaluator(requires_regen=True)
    evaluator = PrecheckQualityEvaluator(
        base, MockDecisionProvider(probability), PrecheckSettings(mode="enforce")
    )
    score = await evaluator.evaluate("q", "a", ["ctx"])
    assert len(base.calls) == 1
    assert score.overall == 0.5
    assert evaluator.requires_regeneration(score)
    assert score.raw_response["precheck"]["decision"] == "fallthrough"


@pytest.mark.asyncio
@pytest.mark.parametrize("probability", [None, True, -0.1, 1.1, float("nan"), float("inf")])
async def test_invalid_success_result_from_provider_fails_open(probability):
    base = _RecordingEvaluator()
    provider = MockDecisionProvider(sequence=[NoulResult(probability, "ok", 0, "mock")])
    evaluator = PrecheckQualityEvaluator(base, provider, PrecheckSettings(mode="enforce"))
    score = await evaluator.evaluate("q", "a", ["ctx"])
    assert len(base.calls) == 1
    assert score.raw_response["precheck"]["status"] == "parse_error"
    assert score.raw_response["precheck"]["decision"] == "fail_open"


@pytest.mark.asyncio
async def test_missing_jev_key_falls_through_without_creating_http_client():
    base = _RecordingEvaluator()
    provider = JevDecisionProvider(api_key="")
    evaluator = PrecheckQualityEvaluator(base, provider, PrecheckSettings(mode="enforce"))
    score = await evaluator.evaluate("q", "a", ["ctx"])
    assert score.raw_response["precheck"]["status"] == "missing_api_key"
    assert len(base.calls) == 1
    assert provider._client is None


@pytest.mark.asyncio
async def test_context_budget_only_applies_to_precheck_and_attributes_delegate():
    base = _RecordingEvaluator()
    base.custom_attribute = "forward compatible"
    provider = MockDecisionProvider()
    settings = PrecheckSettings(mode="shadow", max_context_chars=5, instructions="Custom rubric")
    evaluator = PrecheckQualityEvaluator(base, provider, settings)
    context = ["abcd", "efgh"]
    await evaluator.evaluate("query", "answer", context)
    assert provider.calls[0] == {
        "instructions": "Custom rubric",
        "state": {"query": "query", "answer": "answer", "context": "abcd\n"},
        "timeout_s": 0.5,
    }
    assert base.calls[0]["context"] == context == ["abcd", "efgh"]
    assert evaluator.custom_attribute == "forward compatible"
    base.quality_threshold = 0.8
    assert evaluator.quality_threshold == 0.8
    base.requires_regeneration = Mock(return_value=True)
    assert evaluator.requires_regeneration(base.last_score) is True
    base.requires_regeneration.assert_called_once_with(base.last_score)


def test_missing_base_evaluator_attribute_does_not_recurse():
    evaluator = object.__new__(PrecheckQualityEvaluator)
    with pytest.raises(AttributeError, match="base_evaluator"):
        _ = evaluator.base_evaluator


@pytest.mark.asyncio
async def test_annotation_preserves_future_quality_fields():
    @dataclass
    class ExtendedScore(QualityScore):
        evaluation_failed: bool = True

    class ExtendedEvaluator(_RecordingEvaluator):
        async def evaluate(self, query, answer, context):
            score = await super().evaluate(query, answer, context)
            return ExtendedScore(**vars(score))

    evaluator = PrecheckQualityEvaluator(
        ExtendedEvaluator(), MockDecisionProvider(0.01), PrecheckSettings(mode="shadow")
    )
    score = await evaluator.evaluate("q", "a", [])
    assert isinstance(score, ExtendedScore)
    assert score.evaluation_failed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["shadow", "enforce"])
async def test_caller_cancellation_propagates(mode):
    provider = MockDecisionProvider(delay_s=2)
    evaluator = PrecheckQualityEvaluator(_RecordingEvaluator(), provider, PrecheckSettings(mode=mode))
    task = asyncio.create_task(evaluator.evaluate("q", "a", []))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
