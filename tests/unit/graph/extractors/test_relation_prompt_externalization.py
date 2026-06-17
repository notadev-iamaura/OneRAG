"""
LLMRelationExtractor 프롬프트 외부화 회귀/오버라이드 테스트

코드 상수로 하드코딩됐던 관계 추출 프롬프트를 config(prompt_template)로
외부화한 것이 다음을 만족하는지 검증한다(llm_entity_extractor 패턴과 동일):

(a) config 미설정 시 코드 내장 한국어 기본 프롬프트가 LLM에 전달됨 (회귀 0)
(b) config 오버라이드 시 코드 변경 없이 프롬프트가 바뀜
(c) 변수 치환({text}/{entities}/{max_relations}) 보존
"""

from unittest.mock import AsyncMock

import pytest

from app.modules.core.graph.extractors.llm_relation_extractor import (
    RELATION_EXTRACTION_PROMPT,
    LLMRelationExtractor,
)
from app.modules.core.graph.models import Entity


@pytest.fixture
def sample_entities() -> list[Entity]:
    """관계 추출용 최소 엔티티(2개 이상이어야 추출 시도)"""
    return [
        Entity(id="e1", name="A사", type="company"),
        Entity(id="e2", name="서울", type="location"),
    ]


@pytest.fixture
def mock_llm_client() -> AsyncMock:
    """관계 추출 응답(빈 배열)을 반환하는 Mock LLM 클라이언트"""
    client = AsyncMock()
    client.generate = AsyncMock(return_value="[]")
    return client


class TestRelationExtractorPromptDefault:
    """(a) 미설정 시 코드 내장 한국어 기본 프롬프트 사용 (회귀 0)"""

    @pytest.mark.asyncio
    async def test_default_uses_builtin_prompt(
        self, mock_llm_client: AsyncMock, sample_entities: list[Entity]
    ) -> None:
        extractor = LLMRelationExtractor(llm_client=mock_llm_client)
        # 미설정 시 내부 템플릿 = 코드 내장 기본 프롬프트
        assert extractor._prompt_template == RELATION_EXTRACTION_PROMPT

        await extractor.extract("A사는 서울에 있습니다.", sample_entities)
        prompt = mock_llm_client.generate.call_args.args[0]
        # 한국어 추출 규칙/관계 타입 목록이 그대로 LLM에 전달됨
        assert "엔티티 간의 관계를 추출하세요" in prompt
        assert "partnership: 파트너십" in prompt
        # (c) 변수 치환 보존: {text}→실제 텍스트, {entities}→엔티티 목록, {max_relations}→30
        assert "A사는 서울에 있습니다." in prompt
        assert "- A사 (company)" in prompt
        assert "최대 30개까지" in prompt


class TestRelationExtractorPromptOverride:
    """(b)(c) 오버라이드 시 코드 변경 없이 프롬프트 교체 + 변수 보존"""

    @pytest.mark.asyncio
    async def test_override_changes_prompt(
        self, mock_llm_client: AsyncMock, sample_entities: list[Entity]
    ) -> None:
        custom = "Extract relations. Text: {text}. Entities: {entities}. Max: {max_relations}."
        extractor = LLMRelationExtractor(
            llm_client=mock_llm_client,
            config={"max_relations": 7, "prompt_template": custom},
        )
        await extractor.extract("Acme is in Seoul.", sample_entities)
        prompt = mock_llm_client.generate.call_args.args[0]
        # 한국어 내장 프롬프트가 사라지고 영어 커스텀이 전달됨
        assert prompt.startswith("Extract relations. Text: Acme is in Seoul.")
        assert "Max: 7." in prompt
        assert "엔티티 간의 관계를 추출하세요" not in prompt
