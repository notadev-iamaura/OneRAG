"""라우터 분류 프롬프트 전체 템플릿 config 외부화 테스트

`_build_router_prompt`의 프롬프트 본문(지시문/판단항목/JSON 포맷) 언어 자체를
domain.yaml의 `router.prompt_template`로 오버라이드할 수 있는지 검증한다.

핵심 요구사항:
1. (회귀 0) prompt_template 미설정 시 기존 한국어 본문을 코드 기본값으로 사용한다.
2. (오버라이드) prompt_template 설정 시 그 템플릿이 사용되며 placeholder가 치환된다.
3. 런타임 placeholder({context}/{query})는 보존되고, JSON 예시 중괄호도 깨지지 않는다.
4. (데드 키 아님) 코드가 domain.router.prompt_template 키를 실제로 읽는다.
"""

from __future__ import annotations

from app.modules.core.routing.llm_query_router import LLMQueryRouter


def _make_router(config: dict) -> LLMQueryRouter:
    """라우터 인스턴스 생성 헬퍼 (LLM 비활성화로 가볍게)"""
    return LLMQueryRouter(
        config=config,
        generation_module=object(),
        llm_factory=None,
        circuit_breaker_factory=None,
    )


def _domain_config(extra: dict | None = None) -> dict:
    """domain.router 기본 설정 헬퍼"""
    router: dict = {
        "system_role": "테스트 역할",
        "domain_description": "테스트 설명",
        "rag_categories": [{"name": "정보", "description": "정보 요청"}],
        "data_sources": {
            "structured": {
                "description": "S",
                "triggers": {"entities": ["삼성"], "keywords": ["가격"]},
            },
            "general": {"description": "G", "triggers": {"keywords": ["추천"]}},
            "both": {"description": "B", "triggers": {"keywords": ["후기"]}},
        },
        "out_of_scope_examples": ["날씨"],
    }
    if extra:
        router.update(extra)
    return {"domain": {"router": router}}


def test_router_prompt_default_korean_when_no_template() -> None:
    """prompt_template 미설정 시 기존 한국어 본문을 기본값으로 사용한다(회귀 0)."""
    router = _make_router(_domain_config())
    prompt = router.router_prompt

    # 한국어 본문 핵심 문구가 그대로 유지된다
    assert "당신은 테스트 역할입니다." in prompt
    assert "**판단 항목**" in prompt
    assert "반드시 아래 JSON 형식으로만 출력하세요" in prompt
    # config 값이 placeholder로 치환됐다
    assert "정보 요청" in prompt
    assert "삼성" in prompt
    # 런타임 placeholder는 보존된다
    assert "{context}" in prompt
    assert "{query}" in prompt


def test_router_prompt_runtime_substitution_preserves_json_braces() -> None:
    """런타임 치환(replace 방식)이 JSON 예시 중괄호를 깨지 않는다."""
    router = _make_router(_domain_config())
    runtime = router.router_prompt.replace("{context}", "CTX").replace(
        "{query}", "QRY"
    )
    assert "CTX" in runtime and "QRY" in runtime
    # JSON 예시의 키가 그대로 남아 있어야 한다(중괄호 이스케이프 깨짐 없음)
    assert '"needs_rag": true/false' in runtime
    assert '"data_source"' in runtime


def test_router_prompt_template_override_from_config() -> None:
    """prompt_template 설정 시 그 템플릿이 사용되고 placeholder가 치환된다."""
    template = (
        "<system_instructions>\n"
        "You are {system_role}. {domain_desc}\n"
        "</system_instructions>\n"
        "<user_query>{query}</user_query>\n"
        '<response_format>{ "needs_rag": boolean }</response_format>'
    )
    router = _make_router(
        _domain_config({"prompt_template": template})
    )
    prompt = router.router_prompt

    # config 템플릿이 적용됐다(영어 지시문)
    assert prompt.startswith("<system_instructions>\nYou are 테스트 역할. 테스트 설명")
    # 한국어 코드 기본 본문은 더 이상 등장하지 않는다
    assert "**판단 항목**" not in prompt
    # 런타임 placeholder와 JSON 중괄호는 보존된다
    assert "{query}" in prompt
    assert '"needs_rag": boolean' in prompt


def test_router_prompt_empty_template_falls_back_to_default() -> None:
    """빈 문자열 prompt_template은 무시하고 코드 기본 템플릿으로 폴백한다(회귀 0)."""
    router = _make_router(_domain_config({"prompt_template": "   "}))
    assert "**판단 항목**" in router.router_prompt
