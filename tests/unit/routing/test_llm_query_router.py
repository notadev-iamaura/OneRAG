from unittest.mock import AsyncMock

import pytest

from app.modules.core.routing.llm_query_router import LLMQueryRouter


class _PassthroughBreaker:
    async def call(self, fn, *args, **kwargs):
        return await fn(*args, **kwargs)


class _BreakerFactory:
    def get(self, *_args, **_kwargs):
        return _PassthroughBreaker()


@pytest.mark.asyncio
async def test_llm_query_router_uses_configured_provider_and_model() -> None:
    llm_factory = type("Factory", (), {})()
    llm_factory._clients = {"openrouter": object()}
    llm_factory.generate_with_fallback = AsyncMock(
        return_value=(
            """
            {
              "is_greeting": false,
              "is_harmful": false,
              "is_attack": false,
              "is_out_of_scope": false,
              "needs_rag": true,
              "data_source": "general",
              "reasoning": "문서 검색 필요"
            }
            """,
            "openrouter",
        )
    )

    router = LLMQueryRouter(
        config={
            "query_routing": {
                "llm_router": {
                    "enabled": True,
                    "provider": "openrouter",
                    "model": "openrouter/test-model",
                    "temperature": 0.2,
                    "max_tokens": 123,
                }
            }
        },
        generation_module=object(),
        llm_factory=llm_factory,
        circuit_breaker_factory=_BreakerFactory(),
    )

    await router._call_llm_router("질문")

    kwargs = llm_factory.generate_with_fallback.call_args.kwargs
    assert kwargs["preferred_provider"] == "openrouter"
    # 라우터는 preferred provider용 설정 모델을 전달한다. 이 model이 폴백 provider로
    # 새지 않도록 스코프하는 책임은 generate_with_fallback에 있다(아래 별도 테스트로 검증).
    assert kwargs["model"] == "openrouter/test-model"
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_tokens"] == 123


def test_llm_query_router_disables_unavailable_configured_provider(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    router = LLMQueryRouter(
        config={
            "query_routing": {
                "llm_router": {
                    "enabled": True,
                    "provider": "google",
                }
            }
        },
        generation_module=object(),
        llm_factory=None,
        circuit_breaker_factory=_BreakerFactory(),
    )

    assert router.enabled is False


def test_llm_query_router_uses_factory_clients_for_provider_availability() -> None:
    llm_factory = type("Factory", (), {"_clients": {"openrouter": object()}})()

    router = LLMQueryRouter(
        config={
            "query_routing": {
                "llm_router": {
                    "enabled": True,
                    "provider": "openrouter",
                }
            }
        },
        generation_module=object(),
        llm_factory=llm_factory,
        circuit_breaker_factory=_BreakerFactory(),
    )

    assert router.enabled is True


def test_llm_query_router_disables_google_without_api_key(monkeypatch) -> None:
    # ✅ [45] 회귀: google이 _clients에 있어도 API 키가 없으면 라우터는 비활성화돼야 한다.
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    llm_factory = type("Factory", (), {"_clients": {"google": object()}})()

    router = LLMQueryRouter(
        config={
            "query_routing": {
                "llm_router": {
                    "enabled": True,
                    "provider": "google",
                }
            }
        },
        generation_module=object(),
        llm_factory=llm_factory,
        circuit_breaker_factory=_BreakerFactory(),
    )

    assert router.enabled is False


def test_llm_query_router_disables_unknown_provider_without_clients() -> None:
    # ✅ [52] 회귀: _clients가 없고 알 수 없는 provider면 보수적으로 비활성화돼야 한다.
    router = LLMQueryRouter(
        config={
            "query_routing": {
                "llm_router": {
                    "enabled": True,
                    "provider": "totally-unknown-provider",
                }
            }
        },
        generation_module=object(),
        llm_factory=None,
        circuit_breaker_factory=_BreakerFactory(),
    )

    assert router.enabled is False


# ============================================================================
# 항목 5: PROCEDURAL 인텐트 키워드 외부화 (domain.router.procedural_intent_keywords)
# ============================================================================


def _make_router(config: dict) -> LLMQueryRouter:
    """프로바이더 검증을 우회하기 위해 라우터를 비활성 상태로 생성하는 헬퍼."""
    return LLMQueryRouter(
        config=config,
        generation_module=object(),
        llm_factory=None,
        circuit_breaker_factory=_BreakerFactory(),
    )


def test_procedural_keywords_default_is_korean_minimal() -> None:
    """(a) 미설정 시 코드 기본(ko 최소셋)을 사용한다(회귀 0)."""
    from app.modules.core.routing.llm_query_router import (
        _DEFAULT_PROCEDURAL_INTENT_KEYWORDS,
    )

    router = _make_router({})
    assert router.procedural_intent_keywords == _DEFAULT_PROCEDURAL_INTENT_KEYWORDS
    # 기존 하드코딩 키워드가 그대로 포함된다.
    assert "방법" in router.procedural_intent_keywords
    assert "어떻게" in router.procedural_intent_keywords
    assert "규칙" in router.procedural_intent_keywords


def test_procedural_keywords_override_from_domain_config() -> None:
    """(b)(c) config 오버라이드 시 키워드가 교체되고 인스턴스에 반영된다(데드 키 아님)."""
    router = _make_router(
        {
            "domain": {
                "router": {
                    "procedural_intent_keywords": ["how to", "procedure"],
                }
            }
        }
    )
    assert router.procedural_intent_keywords == ("how to", "procedure")
    # 오버라이드는 '대체'이므로 한국어 기본 키워드는 더 이상 포함되지 않는다.
    assert "방법" not in router.procedural_intent_keywords


def test_procedural_keywords_empty_falls_back_to_default() -> None:
    """빈 리스트/비리스트는 무효로 보아 코드 기본값을 사용한다(회귀 0)."""
    from app.modules.core.routing.llm_query_router import (
        _DEFAULT_PROCEDURAL_INTENT_KEYWORDS,
    )

    router_empty = _make_router(
        {"domain": {"router": {"procedural_intent_keywords": []}}}
    )
    assert (
        router_empty.procedural_intent_keywords
        == _DEFAULT_PROCEDURAL_INTENT_KEYWORDS
    )
    router_bad = _make_router(
        {"domain": {"router": {"procedural_intent_keywords": "방법"}}}
    )
    assert (
        router_bad.procedural_intent_keywords == _DEFAULT_PROCEDURAL_INTENT_KEYWORDS
    )
