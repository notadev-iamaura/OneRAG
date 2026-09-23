"""오케스트레이터 수정 없이 두 진입점의 precheck/재생성 통합 검증."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.modules.core.decision import MockDecisionProvider
from app.modules.core.self_rag.orchestrator import SelfRAGOrchestrator
from app.modules.core.self_rag.precheck import PrecheckQualityEvaluator, PrecheckSettings
from tests.unit.self_rag.test_orchestrator_options import (
    _FakeComplexityCalculator,
    _FakeDoc,
    _RecordingGeneration,
    _RecordingRetrieval,
)
from tests.unit.self_rag.test_precheck_evaluator import _RecordingEvaluator

pytestmark = pytest.mark.asyncio


def _make_orchestrator(evaluator):
    retrieval = _RecordingRetrieval()
    generation = _RecordingGeneration()
    orchestrator = SelfRAGOrchestrator(
        complexity_calculator=_FakeComplexityCalculator(),
        evaluator=evaluator,
        retrieval_module=retrieval,
        generation_module=generation,
        retry_top_k=17,
    )
    return orchestrator, retrieval, generation


async def _run(orchestrator, entrypoint):
    options = {"response_language": "en"}
    if entrypoint == "process":
        return await orchestrator.process("q", "session", options=options)
    return await orchestrator.verify_existing_answer(
        "q", "existing answer",
        [_FakeDoc("original content"), SimpleNamespace(page_content="page content")],
        "session", options=options,
    )


@pytest.mark.parametrize("entrypoint", ["process", "verify_existing_answer"])
async def test_enforce_low_regenerates_and_only_evaluates_regenerated_answer(entrypoint):
    base = _RecordingEvaluator()
    provider = MockDecisionProvider(sequence=[0.01, 0.95])
    evaluator = PrecheckQualityEvaluator(base, provider, PrecheckSettings(mode="enforce"))
    orchestrator, retrieval, generation = _make_orchestrator(evaluator)

    result = await _run(orchestrator, entrypoint)

    assert result.regenerated is True
    assert result.used_self_rag is True
    assert result.tokens_used == 10
    assert result.answer == "생성된 답변"
    assert result.initial_quality.raw_response["precheck"]["decision"] == "short_circuit"
    assert result.final_quality.raw_response["precheck"]["decision"] == "fallthrough"
    assert len(base.calls) == 1
    assert base.calls[0]["answer"] == result.answer
    assert len(provider.calls) == 2
    assert retrieval.search_calls[-1] == {"response_language": "en", "limit": 17}
    expected_calls = 2 if entrypoint == "process" else 1
    assert len(retrieval.search_calls) == len(generation.generate_calls) == expected_calls
    assert all(call == {"response_language": "en"} for call in generation.generate_calls)
    if entrypoint == "verify_existing_answer":
        assert provider.calls[0]["state"]["context"] == "original content\n\npage content"


@pytest.mark.parametrize("entrypoint", ["process", "verify_existing_answer"])
@pytest.mark.parametrize("mode", ["shadow", "enforce"])
@pytest.mark.parametrize("requires_regen", [False, True])
async def test_shadow_low_and_enforce_error_match_base_outcome(entrypoint, mode, requires_regen):
    baseline, base_retrieval, base_generation = _make_orchestrator(
        _RecordingEvaluator(requires_regen)
    )
    expected = await _run(baseline, entrypoint)
    base = _RecordingEvaluator(requires_regen)
    provider = MockDecisionProvider(0.01, status="ok" if mode == "shadow" else "error")
    evaluator = PrecheckQualityEvaluator(base, provider, PrecheckSettings(mode=mode))
    orchestrator, retrieval, generation = _make_orchestrator(evaluator)

    result = await _run(orchestrator, entrypoint)

    assert result.answer == expected.answer
    assert result.regenerated == expected.regenerated
    assert result.used_self_rag == expected.used_self_rag
    assert result.tokens_used == expected.tokens_used
    assert result.metadata == expected.metadata
    assert result.initial_quality.overall == expected.initial_quality.overall
    assert result.final_quality.overall == expected.final_quality.overall
    assert retrieval.search_calls == base_retrieval.search_calls
    assert generation.generate_calls == base_generation.generate_calls
    assert result.initial_quality.raw_response["precheck"]["decision"] == (
        "shadow" if mode == "shadow" else "fail_open"
    )


@pytest.mark.parametrize("entrypoint", ["process", "verify_existing_answer"])
async def test_enforce_rechecks_regenerated_answer(entrypoint):
    base = _RecordingEvaluator()
    provider = MockDecisionProvider(0.01)
    evaluator = PrecheckQualityEvaluator(base, provider, PrecheckSettings(mode="enforce"))
    orchestrator, _, _ = _make_orchestrator(evaluator)
    result = await _run(orchestrator, entrypoint)
    assert result.regenerated is True
    assert len(provider.calls) == 2
    assert base.calls == []
    assert result.final_quality.grounding == 0.01
    assert result.final_quality.overall < 0.6
    assert evaluator.requires_regeneration(result.final_quality)


async def test_enforce_low_then_midband_regeneration_does_not_rollback():
    class MidbandEvaluator(_RecordingEvaluator):
        async def evaluate(self, query, answer, context):
            return replace(await super().evaluate(query, answer, context), overall=0.65)

    base = MidbandEvaluator()
    provider = MockDecisionProvider(sequence=[0.1, 0.95])
    evaluator = PrecheckQualityEvaluator(base, provider, PrecheckSettings(mode="enforce"))
    orchestrator, _, _ = _make_orchestrator(evaluator)

    result = await _run(orchestrator, "verify_existing_answer")

    assert result.initial_quality.overall == pytest.approx(0.1)
    assert result.final_quality.overall == pytest.approx(0.65)
    assert result.answer == "생성된 답변"
    assert result.regenerated is True
    assert result.metadata.get("reason") != "rollback"
    assert len(base.calls) == 1
