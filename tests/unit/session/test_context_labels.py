"""세션 컨텍스트 라벨 + 요약 프롬프트 외부화 단위 테스트.

핵심 요구사항:
1. config 미설정(기본)이면 코드 내장 한국어 라벨/프롬프트로 기존 출력과 동치(회귀 0).
2. config 오버라이드 시 영어/타 언어 라벨/프롬프트로 교체 가능(데드 키 아님 — 실제
   get_context_string 출력과 _summarize_conversations 프롬프트에 반영).
3. get_context_string 반환값과 요약 결과는 {session_context}로 LLM에 삽입되므로
   cosmetic이 아닌 동작 영향 경로다.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.chat_history import InMemoryChatMessageHistory

from app.modules.core.session.services.memory_service import (
    DEFAULT_AI_TURN_LABEL,
    DEFAULT_FACTS_HEADER,
    DEFAULT_RECENT_HEADER,
    DEFAULT_RECENT_HEADER_FULL,
    DEFAULT_SUMMARY_HEADER,
    DEFAULT_SUMMARY_PROMPT_TEMPLATE,
    DEFAULT_TOPICS_LABEL,
    DEFAULT_USER_INFO_LABEL_PREFIX,
    DEFAULT_USER_NAME_LABEL,
    DEFAULT_USER_TURN_LABEL,
    MemoryService,
)


def _seed_history(service: MemoryService, session_id: str) -> None:
    """컨텍스트 출력 검증을 위해 1교환(user+AI) 메모리를 주입한다."""
    history = InMemoryChatMessageHistory()
    history.add_user_message("안녕하세요")
    history.add_ai_message("무엇을 도와드릴까요?")
    service.memories[session_id] = history


class TestDefaultLabelsAreBuiltinKorean:
    """(a) 미설정 시 코드 내장 한국어 라벨 사용 (회귀 0)."""

    def test_label_attributes_default_to_builtin(self) -> None:
        service = MemoryService()
        assert service.user_name_label == DEFAULT_USER_NAME_LABEL
        assert service.user_info_label_prefix == DEFAULT_USER_INFO_LABEL_PREFIX
        assert service.topics_label == DEFAULT_TOPICS_LABEL
        assert service.summary_header == DEFAULT_SUMMARY_HEADER
        assert service.recent_header == DEFAULT_RECENT_HEADER
        assert service.recent_header_full == DEFAULT_RECENT_HEADER_FULL
        assert service.user_turn_label == DEFAULT_USER_TURN_LABEL
        assert service.ai_turn_label == DEFAULT_AI_TURN_LABEL
        assert service.facts_header == DEFAULT_FACTS_HEADER

    @pytest.mark.asyncio
    async def test_default_context_string_byte_equivalent(self) -> None:
        """미설정 시 get_context_string이 기존 한국어 출력과 byte 단위 동치인지 검증."""
        service = MemoryService()
        service.summary_enabled = False  # 기본 경로(전체 대화 표시) 강제
        session_id = "sess-default"
        _seed_history(service, session_id)
        session: dict[str, Any] = {
            "user_name": "철수",
            "user_info": {"나이": 30},
            "topics": ["환불", "배송"],
            "facts": {"이름": "철수", "나이": "30살"},
        }

        result = await service.get_context_string(session_id, session)

        expected = "\n".join(
            [
                "사용자 이름: 철수",
                "사용자 나이: 30",
                "대화 주제: 환불, 배송",
                "\n최근 대화 내역:",
                "사용자: 안녕하세요",
                "AI: 무엇을 도와드릴까요?",
                "\n기억된 정보:",
                "- 이름: 철수",
                "- 나이: 30살",
            ]
        )
        assert result == expected


class TestOverrideLabelsViaConfig:
    """(b)(c) config 오버라이드 시 라벨 교체 + 실제 출력 반영 (데드 키 아님)."""

    def _english_config(self) -> dict[str, Any]:
        return {
            "session": {
                "context_labels": {
                    "user_name_label": "User name",
                    "user_info_label_prefix": "User",
                    "topics_label": "Topics",
                    "summary_header": "[Previous conversation summary]",
                    "recent_header": "[Recent conversation]",
                    "recent_header_full": "Recent conversation:",
                    "user_turn_label": "User",
                    "ai_turn_label": "AI",
                    "facts_header": "Remembered info:",
                }
            }
        }

    def test_label_attributes_are_overridden(self) -> None:
        service = MemoryService(config=self._english_config())
        assert service.user_name_label == "User name"
        assert service.user_info_label_prefix == "User"
        assert service.topics_label == "Topics"
        assert service.summary_header == "[Previous conversation summary]"
        assert service.recent_header == "[Recent conversation]"
        assert service.recent_header_full == "Recent conversation:"
        assert service.user_turn_label == "User"
        assert service.ai_turn_label == "AI"
        assert service.facts_header == "Remembered info:"

    @pytest.mark.asyncio
    async def test_english_context_string_reflects_override(self) -> None:
        service = MemoryService(config=self._english_config())
        service.summary_enabled = False
        session_id = "sess-en"
        _seed_history(service, session_id)
        session: dict[str, Any] = {
            "user_name": "Alice",
            "user_info": {"age": 42},
            "topics": ["refund", "shipping"],
            "facts": {"name": "Alice"},
        }

        result = await service.get_context_string(session_id, session)

        # recent_header_full / facts_header 는 "\n" 접두로 append되므로 join 시 빈 줄이 생긴다
        # (한국어 기본 경로와 동일한 구조 — 라벨만 영어로 치환됨).
        expected = "\n".join(
            [
                "User name: Alice",
                "User age: 42",
                "Topics: refund, shipping",
                "\nRecent conversation:",
                "User: 안녕하세요",
                "AI: 무엇을 도와드릴까요?",
                "\nRemembered info:",
                "- name: Alice",
            ]
        )
        assert result == expected


class TestInvalidLabelConfigFallsBackToDefault:
    """비정상 config(타입 불일치/공백)는 코드 기본값으로 폴백 (회귀 0)."""

    def test_non_dict_context_labels_falls_back(self) -> None:
        service = MemoryService(config={"session": {"context_labels": "invalid"}})
        assert service.user_name_label == DEFAULT_USER_NAME_LABEL
        assert service.user_turn_label == DEFAULT_USER_TURN_LABEL

    def test_blank_label_falls_back(self) -> None:
        service = MemoryService(
            config={"session": {"context_labels": {"user_turn_label": "   "}}}
        )
        assert service.user_turn_label == DEFAULT_USER_TURN_LABEL


class TestSummaryPromptTemplate:
    """요약 프롬프트 외부화: 미설정 기본값 + 오버라이드 + 플레이스홀더 검증."""

    def test_default_summary_prompt_is_builtin(self) -> None:
        service = MemoryService()
        assert service.summary_prompt_template == DEFAULT_SUMMARY_PROMPT_TEMPLATE
        assert "{full_text}" in service.summary_prompt_template

    def test_summary_prompt_override(self) -> None:
        custom = "Summarize:\n{full_text}\nSummary:"
        service = MemoryService(
            config={
                "session": {
                    "conversation_summary": {"summary_prompt_template": custom}
                }
            }
        )
        assert service.summary_prompt_template == custom

    def test_summary_prompt_without_placeholder_falls_back(self) -> None:
        """{full_text} 누락 시 대화 본문이 주입되지 않으므로 기본값으로 폴백."""
        service = MemoryService(
            config={
                "session": {
                    "conversation_summary": {
                        "summary_prompt_template": "Summarize without body"
                    }
                }
            }
        )
        assert service.summary_prompt_template == DEFAULT_SUMMARY_PROMPT_TEMPLATE

    def test_blank_summary_prompt_falls_back(self) -> None:
        service = MemoryService(
            config={
                "session": {
                    "conversation_summary": {"summary_prompt_template": "   "}
                }
            }
        )
        assert service.summary_prompt_template == DEFAULT_SUMMARY_PROMPT_TEMPLATE
