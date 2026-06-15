"""Self-RAG 오케스트레이터의 options 처리 회귀 테스트.

검증 대상(차용 #2):
1. 호출자가 전달한 ``options`` dict가 process()/verify_existing_answer()
   실행 후에도 변형(mutation)되지 않는다(특히 caller의 ``limit`` 키 미오염).
2. generate_answer()에 빈 dict가 아니라 사용자 옵션(예: response_language)이
   그대로 전달된다(언어/모델/스타일 옵션 소실 방지).
"""

from typing import Any

import pytest

from app.modules.core.routing import ComplexityResult
from app.modules.core.self_rag.evaluator import QualityScore
from app.modules.core.self_rag.orchestrator import SelfRAGOrchestrator


class _FakeComplexityCalculator:
    """항상 Self-RAG가 필요하다고 판단하는 복잡도 계산기 더블."""

    threshold = 0.7

    async def calculate(self, query: str) -> ComplexityResult:
        return ComplexityResult(0.9, 0.9, 0.9, 0.9, {})

    def requires_self_rag(self, complexity: ComplexityResult) -> bool:
        return True


class _FakeEvaluator:
    """초기 품질을 충분하다고 판단해 재생성 없이 종료시키는 평가기 더블."""

    quality_threshold = 0.75

    def __init__(self, requires_regen: bool = False) -> None:
        self._requires_regen = requires_regen

    async def evaluate(self, query: str, answer: str, context: list[str]) -> QualityScore:
        overall = 0.5 if self._requires_regen else 0.9
        return QualityScore(
            relevance=overall,
            grounding=overall,
            completeness=overall,
            confidence=overall,
            overall=overall,
            reasoning="테스트용 평가 결과",
            raw_response={},
        )

    def requires_regeneration(self, quality: QualityScore) -> bool:
        return self._requires_regen


class _FakeDoc:
    def __init__(self, content: str) -> None:
        self.content = content


class _RecordingRetrieval:
    """search()에 전달된 options를 기록하는 검색 모듈 더블."""

    def __init__(self) -> None:
        self.search_calls: list[dict[str, Any]] = []

    async def search(self, query: str, options: dict[str, Any]) -> list[_FakeDoc]:
        self.search_calls.append(options)
        return [_FakeDoc("문서 본문")]


class _GenerationResult:
    def __init__(self, answer: str, tokens_used: int = 10) -> None:
        self.answer = answer
        self.tokens_used = tokens_used


class _RecordingGeneration:
    """generate_answer()에 전달된 options를 기록하는 생성 모듈 더블."""

    def __init__(self) -> None:
        self.generate_calls: list[dict[str, Any]] = []

    async def generate_answer(
        self, query: str, context_documents: list[Any], options: dict[str, Any]
    ) -> _GenerationResult:
        self.generate_calls.append(options)
        return _GenerationResult("생성된 답변")


def _make_orchestrator(
    *, requires_regen: bool = False, enabled: bool = True
) -> tuple[SelfRAGOrchestrator, _RecordingRetrieval, _RecordingGeneration]:
    retrieval = _RecordingRetrieval()
    generation = _RecordingGeneration()
    orchestrator = SelfRAGOrchestrator(
        complexity_calculator=_FakeComplexityCalculator(),
        evaluator=_FakeEvaluator(requires_regen=requires_regen),
        retrieval_module=retrieval,
        generation_module=generation,
        enabled=enabled,
    )
    return orchestrator, retrieval, generation


@pytest.mark.asyncio
async def test_process_does_not_mutate_caller_options() -> None:
    """process()는 호출자의 options dict를 변형하지 않아야 한다."""
    orchestrator, _, _ = _make_orchestrator()
    user_options = {"response_language": "en"}

    await orchestrator.process("복잡한 질문", "session-1", options=user_options)

    # 호출자 dict에 limit 키가 주입되어서는 안 된다
    assert user_options == {"response_language": "en"}
    assert "limit" not in user_options


@pytest.mark.asyncio
async def test_process_passes_user_options_to_generation() -> None:
    """process()는 generate_answer에 사용자 옵션을 그대로 전달해야 한다."""
    orchestrator, retrieval, generation = _make_orchestrator()
    user_options = {"response_language": "en", "model": "claude"}

    await orchestrator.process("복잡한 질문", "session-1", options=user_options)

    # 검색 options에는 사용자 옵션 + limit가 모두 있어야 한다
    assert retrieval.search_calls[0]["response_language"] == "en"
    assert retrieval.search_calls[0]["limit"] == orchestrator.initial_top_k
    # 생성 options에는 사용자 옵션이 보존되어야 한다(빈 dict 아님)
    assert generation.generate_calls[0]["response_language"] == "en"
    assert generation.generate_calls[0]["model"] == "claude"


@pytest.mark.asyncio
async def test_process_regeneration_preserves_user_options() -> None:
    """재생성 경로에서도 사용자 옵션이 소실되지 않아야 한다."""
    orchestrator, retrieval, generation = _make_orchestrator(requires_regen=True)
    user_options = {"response_language": "en"}

    await orchestrator.process("복잡한 질문", "session-1", options=user_options)

    # 초기/재생성 검색 모두 사용자 옵션을 유지하며 limit만 달라야 한다
    assert retrieval.search_calls[0]["limit"] == orchestrator.initial_top_k
    assert retrieval.search_calls[1]["limit"] == orchestrator.retry_top_k
    assert all(call["response_language"] == "en" for call in retrieval.search_calls)
    # 호출자 dict는 마지막 limit(retry_top_k)로 오염되지 않아야 한다
    assert "limit" not in user_options
    # 재생성 generate_answer도 사용자 옵션 보존
    assert generation.generate_calls[-1]["response_language"] == "en"


@pytest.mark.asyncio
async def test_regular_flow_does_not_mutate_caller_options() -> None:
    """Self-RAG 비활성 시 _regular_flow도 호출자 options를 변형하지 않아야 한다."""
    orchestrator, retrieval, generation = _make_orchestrator(enabled=False)
    user_options = {"response_language": "ja"}

    await orchestrator.process("질문", "session-1", options=user_options)

    assert "limit" not in user_options
    assert retrieval.search_calls[0]["response_language"] == "ja"
    assert generation.generate_calls[0]["response_language"] == "ja"


@pytest.mark.asyncio
async def test_verify_existing_answer_accepts_and_uses_options() -> None:
    """verify_existing_answer는 options 파라미터를 받아 재생성에 활용해야 한다."""
    orchestrator, retrieval, generation = _make_orchestrator(requires_regen=True)
    user_options = {"response_language": "en"}
    existing_docs = [_FakeDoc("기존 문서")]

    await orchestrator.verify_existing_answer(
        "복잡한 질문",
        "기존 답변",
        existing_docs,
        "session-1",
        options=user_options,
    )

    # 재검색 시 사용자 옵션 + retry limit가 함께 전달되어야 한다
    assert retrieval.search_calls[0]["limit"] == orchestrator.retry_top_k
    assert retrieval.search_calls[0]["response_language"] == "en"
    # 재생성에도 사용자 옵션 전달
    assert generation.generate_calls[0]["response_language"] == "en"
    # 호출자 dict 미오염
    assert user_options == {"response_language": "en"}
