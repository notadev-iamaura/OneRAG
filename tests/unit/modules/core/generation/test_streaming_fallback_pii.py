"""
스트리밍 fallback 및 PII 청크 버퍼링 테스트 (Phase 4.5)

목적:
    (1) 스트림 시작 전 모델 실패 시 fallback 모델로 전환하는지,
    (2) 청크 경계에 걸친 PII(쪼개진 전화번호)가 버퍼링으로 마스킹되는지 검증한다.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from openai import OpenAI

from app.modules.core.generation.generator import GenerationModule
from app.modules.core.privacy.masker import PrivacyMasker


class _Delta:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


def _build_gen(
    chunks: list[str], create_side_effects: dict[str, Exception] | None = None
) -> GenerationModule:
    gen = GenerationModule.__new__(GenerationModule)
    gen._privacy_enabled = True  # type: ignore[attr-defined]
    gen.privacy_masker = PrivacyMasker()  # type: ignore[attr-defined]
    gen.default_model = "m1"  # type: ignore[attr-defined]
    gen.auto_fallback = True  # type: ignore[attr-defined]
    gen.fallback_models = ["m1", "m2"]  # type: ignore[attr-defined]
    gen.stats = {  # type: ignore[attr-defined]
        "total_generations": 0,
        "fallback_count": 0,
        "error_count": 0,
    }

    calls: list[str] = []

    def _create(**kw: Any) -> object:
        calls.append(kw["model"])
        if create_side_effects and kw["model"] in create_side_effects:
            raise create_side_effects[kw["model"]]
        return object()  # 더미 stream (실제 순회는 _iterate_stream_chunks가 담당)

    class _Client:
        class chat:
            class completions:
                create = staticmethod(_create)

    gen.client = _Client()  # type: ignore[attr-defined]
    gen._create_calls = calls  # type: ignore[attr-defined]

    async def _build_prompt(*args: object, **kwargs: object) -> tuple[str, str]:
        return ("sys", "user")

    gen._build_prompt = _build_prompt  # type: ignore[assignment]
    gen._get_model_settings = lambda m, o: {  # type: ignore[assignment]
        "max_tokens": 100,
        "temperature": 0.3,
        "timeout": 5,
    }
    gen._update_stats = lambda *a, **k: None  # type: ignore[assignment]

    async def _iterate(stream: Any) -> Any:
        for c in chunks:
            yield _Chunk(c)

    gen._iterate_stream_chunks = _iterate  # type: ignore[assignment]
    return gen


@pytest.mark.asyncio
async def test_streaming_masks_phone_split_across_chunks() -> None:
    """청크 경계에 걸쳐 쪼개진 전화번호가 버퍼링으로 마스킹돼야 한다."""
    chunks = [
        "연락처는 ",
        "010-",
        "1234-",
        "5678",
        " 입니다 그리고 추가 안내 문장을 충분히 길게 이어서 버퍼가 플러시되도록 합니다.",
    ]
    gen = _build_gen(chunks)
    out = ""
    async for piece in gen.stream_answer("질문", [{"content": "doc"}]):
        assert piece  # Standalone generators yield only user-visible text.
        out += piece
    assert "010-1234-5678" not in out, "청크 경계 전화번호가 마스킹되지 않음"


@pytest.mark.asyncio
async def test_streaming_fallback_on_first_model_failure() -> None:
    """첫 모델의 스트림 생성이 실패하면 fallback 모델로 전환해야 한다."""
    gen = _build_gen(
        ["답변"], create_side_effects={"m1": ConnectionError("backend down")}
    )
    out = ""
    async for piece in gen.stream_answer("질문", [{"content": "doc"}]):
        out += piece
    assert gen._create_calls == ["m1", "m2"]  # type: ignore[attr-defined]
    assert gen.stats["fallback_count"] == 1  # type: ignore[attr-defined]
    assert "답변" in out


@pytest.mark.asyncio
@pytest.mark.parametrize("end_first_attempt", ["cancel", "timeout"])
async def test_late_opened_sdk_stream_is_closed_once(end_first_attempt: str) -> None:
    """Return real SDK streams after their reader has timed out or disconnected."""

    class Body(httpx.SyncByteStream):
        def __init__(self) -> None:
            self.close_count = 0
            self.closed = threading.Event()
            self.iterations = 0

        def __iter__(self) -> Iterator[bytes]:
            self.iterations += 1
            yield b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
            yield b"data: [DONE]\n\n"

        def close(self) -> None:
            self.close_count += 1
            self.closed.set()

    requests: list[tuple[str, float]] = []
    first_opening = threading.Event()
    release_first = threading.Event()
    bodies = {"m1": Body(), "m2": Body()}

    def handle(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        requests.append((model, request.extensions["timeout"]["read"]))
        if model == "m1":
            first_opening.set()
            assert release_first.wait(5), "Test did not release first response"
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=bodies[model]
        )

    first_timeout = 0.3 if end_first_attempt == "timeout" else 5.0
    with OpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    ) as client:
        gen = _build_gen([])
        gen.client = client
        gen._iterate_stream_chunks = GenerationModule._iterate_stream_chunks.__get__(gen)
        gen._get_model_settings = lambda model, _: {
            "timeout": first_timeout if model == "m1" else 5.0
        }

        async def consume() -> str:
            return "".join([s async for s in gen.stream_answer("질문", [{"content": "doc"}])])

        consumer = asyncio.create_task(consume())
        try:
            assert await asyncio.to_thread(first_opening.wait, 2)
            if end_first_attempt == "cancel":
                consumer.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(consumer, 2)
            else:
                assert await asyncio.wait_for(consumer, 2) == "ok"
                assert bodies["m2"].iterations == bodies["m2"].close_count == 1
        finally:
            release_first.set()
        assert await asyncio.to_thread(bodies["m1"].closed.wait, 1)
        assert bodies["m1"].close_count == 1
        assert bodies["m1"].iterations == 0
        assert not client.is_closed()
        expected = [("m1", first_timeout)]
        if end_first_attempt == "timeout":
            expected.append(("m2", 5.0))
        assert requests == expected
        assert gen.stats["fallback_count"] == len(expected) - 1


@pytest.mark.asyncio
async def test_cancel_after_worker_open_before_stream_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cancellation can also win after the worker has returned its stream."""
    worker_done = asyncio.Event()
    original_to_thread = asyncio.to_thread

    async def hold_delivery(create: Any) -> Any:
        stream = await original_to_thread(create)
        worker_done.set()
        await asyncio.Event().wait()
        return stream

    monkeypatch.setattr(asyncio, "to_thread", hold_delivery)
    gen = _build_gen([])
    client = MagicMock()
    gen.client = client
    task = asyncio.create_task(gen._open_model_stream({}, 5))
    await asyncio.wait_for(worker_done.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    client.chat.completions.create.return_value.close.assert_called_once_with()
    client.close.assert_not_called()
