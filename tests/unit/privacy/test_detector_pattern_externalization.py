"""
HybridPIIDetector 정규식 패턴 외부화 테스트

review 서브시스템(detector.py)의 PII 정규식이 __init__ 인자로
오버라이드 가능한지(데드 상수 아님), 미설정 시 한국 기본 패턴으로
폴백하는지(회귀 0, 보안 약화 없음) 검증한다.
"""

from app.modules.core.privacy.review import (
    HybridPIIDetector,
    PIIType,
)


class TestDetectorPatternExternalization:
    """detector 정규식 키별 오버라이드 + 기본 폴백 검증"""

    def _detector(self, patterns: dict[str, str] | None = None) -> HybridPIIDetector:
        """NER 비활성(빠름) + 패턴 오버라이드만 받는 헬퍼"""
        return HybridPIIDetector(
            enable_ner=False,
            whitelist=[],
            patterns=patterns,
        )

    def test_default_patterns_unchanged(self) -> None:
        """patterns 미설정 시 한국 기본 패턴 그대로 적용(회귀 0)"""
        det = self._detector(None)

        # 한국 개인 전화번호 탐지(기존 동작)
        ents = det.detect("연락처는 010-1234-5678입니다.")
        assert any(e.entity_type == PIIType.PHONE for e in ents)

        # 주민등록번호 탐지(기존 동작)
        ents = det.detect("주민번호 901225-1234567")
        assert any(e.entity_type == PIIType.SSN for e in ents)

    def test_default_pattern_constants_match_compiled(self) -> None:
        """기본 상수가 실제 컴파일된 인스턴스 패턴과 일치(데드 상수 아님)"""
        det = self._detector(None)
        assert det.SSN_PATTERN.pattern == HybridPIIDetector.DEFAULT_SSN_PATTERN
        assert det.PHONE_PATTERN.pattern == HybridPIIDetector.DEFAULT_PHONE_PATTERN
        assert det.CARD_PATTERN.pattern == HybridPIIDetector.DEFAULT_CARD_PATTERN
        assert det.EMAIL_PATTERN.pattern == HybridPIIDetector.DEFAULT_EMAIL_PATTERN

    def test_override_single_key_applies(self) -> None:
        """phone 키만 미국 형식으로 오버라이드 → 미국 전화 탐지(데드 키 해소)"""
        det = self._detector({"phone": r"\d{3}-\d{3}-\d{4}"})

        # 미국 전화 형식이 탐지되어야 함
        ents = det.detect("Call me at 415-555-1234 please.")
        assert any(e.entity_type == PIIType.PHONE for e in ents)
        assert det.PHONE_PATTERN.pattern == r"\d{3}-\d{3}-\d{4}"

    def test_unset_keys_fall_back_to_default(self) -> None:
        """일부 키만 오버라이드해도 나머지는 한국 기본 패턴 유지(보안 약화 없음)"""
        det = self._detector({"phone": r"\d{3}-\d{3}-\d{4}"})

        # ssn은 오버라이드 안 했으므로 한국 기본 패턴이 그대로 동작해야 함
        assert det.SSN_PATTERN.pattern == HybridPIIDetector.DEFAULT_SSN_PATTERN
        ents = det.detect("주민번호 901225-1234567")
        assert any(e.entity_type == PIIType.SSN for e in ents)

    def test_empty_patterns_dict_equals_default(self) -> None:
        """빈 dict 주입 시 전부 기본 패턴 폴백(회귀 0)"""
        det = self._detector({})
        assert det.SSN_PATTERN.pattern == HybridPIIDetector.DEFAULT_SSN_PATTERN
        assert det.PHONE_PATTERN.pattern == HybridPIIDetector.DEFAULT_PHONE_PATTERN
