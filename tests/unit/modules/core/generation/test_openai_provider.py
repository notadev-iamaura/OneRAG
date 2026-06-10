"""
OpenAI provider 직접 지원 테스트 (Phase 3.2)

목적:
    채팅 생성 경로가 OpenAI provider를 OpenRouter 폴백이 아닌 직접 클라이언트로
    지원하는지 검증한다 (google/ollama처럼). Anthropic은 OpenAI 호환 API가 없어
    OpenRouter 경유를 권장하므로 범위에서 제외한다.
"""

from __future__ import annotations

import pytest

from app.modules.core.generation.generator import GenerationModule


def _make(config_overrides: dict | None = None) -> GenerationModule:
    gen_config = {"default_provider": "openai", "openai": {}}
    if config_overrides:
        gen_config["openai"].update(config_overrides)
    return GenerationModule(config={"generation": gen_config}, prompt_manager=None)  # type: ignore[arg-type]


def test_openai_provider_default_model() -> None:
    """openai provider 선택 시 기본 모델이 gpt 계열이어야 한다."""
    gen = _make()
    assert gen.provider == "openai"
    assert gen.default_model == "gpt-4.1"


@pytest.mark.asyncio
async def test_openai_provider_initializes_direct_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OPENAI_API_KEY로 OpenAI 네이티브 엔드포인트 클라이언트를 직접 생성해야 한다."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    gen = _make()
    await gen.initialize()
    assert gen.client is not None
    assert "openai.com" in str(gen.client.base_url)


@pytest.mark.asyncio
async def test_openai_provider_missing_key_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenRouter 키가 아닌 OpenAI 키 부재 시 명확한 에러를 내야 한다."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    gen = _make()
    with pytest.raises(ValueError, match="OpenAI API 키"):
        await gen.initialize()
