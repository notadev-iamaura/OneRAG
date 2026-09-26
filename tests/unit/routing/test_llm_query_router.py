import hashlib
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


def _make_cache_router(cache_ttl: int | None = None) -> LLMQueryRouter:
    llm_factory = type("Factory", (), {"_clients": {"openrouter": object()}})()
    routing_config = {
        "llm_router": {"enabled": True, "provider": "openrouter"},
    }
    if cache_ttl is not None:
        routing_config["cache_ttl"] = cache_ttl

    router = LLMQueryRouter(
        config={"query_routing": routing_config},
        llm_factory=llm_factory,
    )
    router._call_llm_router = AsyncMock(
        return_value={
            "is_greeting": False,
            "is_harmful": False,
            "is_attack": False,
            "is_out_of_scope": False,
            "needs_rag": True,
            "reasoning": "test",
        }
    )
    return router


@pytest.mark.parametrize("cache_ttl, expected", [(None, 3600), (123, 123)])
def test_router_cache_ttl_uses_config_or_default(cache_ttl, expected) -> None:
    router = _make_cache_router(cache_ttl)

    assert router.routing_cache.ttl == expected
    assert router.routing_cache.maxsize == 500


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first_context, second_context",
    [
        ("User: 안녕\nAssistant: 안녕하세요", "User: 안녕\nAssistant: 반갑습니다"),
        ("ctx A", "ctx B"),
    ],
)
async def test_different_session_contexts_miss_separate_cache_entries(
    first_context: str, second_context: str
) -> None:
    router = _make_cache_router()

    await router.analyze_and_route("환불 절차", session_context=first_context)
    await router.analyze_and_route("환불 절차", session_context=second_context)

    assert router._call_llm_router.call_count == 2
    assert router.stats["cache_misses"] == 2
    assert len(router.routing_cache) == 2
    assert set(router.routing_cache) == {
        f"환불 절차::ctx:{hashlib.sha256(context.encode('utf-8')).hexdigest()[:16]}"
        for context in (first_context, second_context)
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session_context",
    [None, "", "   ", "User: 이전 질문\nAssistant: 이전 답변"],
)
async def test_same_session_context_hits_cache(session_context: str | None) -> None:
    router = _make_cache_router()

    first = await router.analyze_and_route("안녕하세요", session_context=session_context)
    second = await router.analyze_and_route("안녕하세요", session_context=session_context)

    assert router._call_llm_router.call_count == 1
    assert router.stats["cache_hits"] == 1
    assert first == second


@pytest.mark.asyncio
async def test_empty_none_and_whitespace_contexts_share_query_only_key() -> None:
    router = _make_cache_router()

    for session_context in (None, "", "\n\t "):
        await router.analyze_and_route(" 배송 문의 ", session_context=session_context)

    assert router._call_llm_router.call_count == 1
    assert list(router.routing_cache) == ["배송 문의"]


@pytest.mark.asyncio
async def test_session_context_hash_uses_stripped_text() -> None:
    router = _make_cache_router()

    await router.analyze_and_route("배송 문의", session_context="  이전 대화  ")
    await router.analyze_and_route("배송 문의", session_context="이전 대화")

    expected_hash = hashlib.sha256("이전 대화".encode()).hexdigest()[:16]
    assert router._call_llm_router.call_count == 1
    assert list(router.routing_cache) == [f"배송 문의::ctx:{expected_hash}"]
