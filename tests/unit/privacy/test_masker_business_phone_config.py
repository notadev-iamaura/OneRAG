"""
사업자 전화 판별 config 단일화 테스트 (8차 범용화)

_is_business_phone의 '010=개인, 02/0XX=사업자' 한국 규칙 하드코딩을
제거하고 config(privacy.yaml phone_business)에서 컴파일된
BUSINESS_PHONE_PATTERN을 단일 진실원천으로 쓰도록 바꾼 변경을 검증한다.
이전에 BUSINESS_PHONE_PATTERN은 컴파일만 되고 미사용 데드 키였다.
"""

from app.modules.core.privacy.masker import PrivacyMasker


class TestDefaultKoreanBehaviorUnchanged:
    def test_010_is_personal_not_business(self):
        """010 번호는 개인(사업자 아님) — 회귀 0."""
        m = PrivacyMasker()
        assert m._is_business_phone("010-1234-5678") is False

    def test_region_numbers_classified_business(self):
        """한국 지역번호(02, 031~)는 사업자로 분류 (기본 패턴 동작)."""
        m = PrivacyMasker()
        assert m._is_business_phone("02-123-4567") is True
        assert m._is_business_phone("031-123-4567") is True

    def test_personal_phone_still_masked(self):
        """개인전화 마스킹 동작 회귀 0."""
        m = PrivacyMasker()
        assert m.mask_text("010-1234-5678") == "010-****-5678"


class TestDeadKeyActivation:
    def test_business_pattern_override_takes_effect(self):
        """phone_business 오버라이드가 사업자 판별에 실제 반영된다(데드키 활성화)."""
        # 미국식 사업자 패턴으로 오버라이드
        m = PrivacyMasker(patterns={"phone_business": r"\d{3}-\d{3}-\d{4}"})
        assert m._is_business_phone("123-456-7890") is True
        # 한국 02 번호는 더 이상 이 패턴에 매칭되지 않음 → 오버라이드가 실제 적용됨
        assert m._is_business_phone("02-123-4567") is False

    def test_non_010_mobile_not_misclassified_as_business(self):
        """이전 하드코딩(0XX+10자리=사업자)이 011/016을 오판하던 결함이 제거됨.

        phone_personal을 011/016 포함으로 오버라이드해도, 한국 기본
        phone_business 패턴은 010/011/016을 사업자로 보지 않으므로
        개인전화로 올바르게 분류된다(마스킹 누락=PII 유출 방지).
        """
        m = PrivacyMasker(
            patterns={"phone_personal": r"01[16][-\s]?\d{3,4}[-\s]?\d{4}"}
        )
        assert m._is_business_phone("016-123-4567") is False
