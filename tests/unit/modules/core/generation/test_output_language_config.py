"""
출력 언어 설정화 테스트 (Phase 3.1)

목적:
    답변 출력 언어가 코드에 한국어로 하드코딩되지 않고 설정
    (generation.output_language)으로 제어되는지 검증한다. 비한국어 외주
    프로젝트가 코드 포크 없이 언어를 바꿀 수 있어야 한다.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.core.generation.generator import GenerationModule


class _FakePromptManager:
    async def get_prompt_content(self, *args: Any, **kwargs: Any) -> str:
        return "You are a helpful assistant"


def _make_gen(gen_config: dict[str, Any]) -> GenerationModule:
    gen = GenerationModule.__new__(GenerationModule)
    gen.gen_config = gen_config  # type: ignore[attr-defined]
    gen.prompt_manager = _FakePromptManager()  # type: ignore[attr-defined]
    return gen


@pytest.mark.asyncio
async def test_build_prompt_uses_configured_english() -> None:
    """output_language=English 설정 시 프롬프트가 영어 출력을 지시해야 한다."""
    gen = _make_gen({"output_language": "English"})
    system, user = await gen._build_prompt("question", "context", {})
    assert "자연스러운 English 문장" in system
    assert "English로 작성" in user


@pytest.mark.asyncio
async def test_build_prompt_defaults_to_korean() -> None:
    """설정이 없으면 기본값 한국어를 유지해야 한다 (하위 호환)."""
    gen = _make_gen({})
    system, user = await gen._build_prompt("question", "context", {})
    assert "자연스러운 한국어 문장" in system
    assert "한국어로 작성" in user
