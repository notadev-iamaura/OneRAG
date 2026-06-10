"""쿼리 확장 프롬프트 언어 설정 이관 테스트

`GPT5QueryExpansionEngine`의 확장 프롬프트와 시스템 메시지에 하드코딩된
"한국어"/"Korean"을 설정값(query_expansion.expansion_language)으로 파라미터화한다.

핵심 요구사항:
1. 설정이 없으면 기본 언어 "한국어"/"Korean"을 사용한다(하위 호환).
2. 설정으로 언어를 바꾸면 프롬프트/시스템 메시지에 반영된다.
3. 질문 마커 목록도 설정으로 오버라이드 가능하다(기본값: 한/일 마커).
"""

from unittest.mock import MagicMock

import pytest

from app.modules.core.retrieval.query_expansion.gpt5_engine import (
    GPT5QueryExpansionEngine,
)


def test_expansion_prompt_defaults_to_korean() -> None:
    """설정 없이 생성하면 확장 프롬프트가 한국어 기준으로 작성된다."""
    engine = GPT5QueryExpansionEngine(llm_factory=MagicMock())
    assert "한국어" in engine.expansion_prompt
    assert engine.expansion_language == "한국어"


def test_expansion_prompt_uses_configured_language() -> None:
    """expansion_language를 바꾸면 확장 프롬프트에 반영된다."""
    engine = GPT5QueryExpansionEngine(
        llm_factory=MagicMock(),
        expansion_language="English",
    )
    assert "English" in engine.expansion_prompt
    # 기존 한국어 문구는 더 이상 들어가지 않는다
    assert "한국어 문서 검색" not in engine.expansion_prompt


def test_from_config_reads_expansion_language() -> None:
    """from_config가 query_expansion.expansion_language를 읽는다."""
    config = {
        "query_expansion": {
            "expansion_language": "日本語",
        }
    }
    engine = GPT5QueryExpansionEngine.from_config(config, llm_factory=MagicMock())
    assert engine.expansion_language == "日本語"
    assert "日本語" in engine.expansion_prompt


def test_from_config_defaults_korean_without_setting() -> None:
    """설정이 없으면 from_config도 한국어를 기본값으로 사용한다."""
    engine = GPT5QueryExpansionEngine.from_config({}, llm_factory=MagicMock())
    assert engine.expansion_language == "한국어"


def test_question_markers_default_includes_korean_japanese() -> None:
    """질문 마커 기본값은 기존 한/일 마커를 포함한다(하위 호환)."""
    engine = GPT5QueryExpansionEngine(llm_factory=MagicMock())
    # 기존 한국어 질문 마커로 복잡 쿼리 판정이 유지된다
    assert engine._is_simple_query("어떻게 복구하나요") is False
    assert engine._is_simple_query("なぜ") is False


def test_question_markers_override_from_config() -> None:
    """질문 마커를 설정으로 교체하면 판정 동작이 바뀐다."""
    config = {
        "query_expansion": {
            "question_markers": ["pourquoi", "comment"],
        }
    }
    engine = GPT5QueryExpansionEngine.from_config(config, llm_factory=MagicMock())
    # 설정한 외국어 마커는 질문 신호로 인식된다
    assert engine._is_simple_query("comment") is False
    # 기존 한국어 마커는 더 이상 질문 신호가 아니다(설정으로 덮어씀)
    # "어떻게"는 5자 이내이고 토큰 1개라 단순 쿼리로 판정돼야 한다
    assert engine._is_simple_query("어떻게") is True


@pytest.mark.asyncio
async def test_call_gpt5_nano_system_message_uses_configured_language() -> None:
    """_call_gpt5_nano의 시스템 메시지가 설정 언어를 반영한다."""
    fake_factory = MagicMock()

    captured: dict[str, str] = {}

    async def fake_generate(*, prompt: str, **kwargs: object) -> tuple[str, str]:
        captured["prompt"] = prompt
        return ("{}", "google")

    fake_factory.generate_with_fallback = fake_generate

    engine = GPT5QueryExpansionEngine(
        llm_factory=fake_factory,
        expansion_language_en="English",
    )
    await engine._call_gpt5_nano("a complex question about retrieval quality?")

    # 영어 시스템 메시지에 설정된 영어 언어 이름이 들어가야 한다
    assert "English query expansion specialist" in captured["prompt"]
    assert "Korean query expansion specialist" not in captured["prompt"]


def test_call_gpt5_nano_system_message_defaults_to_korean() -> None:
    """기본값일 때 영어 시스템 메시지는 기존 'Korean'을 유지한다(하위 호환)."""
    engine = GPT5QueryExpansionEngine(llm_factory=MagicMock())
    assert engine.expansion_language_en == "Korean"
