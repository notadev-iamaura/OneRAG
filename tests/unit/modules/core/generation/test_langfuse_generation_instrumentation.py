"""Langfuse generation 계측 회귀 테스트.

배경(2026-06-18 관측성 심화 — deferred 항목 구현):
    LLM 호출별 model/토큰/비용을 Langfuse `generation` 객체로 기록하도록
    `_generate_with_model`(비스트리밍)과 `stream_answer`(스트리밍)에
    `@observe(as_type="generation")` + `langfuse_context.update_current_observation`을
    배선했다. 스트리밍은 `stream_options={"include_usage": True}`로 받은 usage 청크에서
    정확한 토큰을 추출하고(없으면 청크 수×5 추정 폴백), 첫 토큰 시각을 TTFT로 남긴다.

검증 포인트:
    - 비스트리밍: response.usage(prompt/completion/total)가 generation observation의
      usage(input/output/total, unit=TOKENS)로 정확히 전달된다.
    - 스트리밍: usage 청크에서 실제 토큰을 추출해 기록하고, completion_start_time(TTFT)을
      datetime으로 남긴다.
    - 스트리밍에서 usage 청크가 없으면(레거시/미지원 게이트웨이) 토큰 추정 폴백으로
      동작하며 generation 기록은 usage 없이 model만 남긴다(회귀 0).
    - 관측 실패는 비치명적: langfuse_context가 예외를 던져도 답변 생성은 정상 진행한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

import app.modules.core.generation.generator as generator_mod
from app.modules.core.generation.generator import GenerationModule


class _SpyLangfuseContext:
    """update_current_observation 호출 인자를 캡처하는 스파이.

    실제 langfuse_context(또는 더미)를 대체해 generation 기록 인자를 검증한다.
    """

    def __init__(self) -> None:
        self.observation_calls: list[dict[str, Any]] = []
        self.trace_calls: list[dict[str, Any]] = []

    def update_current_observation(self, **kwargs: Any) -> None:
        self.observation_calls.append(kwargs)

    def update_current_trace(self, **kwargs: Any) -> None:
        self.trace_calls.append(kwargs)


# ----------------------------------------------------------------------------
# 비스트리밍 응답 스텁 (OpenAI/OpenRouter 호환)
# ----------------------------------------------------------------------------
class _Usage:
    def __init__(self, prompt: int, completion: int, total: int) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = total


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _RespChoice:
    def __init__(self, content: str) -> None:
        self.message = _Message(content)


class _Response:
    def __init__(self, content: str, usage: _Usage | None) -> None:
        self.choices = [_RespChoice(content)]
        self.usage = usage


# ----------------------------------------------------------------------------
# 스트리밍 청크 스텁
# ----------------------------------------------------------------------------
class _Delta:
    def __init__(self, content: str) -> None:
        self.content = content


class _StreamChoice:
    def __init__(self, content: str) -> None:
        self.delta = _Delta(content)


class _ContentChunk:
    """콘텐츠 토큰 청크(choices 있음, usage 없음)."""

    def __init__(self, content: str) -> None:
        self.choices = [_StreamChoice(content)]
        self.usage = None


class _UsageChunk:
    """마지막 usage 청크(choices 빔, usage 채워짐 — include_usage 응답)."""

    def __init__(self, usage: _Usage) -> None:
        self.choices = []
        self.usage = usage


def _make_gen(spy: _SpyLangfuseContext, response: _Response) -> GenerationModule:
    """비스트리밍 _generate_with_model 검증용 GenerationModule 스텁."""
    gen = GenerationModule.__new__(GenerationModule)
    gen.provider = "openrouter"  # type: ignore[attr-defined]
    gen.default_model = "m1"  # type: ignore[attr-defined]
    gen._privacy_enabled = False  # type: ignore[attr-defined]
    gen.privacy_masker = None  # type: ignore[attr-defined]

    def _create(**kw: Any) -> object:
        return response

    class _Client:
        class chat:
            class completions:
                create = staticmethod(_create)

    gen.client = _Client()  # type: ignore[attr-defined]
    gen._build_context = lambda docs, options=None: "ctx"  # type: ignore[assignment]

    async def _build_prompt(*a: object, **k: object) -> tuple[str, str]:
        return ("sys", "user")

    gen._build_prompt = _build_prompt  # type: ignore[assignment]
    gen._get_model_settings = lambda m, o: {  # type: ignore[assignment]
        "max_tokens": 512,
        "temperature": 0.3,
        "timeout": 5,
    }
    return gen


def _make_stream_gen(
    spy: _SpyLangfuseContext, chunks: list[Any]
) -> GenerationModule:
    """스트리밍 stream_answer 검증용 GenerationModule 스텁(PII 마스킹 off)."""
    gen = GenerationModule.__new__(GenerationModule)
    gen.provider = "openrouter"  # type: ignore[attr-defined]
    gen.default_model = "m1"  # type: ignore[attr-defined]
    gen.auto_fallback = False  # type: ignore[attr-defined]
    gen.fallback_models = []  # type: ignore[attr-defined]
    gen._privacy_enabled = False  # type: ignore[attr-defined]
    gen.privacy_masker = None  # type: ignore[attr-defined]
    gen.stats = {"total_generations": 0, "fallback_count": 0, "error_count": 0}  # type: ignore[attr-defined]
    gen._update_stats_calls = []  # type: ignore[attr-defined]

    def _create(**kw: Any) -> object:
        return object()

    class _Client:
        class chat:
            class completions:
                create = staticmethod(_create)

    gen.client = _Client()  # type: ignore[attr-defined]
    gen._build_context = lambda docs, options=None: "ctx"  # type: ignore[assignment]

    async def _build_prompt(*a: object, **k: object) -> tuple[str, str]:
        return ("sys", "user")

    gen._build_prompt = _build_prompt  # type: ignore[assignment]
    gen._get_model_settings = lambda m, o: {  # type: ignore[assignment]
        "max_tokens": 512,
        "temperature": 0.3,
        "timeout": 5,
    }

    def _update_stats(model: str, tokens: int, gtime: float) -> None:
        gen._update_stats_calls.append((model, tokens))  # type: ignore[attr-defined]

    gen._update_stats = _update_stats  # type: ignore[assignment]

    async def _iterate(stream: Any) -> Any:
        for c in chunks:
            yield c

    gen._iterate_stream_chunks = _iterate  # type: ignore[assignment]
    return gen


@pytest.mark.asyncio
async def test_nonstreaming_records_generation_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """비스트리밍: response.usage가 generation observation usage로 정확히 전달된다."""
    spy = _SpyLangfuseContext()
    monkeypatch.setattr(generator_mod, "langfuse_context", spy)

    gen = _make_gen(spy, _Response("답변입니다", _Usage(prompt=10, completion=20, total=30)))
    result = await gen._generate_with_model(
        model="anthropic/claude-sonnet-4.5",
        query="질문",
        context_documents=[{"content": "doc"}],
        options={},
    )

    assert result.answer == "답변입니다"
    assert result.tokens_used == 30
    assert len(spy.observation_calls) == 1
    call = spy.observation_calls[0]
    assert call["model"] == "anthropic/claude-sonnet-4.5"
    assert call["usage"] == {"input": 10, "output": 20, "total": 30, "unit": "TOKENS"}
    assert call["model_parameters"] == {"temperature": 0.3, "max_tokens": 512}
    assert call["output"] == "답변입니다"


@pytest.mark.asyncio
async def test_nonstreaming_total_token_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """비스트리밍: total_tokens=0이면 prompt+completion으로 보정해 기록한다."""
    spy = _SpyLangfuseContext()
    monkeypatch.setattr(generator_mod, "langfuse_context", spy)

    gen = _make_gen(spy, _Response("답변", _Usage(prompt=7, completion=5, total=0)))
    await gen._generate_with_model(
        model="m1", query="q", context_documents=[{"content": "d"}], options={}
    )

    call = spy.observation_calls[0]
    assert call["usage"]["total"] == 12  # 7 + 5 보정


@pytest.mark.asyncio
async def test_streaming_extracts_real_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """스트리밍: usage 청크에서 실제 토큰을 추출하고 TTFT를 datetime으로 남긴다."""
    spy = _SpyLangfuseContext()
    monkeypatch.setattr(generator_mod, "langfuse_context", spy)

    chunks = [
        _ContentChunk("안녕"),
        _ContentChunk("하세요"),
        _UsageChunk(_Usage(prompt=100, completion=40, total=140)),
    ]
    gen = _make_stream_gen(spy, chunks)

    emitted = [c async for c in gen.stream_answer("질문", [{"content": "doc"}], {})]

    assert "".join(emitted) == "안녕하세요"
    # 실제 usage가 generation observation에 기록됨
    assert len(spy.observation_calls) == 1
    call = spy.observation_calls[0]
    assert call["model"] == "m1"
    assert call["usage"] == {"input": 100, "output": 40, "total": 140, "unit": "TOKENS"}
    assert isinstance(call["completion_start_time"], datetime)
    # 통계도 실제 토큰(140)으로 업데이트됨 (청크 수×5 추정이 아님)
    assert gen._update_stats_calls == [("m1", 140)]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_streaming_falls_back_to_estimate_without_usage_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """스트리밍: usage 청크가 없으면 청크 수×5 추정으로 폴백(회귀 0)."""
    spy = _SpyLangfuseContext()
    monkeypatch.setattr(generator_mod, "langfuse_context", spy)

    chunks = [_ContentChunk("a"), _ContentChunk("b"), _ContentChunk("c")]
    gen = _make_stream_gen(spy, chunks)

    emitted = [c async for c in gen.stream_answer("질문", [{"content": "doc"}], {})]

    assert "".join(emitted) == "abc"
    # usage 없음 → 추정 토큰(3×5=15)으로 통계 업데이트
    assert gen._update_stats_calls == [("m1", 15)]  # type: ignore[attr-defined]
    # generation observation은 model만 남고 usage는 미포함(토큰 0이라 생략)
    call = spy.observation_calls[0]
    assert call["model"] == "m1"
    assert "usage" not in call


@pytest.mark.asyncio
async def test_observation_failure_is_non_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """관측 실패는 비치명적: update_current_observation이 예외를 던져도 답변은 정상 반환."""

    class _ExplodingContext:
        def update_current_observation(self, **kwargs: Any) -> None:
            raise RuntimeError("langfuse down")

        def update_current_trace(self, **kwargs: Any) -> None:
            raise RuntimeError("langfuse down")

    monkeypatch.setattr(generator_mod, "langfuse_context", _ExplodingContext())

    gen = _make_gen(_SpyLangfuseContext(), _Response("정상답변", _Usage(1, 2, 3)))
    result = await gen._generate_with_model(
        model="m1", query="q", context_documents=[{"content": "d"}], options={}
    )
    # 관측이 폭발해도 답변 생성은 graceful하게 완료된다
    assert result.answer == "정상답변"
    assert result.tokens_used == 3


@pytest.mark.asyncio
async def test_nonstreaming_output_is_masked_before_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """비스트리밍: generation output은 PII 마스킹 후 텍스트로 기록된다(raw 미유출)."""
    from app.modules.core.privacy.masker import PrivacyMasker

    spy = _SpyLangfuseContext()
    monkeypatch.setattr(generator_mod, "langfuse_context", spy)

    gen = _make_gen(spy, _Response("연락처는 010-1234-5678 입니다", _Usage(3, 4, 7)))
    gen._privacy_enabled = True  # type: ignore[attr-defined]
    gen.privacy_masker = PrivacyMasker()  # type: ignore[attr-defined]

    await gen._generate_with_model(
        model="m1", query="q", context_documents=[{"content": "d"}], options={}
    )

    recorded_output = spy.observation_calls[0].get("output") or ""
    # 관측 채널에 raw 전화번호가 유출되지 않고, 마스킹 토큰이 적용됨
    assert "010-1234-5678" not in recorded_output
    assert "****" in recorded_output


@pytest.mark.asyncio
async def test_streaming_emitted_chunks_are_masked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """스트리밍: emit되는 청크가 PII 마스킹된 상태이므로 관측 output도 마스킹된다."""
    from app.modules.core.privacy.masker import PrivacyMasker

    spy = _SpyLangfuseContext()
    monkeypatch.setattr(generator_mod, "langfuse_context", spy)

    chunks = [_ContentChunk("연락처는 010-1234-5678 입니다"), _UsageChunk(_Usage(10, 20, 30))]
    gen = _make_stream_gen(spy, chunks)
    gen._privacy_enabled = True  # type: ignore[attr-defined]
    gen.privacy_masker = PrivacyMasker()  # type: ignore[attr-defined]

    emitted = "".join([c async for c in gen.stream_answer("질문", [{"content": "doc"}], {})])

    # transform_to_string은 emit된(=마스킹된) 청크를 캡처하므로 관측 output도 마스킹 상태
    assert "010-1234-5678" not in emitted
    assert "****" in emitted
    # usage 청크의 실제 토큰은 그대로 기록됨
    assert spy.observation_calls[0]["usage"]["total"] == 30
