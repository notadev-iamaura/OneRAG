"""
스트리밍 fallback 및 PII 청크 버퍼링 테스트 (Phase 4.5)

목적:
    (1) 스트림 시작 전 모델 실패 시 fallback 모델로 전환하는지,
    (2) 청크 경계에 걸친 PII(쪼개진 전화번호)가 버퍼링으로 마스킹되는지 검증한다.
"""

from __future__ import annotations

from typing import Any

import pytest

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

    async def _build_prompt(q: str, c: str, o: dict) -> tuple[str, str]:
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
