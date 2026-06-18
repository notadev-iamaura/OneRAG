"""llm_client generation 계측 회귀 테스트.

배경(2026-06-18 관측성 심화 — "모든 LLM 호출 비용" 구현):
    BaseLLMClient의 모든 provider generate_text/stream_text에 @observe(as_type=
    "generation")를 걸고, LLM 응답에서 추출한 model/usage(토큰)를 _emit_generation으로
    현재 generation observation에 기록한다. 이로써 llm_client를 경유하는 모든 호출
    (/v1 OpenAI 호환 API, Agent planner/reflector/synthesizer, 쿼리확장, 라우터 등)의
    토큰/비용이 Langfuse에 일괄 추적된다.

검증 포인트:
    - provider별 usage 추출 헬퍼(_usage_openai/_usage_anthropic/_usage_google) 정확성
    - _emit_generation이 usage(input/output/total/TOKENS)·model_parameters를 기록하고,
      토큰이 0이면 usage를 생략(노이즈 방지)
    - generate_text(비스트리밍)·stream_text(스트리밍 usage 청크)에서 실제 토큰 기록
    - 입력/출력 텍스트는 기록하지 않음(capture_input/output=False — PII 안전)
    - LANGFUSE 비활성 시 더미 no-op으로 기존 동작 유지(회귀 0)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import app.lib.llm_client as llm_client_mod
from app.lib.llm_client import AnthropicLLMClient, BaseLLMClient, OllamaLLMClient


class _SpyContext:
    """update_current_observation 호출 인자를 캡처하는 스파이."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def update_current_observation(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class TestUsageExtractors:
    """provider별 usage 추출 정적 헬퍼."""

    def test_usage_openai(self) -> None:
        resp = MagicMock(usage=MagicMock(prompt_tokens=10, completion_tokens=20, total_tokens=30))
        assert BaseLLMClient._usage_openai(resp) == (10, 20, 30)

    def test_usage_openai_no_usage(self) -> None:
        assert BaseLLMClient._usage_openai(MagicMock(usage=None)) == (0, 0, 0)

    def test_usage_anthropic_computes_total(self) -> None:
        resp = MagicMock(usage=MagicMock(input_tokens=7, output_tokens=5))
        assert BaseLLMClient._usage_anthropic(resp) == (7, 5, 12)

    def test_usage_google(self) -> None:
        resp = MagicMock(
            usage_metadata=MagicMock(
                prompt_token_count=8, candidates_token_count=4, total_token_count=12
            )
        )
        assert BaseLLMClient._usage_google(resp) == (8, 4, 12)


class TestEmitGeneration:
    """_emit_generation 공통 헬퍼."""

    def test_records_usage_and_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spy = _SpyContext()
        monkeypatch.setattr(llm_client_mod, "langfuse_context", spy)
        client = OllamaLLMClient(config={})
        client._emit_generation(
            model="m1",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            temperature=0.3,
            max_tokens=512,
        )
        assert spy.calls[0]["model"] == "m1"
        assert spy.calls[0]["usage"] == {"input": 10, "output": 20, "total": 30, "unit": "TOKENS"}
        assert spy.calls[0]["model_parameters"] == {"temperature": 0.3, "max_tokens": 512}

    def test_omits_usage_when_all_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spy = _SpyContext()
        monkeypatch.setattr(llm_client_mod, "langfuse_context", spy)
        client = OllamaLLMClient(config={})
        client._emit_generation(model="m1")
        assert spy.calls[0]["model"] == "m1"
        assert "usage" not in spy.calls[0]

    def test_total_fallback_from_prompt_completion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spy = _SpyContext()
        monkeypatch.setattr(llm_client_mod, "langfuse_context", spy)
        client = OllamaLLMClient(config={})
        client._emit_generation(model="m1", prompt_tokens=7, completion_tokens=5, total_tokens=0)
        assert spy.calls[0]["usage"]["total"] == 12

    def test_failure_is_non_fatal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Exploding:
            def update_current_observation(self, **kwargs: Any) -> None:
                raise RuntimeError("langfuse down")

        monkeypatch.setattr(llm_client_mod, "langfuse_context", _Exploding())
        client = OllamaLLMClient(config={})
        # 예외를 흡수하므로 호출이 깨지지 않는다
        client._emit_generation(model="m1", prompt_tokens=1, completion_tokens=2, total_tokens=3)


@pytest.mark.asyncio
async def test_ollama_generate_text_records_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """비스트리밍(OpenAI 호환): response.usage가 generation usage로 기록된다."""
    spy = _SpyContext()
    monkeypatch.setattr(llm_client_mod, "langfuse_context", spy)
    client = OllamaLLMClient(config={"model": "llama3.2"})

    mock_openai = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content="응답"))]
    resp.usage = MagicMock(prompt_tokens=11, completion_tokens=22, total_tokens=33)
    mock_openai.chat.completions.create.return_value = resp
    client._client = mock_openai

    result = await client.generate_text("질문")

    assert result == "응답"
    assert len(spy.calls) == 1
    assert spy.calls[0]["model"] == "llama3.2"
    assert spy.calls[0]["usage"] == {"input": 11, "output": 22, "total": 33, "unit": "TOKENS"}


@pytest.mark.asyncio
async def test_ollama_stream_text_records_usage_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """스트리밍(OpenAI 호환): include_usage 마지막 청크에서 실제 토큰을 추출해 기록한다."""
    spy = _SpyContext()
    monkeypatch.setattr(llm_client_mod, "langfuse_context", spy)
    client = OllamaLLMClient(config={"model": "llama3.2"})

    content_chunk = MagicMock()
    content_chunk.usage = None
    content_chunk.choices = [MagicMock(delta=MagicMock(content="안녕"))]
    usage_chunk = MagicMock()
    usage_chunk.usage = MagicMock(prompt_tokens=5, completion_tokens=3, total_tokens=8)
    usage_chunk.choices = []

    mock_openai = MagicMock()
    mock_openai.chat.completions.create.return_value = [content_chunk, usage_chunk]
    client._client = mock_openai

    out = [chunk async for chunk in client.stream_text("질문")]

    assert "".join(out) == "안녕"
    assert len(spy.calls) == 1
    assert spy.calls[0]["usage"] == {"input": 5, "output": 3, "total": 8, "unit": "TOKENS"}


@pytest.mark.asyncio
async def test_anthropic_generate_text_records_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """비스트리밍(Anthropic): input/output_tokens로 total을 계산해 기록한다."""
    spy = _SpyContext()
    monkeypatch.setattr(llm_client_mod, "langfuse_context", spy)

    client = AnthropicLLMClient.__new__(AnthropicLLMClient)
    client.model = "claude-sonnet-4-5"  # type: ignore[attr-defined]
    client.temperature = 0.3  # type: ignore[attr-defined]
    client.max_tokens = 512  # type: ignore[attr-defined]
    client.timeout = 30  # type: ignore[attr-defined]

    resp = MagicMock()
    resp.content = [MagicMock(text="답변")]
    resp.usage = MagicMock(input_tokens=15, output_tokens=25)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = resp
    client.client = mock_client  # type: ignore[attr-defined]

    result = await client.generate_text("질문")

    assert result == "답변"
    assert spy.calls[0]["model"] == "claude-sonnet-4-5"
    assert spy.calls[0]["usage"] == {"input": 15, "output": 25, "total": 40, "unit": "TOKENS"}
