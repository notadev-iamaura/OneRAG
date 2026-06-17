"""사용자 정보(이름/나이) 추출 패턴 외부화 단위 테스트.

핵심 요구사항:
1. config 미설정(기본)이면 코드 내장 한국어 패턴으로 기존 동작과 동치(회귀 0).
2. config 오버라이드 시 영어/타 언어 패턴으로 교체 가능(데드 키 아님 — 실제 추출에 반영).
3. 추출 결과(user_name/user_info/facts)는 컨텍스트로 전파되므로 동작 영향 경로다.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.core.session.services.memory_service import (
    DEFAULT_AGE_FACT_LABEL,
    DEFAULT_AGE_REGEX,
    DEFAULT_AGE_UNIT,
    DEFAULT_NAME_FACT_LABEL,
    DEFAULT_NAME_PATTERNS,
    DEFAULT_NAME_REGEX,
    DEFAULT_NAME_SUFFIX_STRIP_CHARS,
    MemoryService,
)


def _session() -> dict[str, Any]:
    """추출 대상 세션 딕셔너리(추출 키 초기화)."""
    return {"user_name": None, "user_info": {}, "facts": {}}


class TestDefaultPatternsAreBuiltinKorean:
    """(a) 미설정 시 코드 내장 한국어 패턴 사용 (회귀 0)."""

    def test_config_attributes_default_to_builtin(self) -> None:
        service = MemoryService()
        assert service.name_patterns == DEFAULT_NAME_PATTERNS
        assert service.name_regex == DEFAULT_NAME_REGEX
        assert service.name_suffix_strip_chars == DEFAULT_NAME_SUFFIX_STRIP_CHARS
        assert service.name_fact_label == DEFAULT_NAME_FACT_LABEL
        assert service.age_unit == DEFAULT_AGE_UNIT
        assert service.age_regex == DEFAULT_AGE_REGEX
        assert service.age_fact_label == DEFAULT_AGE_FACT_LABEL

    @pytest.mark.asyncio
    async def test_korean_name_regex_extraction(self) -> None:
        """정규식 경로: '저는 철수입니다' → 이름 '철수' (기존 동작 동치)."""
        service = MemoryService()
        session = _session()
        await service._extract_user_info(session, "저는 철수입니다")
        assert session["user_name"] == "철수"
        assert session["facts"]["이름"] == "철수"

    @pytest.mark.asyncio
    async def test_korean_name_substring_extraction(self) -> None:
        """부분 문자열 경로: '내 이름은 영희야' → 이름 '영희' (조사 제거 포함)."""
        service = MemoryService()
        session = _session()
        await service._extract_user_info(session, "내 이름은 영희야")
        assert session["user_name"] == "영희"
        assert session["facts"]["이름"] == "영희"

    @pytest.mark.asyncio
    async def test_korean_age_extraction(self) -> None:
        """나이 경로: '저는 30살입니다' → 나이 30 (기존 동작 동치)."""
        service = MemoryService()
        session = _session()
        await service._extract_user_info(session, "저는 30살입니다")
        assert session["user_info"]["나이"] == 30
        assert session["facts"]["나이"] == "30살"


class TestOverridePatternsViaConfig:
    """(b)(c) config 오버라이드 시 패턴 교체 + 실제 추출 반영 (데드 키 아님)."""

    def _english_config(self) -> dict[str, Any]:
        return {
            "session": {
                "user_info_extraction": {
                    "name_patterns": ["my name is ", "I am ", "call me "],
                    "name_regex": r"my name is\s+([A-Za-z]+)",
                    "name_suffix_strip_chars": ".,",
                    "age_unit": "years old",
                    "age_regex": r"(\d+)\s*years old",
                    "name_fact_label": "name",
                    "age_fact_label": "age",
                }
            }
        }

    def test_config_attributes_are_overridden(self) -> None:
        service = MemoryService(config=self._english_config())
        assert service.name_patterns == ["my name is ", "I am ", "call me "]
        assert service.name_regex == r"my name is\s+([A-Za-z]+)"
        assert service.age_unit == "years old"
        assert service.name_fact_label == "name"
        assert service.age_fact_label == "age"

    @pytest.mark.asyncio
    async def test_english_name_regex_extraction(self) -> None:
        service = MemoryService(config=self._english_config())
        session = _session()
        await service._extract_user_info(session, "Hello, my name is Alice")
        assert session["user_name"] == "Alice"
        assert session["facts"]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_english_age_extraction(self) -> None:
        service = MemoryService(config=self._english_config())
        session = _session()
        await service._extract_user_info(session, "I am 42 years old")
        assert session["user_info"]["age"] == 42
        assert session["facts"]["age"] == "42years old"


class TestInvalidConfigFallsBackToDefault:
    """비정상 config(타입 불일치/공백)는 코드 기본값으로 폴백 (회귀 0)."""

    def test_non_list_name_patterns_falls_back(self) -> None:
        service = MemoryService(
            config={"session": {"user_info_extraction": {"name_patterns": "not-a-list"}}}
        )
        assert service.name_patterns == DEFAULT_NAME_PATTERNS

    def test_blank_regex_falls_back(self) -> None:
        service = MemoryService(
            config={"session": {"user_info_extraction": {"name_regex": "   "}}}
        )
        assert service.name_regex == DEFAULT_NAME_REGEX

    def test_non_dict_extraction_config_falls_back(self) -> None:
        service = MemoryService(
            config={"session": {"user_info_extraction": "invalid"}}
        )
        assert service.name_patterns == DEFAULT_NAME_PATTERNS
        assert service.age_unit == DEFAULT_AGE_UNIT
