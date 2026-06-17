"""SQL 생성 프롬프트 config 외부화 테스트

sql_generation.py의 시스템/유저 프롬프트가 sql_search.generator.prompts.*로
외부화됐는지 검증한다.

핵심 요구사항:
1. (회귀 0) 설정이 없거나 빈 값이면 기존 한국어 기본 프롬프트를 그대로 사용한다.
2. (오버라이드) 설정으로 프롬프트를 바꾸면 LLM에 전달되는 프롬프트가 바뀐다.
"""

from __future__ import annotations

from app.modules.core.sql_search.prompts.sql_generation import (
    SQL_GENERATION_SYSTEM_PROMPT,
    SQL_GENERATION_USER_TEMPLATE,
    get_sql_generation_prompt,
)
from app.modules.core.sql_search.sql_generator import SQLGenerator


class TestUserPromptTemplate:
    def test_default_user_prompt_unchanged(self) -> None:
        """template 미지정 시 기본 템플릿과 byte-identical(회귀 0)"""
        expected = SQL_GENERATION_USER_TEMPLATE.format(user_query="가장 저렴한 곳")
        assert get_sql_generation_prompt("가장 저렴한 곳") == expected

    def test_user_template_override(self) -> None:
        """template 오버라이드 시 해당 템플릿으로 렌더링"""
        result = get_sql_generation_prompt(
            "hello", template="Q: {user_query} END"
        )
        assert result == "Q: hello END"

    def test_empty_template_falls_back_to_default(self) -> None:
        """빈 template은 기본 템플릿으로 폴백"""
        assert get_sql_generation_prompt("x", template=None) == (
            get_sql_generation_prompt("x")
        )


class TestGeneratorPromptWiring:
    def test_default_prompts_when_no_config(self) -> None:
        """prompts 미설정 시 기본 시스템 프롬프트/None 템플릿(회귀 0)"""
        gen = SQLGenerator(config={})
        assert gen._system_prompt == SQL_GENERATION_SYSTEM_PROMPT
        assert gen._user_template is None

    def test_empty_prompts_fall_back_to_default(self) -> None:
        """빈 문자열 prompts는 기본값으로 폴백(데드 키지만 회귀 0)"""
        gen = SQLGenerator(
            config={"prompts": {"system": "", "user_template": ""}}
        )
        assert gen._system_prompt == SQL_GENERATION_SYSTEM_PROMPT
        assert gen._user_template is None

    def test_prompts_override_from_config(self) -> None:
        """config로 system/user_template 오버라이드(데드 키 아님)"""
        gen = SQLGenerator(
            config={
                "prompts": {
                    "system": "CUSTOM SYSTEM PROMPT",
                    "user_template": "ASK: {user_query}",
                }
            }
        )
        assert gen._system_prompt == "CUSTOM SYSTEM PROMPT"
        assert gen._user_template == "ASK: {user_query}"
        assert get_sql_generation_prompt(
            "테스트", template=gen._user_template
        ) == "ASK: 테스트"
