"""The returned answer, score, and evidence must describe the same attempt."""

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.core.routing import ComplexityResult
from app.modules.core.self_rag.evaluator import EvalStatus, QualityEvaluation, QualityScore
from app.modules.core.self_rag.orchestrator import SelfRAGOrchestrator, SelfRAGOutcome

pytestmark = pytest.mark.unit


def scored(value: float) -> QualityEvaluation:
    return QualityEvaluation(EvalStatus.OK, QualityScore(value, value, value, value, value, "ok", {}))


class Complexity:
    threshold = 0.5

    def __init__(self, needed: bool = True) -> None:
        self.needed = needed

    async def calculate(self, query: str) -> ComplexityResult:
        return ComplexityResult(0.9, 0.9, 0.9, 0.9, {})

    def requires_self_rag(self, result: ComplexityResult) -> bool:
        return self.needed


class Evaluator:
    quality_threshold = 0.8

    def __init__(self, evaluations: list[QualityEvaluation], available: bool = True) -> None:
        self.evaluations = evaluations
        self.is_available = available
        self.contexts: list[list[str]] = []
        self.raise_on_call: int | None = None

    async def evaluate(self, query: str, answer: str, context: list[str]) -> QualityEvaluation:
        self.contexts.append(context)
        if len(self.contexts) == self.raise_on_call:
            raise RuntimeError("evaluation failed")
        return self.evaluations.pop(0)

    def requires_regeneration(self, score: QualityScore) -> bool:
        return score.overall < self.quality_threshold


class Retrieval:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.docs = [SimpleNamespace(page_content="retry evidence")]
        self.fail = fail

    async def search(self, query: str, options: dict[str, Any]) -> list[Any]:
        self.calls.append(options)
        if self.fail:
            raise RuntimeError("retrieval failed")
        return self.docs


class Generation:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.contexts: list[list[Any]] = []
        self.fail = fail

    async def generate_answer(self, query: str, context_documents: list[Any], options: dict[str, Any]) -> Any:
        self.calls.append(options)
        self.contexts.append(context_documents)
        if self.fail:
            raise RuntimeError("generation failed")
        return SimpleNamespace(answer="retry answer", tokens_used=12)


def setup(evaluations: list[QualityEvaluation], *, available: bool = True,
          needed: bool = True, enabled: bool = True, rollback: bool = True,
          search_fails: bool = False, generation_fails: bool = False,
          initial_top_k: int | None = 5, retry_top_k: int | None = 15,
          max_retries: int | None = 1,
          ) -> tuple[SelfRAGOrchestrator, Evaluator, Retrieval, Generation]:
    evaluator = Evaluator(evaluations, available)
    retrieval = Retrieval(search_fails)
    generation = Generation(generation_fails)
    orchestrator = SelfRAGOrchestrator(Complexity(needed), evaluator, retrieval, generation,
                                      initial_top_k=initial_top_k, retry_top_k=retry_top_k,
                                      max_retries=max_retries, enabled=enabled,
                                      enable_rollback=rollback)
    return orchestrator, evaluator, retrieval, generation


