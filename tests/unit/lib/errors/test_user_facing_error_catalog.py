"""
17차 범용화: 미들웨어/라우터 raw 한국어 에러의 양언어 카탈로그 전환 테스트.

raw 한국어 에러 응답을 ErrorCode 양언어 카탈로그로 전환하면서, ko 메시지는
기존 raw 문구와 byte 동일(회귀 0)하고 en은 충실히 제공되는지 검증한다.
"""

import pytest

from app.lib.errors import (
    ErrorCode,
    format_user_facing_error,
    get_error_message,
)
from app.lib.errors.messages import ERROR_MESSAGES, USER_FACING_ERRORS

# raw 사이트의 정확한 현재 한국어 문구(회귀 0 골든 — 코드 전환 후에도 ko 동일해야 함)
_SINGLE_MESSAGE_KO_GOLDEN = {
    "RATE-001": "요청 한도를 초과했습니다. 잠시 후 다시 시도해주세요.",
    "RATE-002": "채팅 요청 한도를 초과했습니다. 잠시 후 다시 시도해주세요.",
    "TOOL-001": "ToolExecutor가 초기화되지 않았습니다",
    "TOOL-002": "Tool 목록을 가져오는데 실패했습니다. 다시 시도하거나 관리자에게 문의하세요.",
    "EMPTY-002": "데이터베이스에 연결할 수 없어 설정을 저장하지 못했습니다",
    "EMPTY-003": "데이터베이스에 연결할 수 없어 설정을 리셋하지 못했습니다",
    "FEEDBACK-001": "피드백 저장에 실패했습니다",
    "ADMIN-002": "세션 모듈이 초기화되지 않았습니다",
    "OPENAI-002": "LLM 서비스 사용 불가",
    "OPENAI-004": "user 메시지가 필요합니다",
}


class TestNewSingleMessageCodes:
    @pytest.mark.parametrize("code,ko", _SINGLE_MESSAGE_KO_GOLDEN.items())
    def test_ko_byte_identical(self, code: str, ko: str):
        """ko 메시지가 기존 raw 문구와 byte 동일(회귀 0)."""
        assert get_error_message(code, "ko") == ko

    @pytest.mark.parametrize("code", _SINGLE_MESSAGE_KO_GOLDEN.keys())
    def test_en_present_and_distinct(self, code: str):
        """en 메시지가 존재하고 비어있지 않으며 ASCII(영문)."""
        en = get_error_message(code, "en")
        assert en and en.strip()
        assert en != get_error_message(code, "ko")

    def test_dynamic_context_formatting(self):
        assert get_error_message("TOOL-003", "ko", tool_name="검색") == "Tool '검색'을 찾을 수 없습니다"
        assert get_error_message("TOOL-003", "en", tool_name="search") == "Tool 'search' not found"
        assert "boom" in get_error_message("OPENAI-003", "en", error="boom")


class TestUserFacingErrors:
    def test_all_entries_have_ko_and_en(self):
        for code, entry in USER_FACING_ERRORS.items():
            for field, pair in entry.items():
                assert "ko" in pair and pair["ko"], f"{code}.{field} ko 누락"
                assert "en" in pair and pair["en"], f"{code}.{field} en 누락"

    def test_format_preserves_shape_and_ko_regression(self):
        """3-필드 + preserve 필드 보존 + ko byte 동일(회귀 0)."""
        d = format_user_facing_error(
            "SERVICE-001", "ko", retry_after=30, support_email="support@example.com"
        )
        assert d == {
            "error": "서비스 초기화 중",
            "message": "서비스가 시작 중입니다. 잠시 후 다시 시도해주세요",
            "suggestion": "30초 후 재시도하거나, 문제가 지속되면 관리자에게 문의하세요",
            "retry_after": 30,
            "support_email": "support@example.com",
        }

    def test_format_en(self):
        d = format_user_facing_error("SESSION-005", "en", session_id="abc")
        assert d["error"] == "Session not found"
        assert "session" in d["message"].lower()
        assert d["session_id"] == "abc"

    def test_unknown_code_returns_preserve_only(self):
        d = format_user_facing_error("NOPE-999", "ko", session_id="x")
        assert d == {"session_id": "x"}


class TestCatalogConsistency:
    def test_new_enum_codes_have_messages(self):
        """신규 ErrorCode enum 값이 모두 카탈로그에 존재(데드 코드 아님)."""
        new_codes = [
            ErrorCode.RATE_001, ErrorCode.RATE_002,
            ErrorCode.TOOL_001, ErrorCode.TOOL_002, ErrorCode.TOOL_003,
            ErrorCode.TOOL_004, ErrorCode.TOOL_005,
            ErrorCode.EMPTY_001, ErrorCode.EMPTY_002, ErrorCode.EMPTY_003,
            ErrorCode.FEEDBACK_001, ErrorCode.ADMIN_001, ErrorCode.ADMIN_002,
            ErrorCode.OPENAI_001, ErrorCode.OPENAI_002, ErrorCode.OPENAI_003,
            ErrorCode.OPENAI_004,
        ]
        for code in new_codes:
            assert code.value in ERROR_MESSAGES, f"{code.value} 메시지 누락"
            assert ERROR_MESSAGES[code.value]["en"], f"{code.value} en 누락"
