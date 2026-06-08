"""generate_with_fallback의 provider별 model 스코프 동작 테스트.

#5 회귀 방지: provider 전용 model 문자열은 preferred provider에만 적용되어야 하며,
auto_fallback으로 다른 provider로 전환되면 해당 provider의 기본 model을 써야 한다.
"""

import pytest

from app.lib.llm_client import LLMClientFactory


class _FakeClient:
    """generate_text 호출 kwargs를 기록하는 가짜 LLM 클라이언트."""

    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.calls: list[dict] = []

    async def generate_text(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        self.calls.append(dict(kwargs))
        if self.fail:
            raise RuntimeError(f"{self.name} unavailable")
        return f"answer-from-{self.name}"


def _factory_with_clients(clients: dict, fallback_order: list[str]) -> LLMClientFactory:
    # 실제 __init__(API 키 기반 클라이언트 구성)을 우회하고 가짜 클라이언트를 주입한다.
    factory = object.__new__(LLMClientFactory)
    factory.config = {"llm": {"auto_fallback": True, "fallback_order": fallback_order}}
    factory._clients = clients
    return factory


@pytest.mark.asyncio
async def test_generate_with_fallback_scopes_model_to_preferred_provider() -> None:
    openrouter = _FakeClient("openrouter", fail=True)  # preferred 실패 → 폴백 유도
    openai = _FakeClient("openai")
    factory = _factory_with_clients(
        {"openrouter": openrouter, "openai": openai},
        fallback_order=["openrouter", "openai"],
    )

    text, provider = await factory.generate_with_fallback(
        prompt="q",
        system_prompt=None,
        preferred_provider="openrouter",
        model="openrouter/test-model",
        temperature=0.2,
        max_tokens=123,
    )

    assert provider == "openai"
    assert text == "answer-from-openai"

    # preferred provider는 지정된 model을 받는다.
    assert openrouter.calls[0].get("model") == "openrouter/test-model"
    assert openrouter.calls[0].get("temperature") == 0.2

    # 폴백 provider에는 provider 전용 model이 새지 않아야 한다(자기 기본 model 사용).
    assert "model" not in openai.calls[0]
    assert openai.calls[0].get("temperature") == 0.2
    assert openai.calls[0].get("max_tokens") == 123


@pytest.mark.asyncio
async def test_generate_with_fallback_applies_model_on_preferred_success() -> None:
    openrouter = _FakeClient("openrouter")
    factory = _factory_with_clients(
        {"openrouter": openrouter, "openai": _FakeClient("openai")},
        fallback_order=["openrouter", "openai"],
    )

    text, provider = await factory.generate_with_fallback(
        prompt="q",
        system_prompt=None,
        preferred_provider="openrouter",
        model="openrouter/test-model",
    )

    assert provider == "openrouter"
    assert text == "answer-from-openrouter"
    assert openrouter.calls[0].get("model") == "openrouter/test-model"
