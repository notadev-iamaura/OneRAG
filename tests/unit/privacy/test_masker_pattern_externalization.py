"""
PrivacyMasker PII 패턴/이름/파일명 config 외부화 테스트

검증 목표 (백엔드 범용화 Wave):
1. (회귀 0) config 미설정 시 기본 마스킹이 현 한국 패턴과 byte-identical
2. (오버라이드) patterns config로 타 국가 PII 패턴 추가/교체 시 그 패턴도 마스킹
3. (부분 폴백) 일부 키만 오버라이드 시 누락 키는 한국 기본 패턴 유지(보안 약화 금지)
4. (이름 글자클래스/파일명 라벨) name_char_class·filename_mask_label 외부화
5. (기존 버그 수정) name_suffixes 주입 시 이름 패턴이 실제로 마스킹(과거 f-string 버그)
"""

from __future__ import annotations

from app.modules.core.privacy.masker import (
    DEFAULT_FILENAME_MASK_LABEL,
    DEFAULT_NAME_CHAR_CLASS,
    DEFAULT_PII_PATTERNS,
    PrivacyMasker,
)


class TestDefaultPatternRegressionZero:
    """config 미설정 시 한국 기본 패턴과 동치(회귀 0)"""

    def test_default_phone_masking_unchanged(self) -> None:
        m = PrivacyMasker()
        assert m.mask_text("010-1234-5678") == "010-****-5678"
        assert m.mask_text("01012345678") == "010****5678"

    def test_default_business_phone_not_masked(self) -> None:
        m = PrivacyMasker()
        # 사업자 전화번호(지역번호)는 마스킹 제외 — 보안/오탐 동작 유지
        assert m.mask_text("02-123-4567") == "02-123-4567"

    def test_default_ssn_masking_unchanged(self) -> None:
        m = PrivacyMasker()
        assert m.mask_text("990101-1234567") == "990101-*******"

    def test_default_passport_masking_unchanged(self) -> None:
        m = PrivacyMasker()
        assert m.mask_text("M12345678") == "M********"

    def test_default_driver_license_masking_unchanged(self) -> None:
        m = PrivacyMasker()
        assert m.mask_text("13-05-123456-78") == "13-**-******-**"

    def test_default_pattern_constants_match_compiled(self) -> None:
        """기본 패턴 상수가 실제 컴파일된 패턴과 일치(데드 상수 아님)"""
        m = PrivacyMasker()
        assert m.SSN_PATTERN.pattern == DEFAULT_PII_PATTERNS["ssn"]
        assert m.PERSONAL_PHONE_PATTERN.pattern == DEFAULT_PII_PATTERNS["phone_personal"]
        assert m.PASSPORT_PATTERN.pattern == DEFAULT_PII_PATTERNS["passport"]

    def test_default_name_char_class_and_label(self) -> None:
        m = PrivacyMasker()
        assert DEFAULT_NAME_CHAR_CLASS == "[가-힣]"
        assert DEFAULT_FILENAME_MASK_LABEL == "고객"
        assert m._filename_mask_label == "고객"


class TestForeignPatternOverride:
    """타 국가 패턴 추가/교체 시 그 패턴도 마스킹"""

    def test_us_ssn_pattern_masked(self) -> None:
        m = PrivacyMasker(patterns={"ssn": r"\d{3}-\d{2}-\d{4}"})
        result = m.mask_text("SSN: 123-45-6789")
        assert "123-45-6789" not in result, "미국 SSN이 마스킹되어야 한다"

    def test_us_phone_pattern_masked(self) -> None:
        m = PrivacyMasker(patterns={"phone_personal": r"\d{3}-\d{3}-\d{4}"})
        result = m.mask_text("call 555-123-4567")
        assert "555-123-4567" not in result, "미국 전화가 마스킹되어야 한다"

    def test_latin_name_char_class_override(self) -> None:
        m = PrivacyMasker(
            name_char_class=r"[A-Za-z]",
            name_suffixes=["Customer", "Manager"],
        )
        result = m.mask_text("Hello John Customer here")
        assert "John Customer" not in result, "라틴 이름이 마스킹되어야 한다"
        assert "J" in result, "성(첫 글자)은 노출되어야 한다"

    def test_filename_mask_label_override(self) -> None:
        m = PrivacyMasker(filename_mask_label="CLIENT")
        assert m.mask_filename("홍길동 고객님.txt") == "CLIENT_고객님.txt"


class TestPartialOverrideKeepsKoreanDefault:
    """부분 오버라이드 시 누락 키는 한국 기본 패턴 유지(보안 약화 금지)"""

    def test_passport_override_keeps_korean_phone(self) -> None:
        m = PrivacyMasker(patterns={"passport": r"[A-Z]{2}\d{7}"})
        # 한국 전화 패턴은 그대로 유지되어야 한다
        assert m.mask_text("010-1234-5678") == "010-****-5678"
        # 한국 SSN도 그대로 유지
        assert m.mask_text("990101-1234567") == "990101-*******"

    def test_empty_pattern_value_ignored(self) -> None:
        """빈 문자열/None 패턴은 무시되어 기본 패턴이 유지된다(마스킹 약화 차단)"""
        m = PrivacyMasker(patterns={"ssn": "", "passport": None})  # type: ignore[dict-item]
        assert m.mask_text("990101-1234567") == "990101-*******"
        assert m.mask_text("M12345678") == "M********"

    def test_none_patterns_equals_default(self) -> None:
        m_none = PrivacyMasker(patterns=None)
        m_default = PrivacyMasker()
        sample = "010-1234-5678 990101-1234567 M12345678 13-05-123456-78"
        assert m_none.mask_text(sample) == m_default.mask_text(sample)


class TestNameSuffixBugFix:
    """name_suffixes 주입 시 이름 패턴이 실제로 마스킹(과거 f-string {2,4} 버그 회귀 차단)"""

    def test_injected_suffixes_actually_mask_name(self) -> None:
        # 과거: f-string 안의 {2,4}가 (2, 4)로 해석돼 패턴이 깨져 마스킹 실패
        m = PrivacyMasker(name_suffixes=["고객님", "담당자님?"])
        assert m.mask_text("홍길동 고객님") == "홍** 고객님"
        assert m.mask_text("이영희 담당자님") == "이** 담당자님"

    def test_injected_suffixes_mask_filename(self) -> None:
        m = PrivacyMasker(name_suffixes=["고객님", "담당자님?"])
        assert m.mask_filename("홍길동 고객님.txt") == "고객_고객님.txt"
        assert m.mask_filename("이영희 담당자님.txt") == "고객_담당자님.txt"

    def test_injected_suffixes_detected_by_contains_pii(self) -> None:
        m = PrivacyMasker(name_suffixes=["고객님"])
        assert m.contains_pii("홍길동 고객님") is True