async def verify(orchestrator: SelfRAGOrchestrator) -> Any:
    return await orchestrator.verify_existing_answer(
        "question", "original answer", [SimpleNamespace(page_content="original evidence")],
        "session", options={"response_language": "en"})


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"enabled": False}, {"needed": False}, {"available": False}])
async def test_skipped_without_retry(kwargs: dict[str, bool]) -> None:
    orchestrator, evaluator, retrieval, generation = setup(
        [],
        enabled=kwargs.get("enabled", True),
        needed=kwargs.get("needed", True),
        available=kwargs.get("available", True),
    )
    result = await verify(orchestrator)
    assert result.outcome is SelfRAGOutcome.SKIPPED
    assert result.answer == "original answer"
    assert not evaluator.contexts and not retrieval.calls and not generation.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("evaluation,outcome", [
    (scored(0.9), SelfRAGOutcome.OK),
    (QualityEvaluation(EvalStatus.FAILED, None), SelfRAGOutcome.EVAL_FAILED),
    (QualityEvaluation(EvalStatus.TIMEOUT, None), SelfRAGOutcome.EVAL_TIMEOUT),
])
async def test_initial_evaluation_without_retry(evaluation: QualityEvaluation,
                                                 outcome: SelfRAGOutcome) -> None:
    orchestrator, _, retrieval, generation = setup([evaluation])
    result = await verify(orchestrator)
    assert result.outcome is outcome
    assert result.answer == "original answer"
    assert result.final_quality is result.initial_quality
    assert not retrieval.calls and not generation.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("final,rollback,expected,reason", [
    (scored(0.85), True, SelfRAGOutcome.REGENERATED, None),
    (scored(0.5), True, SelfRAGOutcome.ROLLED_BACK, "quality_degraded"),
    (scored(0.5), False, SelfRAGOutcome.REGENERATED, None),
    (QualityEvaluation(EvalStatus.FAILED, None), True, SelfRAGOutcome.ROLLED_BACK, "final_eval_failed"),
    (QualityEvaluation(EvalStatus.TIMEOUT, None), True, SelfRAGOutcome.ROLLED_BACK, "final_eval_timeout"),
])
async def test_retry_matrix(final: QualityEvaluation, rollback: bool, expected: SelfRAGOutcome,
                            reason: str | None) -> None:
    orchestrator, evaluator, retrieval, generation = setup([scored(0.7), final], rollback=rollback)
    result = await verify(orchestrator)
    assert result.outcome is expected
    assert result.rollback_reason == reason
    assert result.final_eval_status is final.status
    assert generation.calls[0]["max_context_documents"] == orchestrator.retry_top_k
    assert evaluator.contexts[-1] == ["retry evidence"]
    if expected is SelfRAGOutcome.REGENERATED:
        assert result.answer == "retry answer"
        assert result.final_quality is final.score
        assert result.selected_documents == retrieval.docs
    else:
        assert result.answer == "original answer"
        assert result.final_quality is result.initial_quality
        assert result.selected_documents is None
    if reason == "quality_degraded":
        assert result.retry_quality is final.score


@pytest.mark.asyncio
async def test_retry_error_keeps_initial_score() -> None:
    orchestrator, _, retrieval, generation = setup([scored(0.7)], search_fails=True)
    result = await verify(orchestrator)
    assert result.outcome is SelfRAGOutcome.ROLLED_BACK
    assert result.rollback_reason == "regeneration_error"
    assert result.final_quality is result.initial_quality
    assert result.final_quality.overall == 0.7
    assert len(retrieval.calls) == 1 and not generation.calls


@pytest.mark.asyncio
async def test_none_constructor_limits_use_defaults_in_regeneration() -> None:
    orchestrator, _, retrieval, generation = setup(
        [scored(0.7), scored(0.85)],
        initial_top_k=None, retry_top_k=None, max_retries=None,
    )
    result = await verify(orchestrator)
    assert (orchestrator.initial_top_k, orchestrator.retry_top_k, orchestrator.max_retries) == (5, 15, 1)
    assert retrieval.calls[0]["limit"] == 15
    assert generation.calls[0]["max_context_documents"] == 15
    assert type(generation.calls[0]["max_context_documents"]) is int
    assert result.outcome is SelfRAGOutcome.REGENERATED


@pytest.mark.asyncio
async def test_retry_documents_match_prompt_and_evaluation_limit() -> None:
    orchestrator, evaluator, retrieval, generation = setup(
        [scored(0.7), scored(0.85)], retry_top_k=30,
    )
    retrieval.docs = [SimpleNamespace(page_content=f"retry {i}") for i in range(30)]
    result = await verify(orchestrator)
    assert generation.calls[0]["max_context_documents"] == 20
    assert generation.contexts[0] == retrieval.docs[:20]
    assert evaluator.contexts[-1] == [doc.page_content for doc in retrieval.docs[:20]]
    assert result.selected_documents == retrieval.docs[:20]


@pytest.mark.asyncio
async def test_generation_error_rolls_back_with_initial_score() -> None:
    orchestrator, _, _, generation = setup([scored(0.7)], generation_fails=True)
    result = await verify(orchestrator)
    assert len(generation.calls) == 1
    assert result.outcome is SelfRAGOutcome.ROLLED_BACK
    assert result.rollback_reason == "regeneration_error"
    assert result.final_quality is result.initial_quality
    assert result.final_quality.overall == 0.7
    assert result.answer == "original answer"


@pytest.mark.asyncio
async def test_final_evaluation_exception_rolls_back_with_initial_score() -> None:
    orchestrator, evaluator, _, generation = setup([scored(0.7)])
    evaluator.raise_on_call = 2
    result = await verify(orchestrator)
    assert len(generation.calls) == 1
    assert len(evaluator.contexts) == 2
    assert result.outcome is SelfRAGOutcome.ROLLED_BACK
    assert result.rollback_reason == "regeneration_error"
    assert result.final_quality is result.initial_quality
    assert result.final_quality.overall == 0.7
    assert result.answer == "original answer"
