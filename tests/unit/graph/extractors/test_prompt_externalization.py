"""
LLMEntityExtractor 프롬프트 외부화 회귀/오버라이드 테스트

코드에 하드코딩됐던 엔티티 추출 프롬프트를 config(prompt_template)로 외부화한 것이
다음을 만족하는지 검증:

(a) config 미설정 시 코드 내장 한국어 기본 프롬프트가 LLM에 전달됨 (회귀 0)
(b) config 오버라이드 시 코드 변경 없이 프롬프트가 바뀜
(c) 변수 치환({text}/{max_entities}) 보존
"""

from unittest.mock import AsyncMock

import pytest

from app.modules.core.graph.extractors.llm_entity_extractor import (
    ENTITY_EXTRACTION_PROMPT,
    LLMEntityExtractor,
)


@pytest.fixture
def mock_llm_client() -> AsyncMock:
    """엔티티 추출 응답을 반환하는 Mock LLM 클라이언트"""
    client = AsyncMock()
    client.generate = AsyncMock(return_value="[]")
    return client


class TestEntityExtractorPromptDefault:
    """(a) 미설정 시 코드 내장 한국어 기본 프롬프트 사용 (회귀 0)"""

    @pytest.mark.asyncio
    async def test_default_uses_builtin_prompt(self, mock_llm_client: AsyncMock) -> None:
        extractor = LLMEntityExtractor(llm_client=mock_llm_client)
        # 미설정 시 내부 템플릿 = 코드 내장 기본 프롬프트
        assert extractor._prompt_template == ENTITY_EXTRACTION_PROMPT

        await extractor.extract("A사는 서울에 있습니다.")
        prompt = mock_llm_client.generate.call_args.args[0]
        # 한국어 추출 규칙/엔티티 타입 목록이 그대로 LLM에 전달됨
        assert "엔티티(개체명)를 추출하세요" in prompt
        assert "person: 인물" in prompt
        # (c) 변수 치환 보존: {text}→실제 텍스트, {max_entities}→20
        assert "A사는 서울에 있습니다." in prompt
        assert "최대 20개까지" in prompt


class TestEntityExtractorPromptOverride:
    """(b)(c) 오버라이드 시 코드 변경 없이 프롬프트 교체 + 변수 보존"""

    @pytest.mark.asyncio
    async def test_override_changes_prompt(self, mock_llm_client: AsyncMock) -> None:
        custom = "Extract entities. Text: {text}. Max: {max_entities}."
        extractor = LLMEntityExtractor(
            llm_client=mock_llm_client,
            config={"max_entities": 5, "prompt_template": custom},
        )
        await extractor.extract("Acme is in Seoul.")
        prompt = mock_llm_client.generate.call_args.args[0]
        # 한국어 내장 프롬프트가 사라지고 영어 커스텀이 전달됨
        assert prompt == "Extract entities. Text: Acme is in Seoul.. Max: 5."
        assert "엔티티(개체명)를 추출하세요" not in prompt
