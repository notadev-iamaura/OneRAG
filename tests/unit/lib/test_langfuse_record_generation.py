"""record_generation 공통 헬퍼 + LangChain(self_rag) generation 계측 회귀 테스트.

배경(2026-06-18 "모든 LLM 호출 비용" PR-B):
    llm_client를 경유하지 않는 호출처(LangChain self_rag evaluator, LLM 리랭커 3종)를
    계측하기 위해 langfuse_client.record_generation() 공통 헬퍼를 추가했다. 각 호출처는
    @observe(as_type="generation")로 감싸지고, 응답에서 추출한 model/usage를
    record_generation으로 기록한다.

검증 포인트:
    - record_generation이 usage(input/output/total/TOKENS)·model_parameters·output을 기록
    - 토큰이 모두 0이면 usage 생략(노이즈 방지), total 0이면 prompt+completion 보정
    - 기록 실패는 비치명적(예외 흡수)
    - self_rag evaluator가 LangChain usage_metadata(input/output/total_tokens)에서
      record_generation을 호출(키 매핑 회귀 가드)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.lib.langfuse_client as lf
from app.lib.langfuse_client import record_generation


class _SpyContext:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def update_current_observation(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class TestRecordGeneration:
    def test_records_usage_and_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spy = _SpyContext()
        monkeypatch.setattr(lf, "langfuse_context", spy)
        record_generation(
            model="m1",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            model_parameters={"temperature": 0.0},
            output="결과",
        )
        call = spy.calls[0]
        assert call["model"] == "m1"
        assert call["usage"] == {"input": 10, "output": 20, "total": 30, "unit": "TOKENS"}
        assert call["model_parameters"] == {"temperature": 0.0}
        assert call["output"] == "결과"

    def test_omits_usage_when_all_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spy = _SpyContext()
        monkeypatch.setattr(lf, "langfuse_context", spy)
        record_generation(model="m1")
        assert spy.calls[0]["model"] == "m1"
        assert "usage" not in spy.calls[0]
        assert "output" not in spy.calls[0]

    def test_total_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spy = _SpyContext()
        monkeypatch.setattr(lf, "langfuse_context", spy)
        record_generation(model="m1", prompt_tokens=7, completion_tokens=5, total_tokens=0)
        assert spy.calls[0]["usage"]["total"] == 12

    def test_failure_is_non_fatal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Exploding:
            def update_current_observation(self, **kwargs: Any) -> None:
                raise RuntimeError("langfuse down")

        monkeypatch.setattr(lf, "langfuse_context", _Exploding())
        # 예외를 흡수하므로 호출이 깨지지 않는다
        record_generation(model="m1", prompt_tokens=1, completion_tokens=2, total_tokens=3)


@pytest.mark.asyncio
async def test_self_rag_evaluator_records_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """self_rag evaluator가 LangChain usage_metadata에서 generation을 기록한다."""
    from app.modules.core.self_rag.evaluator import LLMQualityEvaluator

    spy = _SpyContext()
    monkeypatch.setattr(lf, "langfuse_context", spy)

    # api_key=None → self.llm=None으로 생성된 뒤 mock LLM을 주입
    evaluator = LLMQualityEvaluator(api_key=None)

    resp = MagicMock()
    resp.content = (
        '{"relevance": 0.9, "grounding": 0.8, "completeness": 0.7, '
        '"confidence": 0.85, "reasoning": "근거 충분"}'
    )
    resp.usage_metadata = {"input_tokens": 50, "output_tokens": 20, "total_tokens": 70}
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=resp)
    mock_llm.model = "gemini-2.0-flash"
    evaluator.llm = mock_llm

    await evaluator.evaluate("질문", "답변", ["문서1"])

    # record_generation → langfuse_context.update_current_observation이 실제 토큰으로 호출됨
    matching = [
        c
        for c in spy.calls
        if c.get("model") == "gemini-2.0-flash"
        and c.get("usage") == {"input": 50, "output": 20, "total": 70, "unit": "TOKENS"}
    ]
    assert matching, f"evaluator usage 기록 누락: {spy.calls}"


@pytest.mark.asyncio
async def test_sql_generator_records_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLGenerator(OpenRouter OpenAI SDK)가 response.usage에서 generation을 기록한다."""
    from app.modules.core.sql_search.sql_generator import SQLGenerator

    spy = _SpyContext()
    monkeypatch.setattr(lf, "langfuse_context", spy)

    gen = SQLGenerator(config={"model": "anthropic/claude-opus-4.5"}, api_key="test-key")

    resp = MagicMock()
    resp.choices = [
        MagicMock(message=MagicMock(content='{"needs_sql": false, "explanation": "불필요"}'))
    ]
    resp.usage = MagicMock(prompt_tokens=30, completion_tokens=15, total_tokens=45)
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = resp
    gen._client = mock_client

    await gen.generate("이번 달 매출은?")

    matching = [
        c
        for c in spy.calls
        if c.get("model") == "anthropic/claude-opus-4.5"
        and c.get("usage") == {"input": 30, "output": 15, "total": 45, "unit": "TOKENS"}
    ]
    assert matching, f"SQL generator usage 기록 누락: {spy.calls}"
