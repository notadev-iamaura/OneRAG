"""쿼리 확장 전용 경량 모델/파라미터 오버라이드 배선 테스트 (#8)

`query_expansion.yaml`이 선언한 `llm.model`, `llm.reasoning_effort`,
`cache_size`, `cache_ttl`이 엔진에 실제로 주입·전달되는지 검증한다.
기존에는 from_config가 model/reasoning_effort를 읽지 않고 cache_size/cache_ttl을
하드코딩해 전형적인 'config 데드 키' 결함을 가지고 있었다.

핵심 요구사항:
1. __init__가 model/reasoning_effort 파라미터를 받아 저장한다(기본값 None).
2. from_config가 query_expansion.llm.model/reasoning_effort를 읽어 주입한다.
3. from_config가 cache_size/cache_ttl을 설정에서 읽는다(하드코딩 제거).
4. _call_gpt5_nano가 generate_with_fallback 호출 시 call_kwargs에
   model/max_tokens/temperature(+reasoning_effort)를 전달한다.
5. model=None이면 call_kwargs에서 제외돼 기존 동작이 유지된다(하위 호환).
"""

from unittest.mock import MagicMock

import pytest

from app.modules.core.retrieval.query_expansion.gpt5_engine import (
    GPT5QueryExpansionEngine,
)


def test_init_stores_model_and_reasoning_effort() -> None:
    """__init__가 model/reasoning_effort를 저장한다."""
    engine = GPT5QueryExpansionEngine(
        llm_factory=MagicMock(),
        model="google/gemini-2.5-flash-lite",
        reasoning_effort="minimal",
    )
    assert engine.model == "google/gemini-2.5-flash-lite"
    assert engine.reasoning_effort == "minimal"


def test_init_defaults_model_none() -> None:
    """model/reasoning_effort 기본값은 None(provider 기본 모델 사용)."""
    engine = GPT5QueryExpansionEngine(llm_factory=MagicMock())
    assert engine.model is None
    assert engine.reasoning_effort is None


def test_from_config_reads_model_and_reasoning_effort() -> None:
    """from_config가 query_expansion.llm.model/reasoning_effort를 읽는다."""
    config = {
        "query_expansion": {
            "llm": {
                "provider": "openrouter",
                "model": "google/gemini-2.5-flash-lite",
                "max_tokens": 333,
                "temperature": 0.55,
                "reasoning_effort": "minimal",
            },
        }
    }
    engine = GPT5QueryExpansionEngine.from_config(config, llm_factory=MagicMock())
    assert engine.model == "google/gemini-2.5-flash-lite"
    assert engine.reasoning_effort == "minimal"
    # llm 블록의 max_tokens/temperature가 우선 적용된다
    assert engine.max_tokens == 333
    assert engine.temperature == 0.55


def test_from_config_reads_cache_size_and_ttl() -> None:
    """from_config가 cache_size/cache_ttl을 설정에서 읽는다(데드 키 제거)."""
    config = {
        "query_expansion": {
            "cache_size": 7,
            "cache_ttl": 99,
        }
    }
    engine = GPT5QueryExpansionEngine.from_config(config, llm_factory=MagicMock())
    assert engine.expansion_cache.maxsize == 7
    assert engine.expansion_cache.ttl == 99


def test_from_config_defaults_when_keys_absent() -> None:
    """설정이 없으면 기존 기본값(1000/86400, model None)을 유지한다(하위 호환)."""
    engine = GPT5QueryExpansionEngine.from_config({}, llm_factory=MagicMock())
    assert engine.model is None
    assert engine.reasoning_effort is None
    assert engine.expansion_cache.maxsize == 1000
    assert engine.expansion_cache.ttl == 86400


@pytest.mark.asyncio
async def test_call_gpt5_nano_passes_call_kwargs() -> None:
    """_call_gpt5_nano가 model/max_tokens/temperature/reasoning_effort를 전달한다."""
    captured: dict[str, object] = {}

    async def fake_generate(*, prompt: str, **kwargs: object) -> tuple[str, str]:
        captured.update(kwargs)
        return ("{}", "openrouter")

    fake_factory = MagicMock()
    fake_factory.generate_with_fallback = fake_generate

    engine = GPT5QueryExpansionEngine(
        llm_factory=fake_factory,
        model="google/gemini-2.5-flash-lite",
        max_tokens=500,
        temperature=0.7,
        reasoning_effort="minimal",
    )
    await engine._call_gpt5_nano("복잡한 검색 품질에 관한 질문인가요?")

    assert captured["model"] == "google/gemini-2.5-flash-lite"
    assert captured["max_tokens"] == 500
    assert captured["temperature"] == 0.7
    assert captured["reasoning_effort"] == "minimal"


@pytest.mark.asyncio
async def test_call_gpt5_nano_omits_none_model() -> None:
    """model=None이면 call_kwargs에서 제외돼 기존 동작이 유지된다."""
    captured: dict[str, object] = {}

    async def fake_generate(*, prompt: str, **kwargs: object) -> tuple[str, str]:
        captured.update(kwargs)
        return ("{}", "google")

    fake_factory = MagicMock()
    fake_factory.generate_with_fallback = fake_generate

    engine = GPT5QueryExpansionEngine(llm_factory=fake_factory)
    await engine._call_gpt5_nano("복잡한 검색 품질에 관한 질문인가요?")

    # model/reasoning_effort 기본값 None은 전달되지 않는다
    assert "model" not in captured
    assert "reasoning_effort" not in captured
    # max_tokens/temperature는 기본값으로 전달된다
    assert captured["max_tokens"] == 500
    assert captured["temperature"] == 0.7
