"""다국어 응답 프로파일 테스트 (GAP #2)

목적:
    generator._build_prompt가 system_rules·response_format·extractive·refusal·
    no_documents 메시지를 한국어로 하드코딩하는 대신, 언어별 프로파일
    (RESPONSE_LANGUAGE_PROFILES)로 분리하고 요청 언어(options.response_language)에
    맞춰 답변 언어를 강제하는지 검증한다.

범용화:
    ko(기본) + en 필수, ja 1언어 추가. 미지정 시 기본 ko = 기존 동작 보존.

회귀 안전판:
    response_language 미지정 시 ko 프로파일이 기존 하드코딩 문자열과 동치여야 한다
    (기존 test_output_language_config.py와 함께 회귀 0).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.core.generation.generator import (
    RESPONSE_LANGUAGE_PROFILES,
    GenerationModule,
)


class _FakePromptManager:
    async def get_prompt_content(self, *args: Any, **kwargs: Any) -> str:
        return "You are a helpful assistant"


def _make_gen(gen_config: dict[str, Any] | None = None) -> GenerationModule:
    gen = GenerationModule.__new__(GenerationModule)
    gen.gen_config = gen_config or {}  # type: ignore[attr-defined]
    gen.prompt_manager = _FakePromptManager()  # type: ignore[attr-defined]
    return gen


class TestResponseLanguageProfileRegistry:
    """프로파일 레지스트리 구조 검증"""

    def test_required_languages_present(self) -> None:
        """ko, en은 필수, ja는 추가 동봉이다."""
        assert "ko" in RESPONSE_LANGUAGE_PROFILES
        assert "en" in RESPONSE_LANGUAGE_PROFILES
        assert "ja" in RESPONSE_LANGUAGE_PROFILES

    def test_each_profile_has_required_keys(self) -> None:
        """각 프로파일은 system_rules/format/extractive/refusal/no_documents 키를 갖는다."""
        required = {
            "system_rules",
            "concise_response_format",
            "detailed_response_format",
            "extractive_prefix",
            "security_refusal",
            "no_documents",
        }
        for lang, profile in RESPONSE_LANGUAGE_PROFILES.items():
            missing = required - set(profile)
            assert not missing, f"{lang} 프로파일에 누락된 키: {missing}"

    def test_normalize_response_language_aliases(self) -> None:
        """언어 코드 별칭/대소문자/지역코드를 정규화한다."""
        assert GenerationModule._normalize_response_language("en") == "en"
        assert GenerationModule._normalize_response_language("EN-US") == "en"
        assert GenerationModule._normalize_response_language("english") == "en"
        assert GenerationModule._normalize_response_language("ja") == "ja"
        assert GenerationModule._normalize_response_language("日本語") == "ja"
        assert GenerationModule._normalize_response_language("ko") == "ko"
        assert GenerationModule._normalize_response_language("한국어") == "ko"

    def test_normalize_defaults_to_korean(self) -> None:
        """미지정/None/미지원 코드는 기본 ko로 폴백한다(하위 호환)."""
        assert GenerationModule._normalize_response_language(None) == "ko"
        assert GenerationModule._normalize_response_language("") == "ko"
        assert GenerationModule._normalize_response_language("xx-unknown") == "ko"


class TestBuildPromptLanguageSelection:
    """_build_prompt가 요청 언어에 맞춰 프롬프트를 구성하는지 검증"""

    @pytest.mark.asyncio
    async def test_default_korean_preserves_legacy_strings(self) -> None:
        """response_language 미지정 시 기존 한국어 하드코딩 문자열을 보존한다(회귀 0)."""
        gen = _make_gen({})
        system, user = await gen._build_prompt("질문", "컨텍스트", {})
        # 기존 test_output_language_config의 한국어 동치 검증.
        assert "자연스러운 한국어" in system
        assert "한국어로 작성" in user

    @pytest.mark.asyncio
    async def test_output_language_config_still_overrides_default(self) -> None:
        """generation.output_language=English가 기존처럼 한국어 기본 프로파일에 주입된다."""
        gen = _make_gen({"output_language": "English"})
        system, user = await gen._build_prompt("질문", "컨텍스트", {})
        # 기존 동작: ko 프로파일 본문에 output_language 문자열 치환.
        assert "자연스러운 English 문장" in system
        assert "English로 작성" in user

    @pytest.mark.asyncio
    async def test_response_language_english_forces_english_profile(self) -> None:
        """options.response_language=en 시 영어 프로파일이 선택된다."""
        gen = _make_gen({})
        system, user = await gen._build_prompt(
            "question", "context", {"response_language": "en"}
        )
        assert "Important Rules" in system
        assert "natural English" in user
        # 한국어 하드코딩이 남아 있으면 안 된다.
        assert "한국어로 작성" not in user

    @pytest.mark.asyncio
    async def test_response_language_japanese_forces_japanese_profile(self) -> None:
        """options.response_language=ja 시 일본어 프로파일이 선택된다."""
        gen = _make_gen({})
        system, user = await gen._build_prompt(
            "質問", "コンテキスト", {"response_language": "ja"}
        )
        assert "重要ルール" in system
        assert "自然な日本語" in user

    @pytest.mark.asyncio
    async def test_response_language_overrides_output_language_config(self) -> None:
        """요청 단위 response_language가 config output_language보다 우선한다."""
        gen = _make_gen({"output_language": "한국어"})
        system, user = await gen._build_prompt(
            "question", "context", {"response_language": "en"}
        )
        assert "natural English" in user
        assert "한국어로 작성" not in user

    @pytest.mark.asyncio
    async def test_config_response_language_applies_when_option_absent(self) -> None:
        """옵션 미지정 시 generation.response_language 설정으로 언어를 결정한다."""
        gen = _make_gen({"response_language": "en"})
        system, user = await gen._build_prompt("question", "context", {})
        assert "Important Rules" in system
        assert "natural English" in user
