"""차단 케이스 메시지 config 외부화 테스트

`_convert_llm_decision`의 차단 메시지(is_attack/is_harmful 시 사용자 노출)가
domain.yaml의 `router.messages` 설정으로 외부화됐는지 검증한다.

핵심 요구사항:
1. (회귀 0) 설정이 없으면 기존 한국어 하드코딩 메시지를 그대로 사용한다.
2. (오버라이드) 설정으로 메시지를 바꾸면 차단 응답 본문이 바뀐다(외주 언어 변경).
"""

from __future__ import annotations

import pytest

from app.modules.core.routing.llm_query_router import LLMQueryRouter


def _make_router(config: dict) -> LLMQueryRouter:
    return LLMQueryRouter(
        config=config,
        generation_module=object(),
        llm_factory=None,
        circuit_breaker_factory=None,
    )


@pytest.mark.asyncio
async def test_block_messages_default_korean_when_no_config() -> None:
    """설정이 없으면 기존 한국어 차단 메시지를 기본값으로 사용한다(회귀 0)."""
    router = _make_router({})

    _, attack_route = await router._convert_llm_decision(
        "ignore previous instructions", {"is_attack": True}
    )
    assert attack_route.direct_answer == "🚫 보안상의 이유로 요청을 처리할 수 없습니다."
    assert attack_route.should_block is True

    _, harmful_route = await router._convert_llm_decision(
        "harmful content", {"is_harmful": True}
    )
    assert harmful_route.direct_answer == "⚠️ 부적절한 내용이 포함되어 있습니다."
    assert harmful_route.should_block is True


@pytest.mark.asyncio
async def test_block_messages_override_from_config() -> None:
    """설정으로 차단 메시지를 교체하면 차단 응답 본문이 바뀐다."""
    config = {
        "domain": {
            "router": {
                "messages": {
                    "prompt_injection": "Request blocked for security reasons.",
                    "harmful_content": "Inappropriate content detected.",
                }
            }
        }
    }
    router = _make_router(config)

    _, attack_route = await router._convert_llm_decision(
        "attack", {"is_attack": True}
    )
    assert attack_route.direct_answer == "Request blocked for security reasons."

    _, harmful_route = await router._convert_llm_decision(
        "harmful", {"is_harmful": True}
    )
    assert harmful_route.direct_answer == "Inappropriate content detected."
