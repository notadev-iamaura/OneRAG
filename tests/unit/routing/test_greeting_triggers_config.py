"""인사 트리거 키워드 설정 이관 테스트

`_generate_greeting_response`의 트리거 키워드(작별/감사/인사)가
domain.yaml의 `router.greeting_triggers` 설정으로 이관됐는지 검증한다.

핵심 요구사항:
1. 설정이 없으면 기존 하드코딩 키워드/응답을 그대로 사용한다(하위 호환).
2. 설정으로 트리거 키워드를 바꾸면 분류 동작이 바뀐다(외주 언어 변경).
"""

from app.modules.core.routing.llm_query_router import LLMQueryRouter


def _make_router(config: dict) -> LLMQueryRouter:
    """라우터 인스턴스 생성 헬퍼 (LLM 비활성화로 가볍게)"""
    return LLMQueryRouter(
        config=config,
        generation_module=object(),
        llm_factory=None,
        circuit_breaker_factory=None,
    )


def test_greeting_triggers_default_korean_when_no_config() -> None:
    """설정이 없으면 기존 한국어 트리거 키워드를 기본값으로 사용한다."""
    router = _make_router({})

    # 작별
    assert router._generate_greeting_response("잘가") == (
        "안녕히 가세요! 이용해 주셔서 감사합니다."
    )
    # 감사
    assert router._generate_greeting_response("고마워") == (
        "도움이 되셨다니 기쁩니다! 언제든 다시 질문해주세요."
    )
    # 인사
    assert router._generate_greeting_response("안녕") == (
        "안녕하세요! 무엇을 도와드릴까요?"
    )
    # 기본 응답
    assert router._generate_greeting_response("뭔가요") == (
        "안녕하세요! 궁금한 점을 말씀해주세요."
    )


def test_greeting_triggers_english_keywords_still_work_by_default() -> None:
    """기본 영어 트리거(bye/thank/hello)도 설정 없이 동작한다."""
    router = _make_router({})

    assert router._generate_greeting_response("bye") == (
        "안녕히 가세요! 이용해 주셔서 감사합니다."
    )
    assert router._generate_greeting_response("thank you") == (
        "도움이 되셨다니 기쁩니다! 언제든 다시 질문해주세요."
    )
    assert router._generate_greeting_response("hello") == (
        "안녕하세요! 무엇을 도와드릴까요?"
    )


def test_greeting_triggers_override_from_config() -> None:
    """설정으로 트리거 키워드를 교체하면 분류 동작이 바뀐다."""
    config = {
        "domain": {
            "router": {
                "messages": {
                    "farewell": "Goodbye!",
                    "thanks": "You're welcome!",
                    "greeting": "Hi there!",
                    "default_greeting": "How can I help?",
                },
                "greeting_triggers": {
                    "farewell": ["adieu"],
                    "thanks": ["merci"],
                    "greeting": ["bonjour"],
                },
            }
        }
    }
    router = _make_router(config)

    # 설정된 외국어 키워드로 분류된다
    assert router._generate_greeting_response("adieu mon ami") == "Goodbye!"
    assert router._generate_greeting_response("merci beaucoup") == "You're welcome!"
    assert router._generate_greeting_response("bonjour") == "Hi there!"

    # 기존 한국어 키워드는 더 이상 트리거되지 않는다(설정으로 덮어썼으므로)
    assert router._generate_greeting_response("안녕") == "How can I help?"
