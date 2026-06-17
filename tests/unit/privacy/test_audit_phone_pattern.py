"""
감사 메타데이터 정제 전화 패턴 단일소스 테스트 (8차 범용화)

PIIAuditLogger._sanitize_metadata의 인라인 전화 정규식 하드코딩을
클래스 상수(DEFAULT_AUDIT_PHONE_PATTERN) + 생성자 오버라이드로 분리한
변경을 검증한다. 미설정 시 한국 기본 동작 유지(회귀 0).
"""

from app.modules.core.privacy.review.audit import PIIAuditLogger


class TestAuditPhonePattern:
    def test_default_masks_korean_phone(self):
        """기본 패턴으로 한국 전화번호를 마스킹한다 (회귀 0)."""
        logger = PIIAuditLogger(collection=None)
        out = logger._sanitize_metadata({"memo": "연락처 010-1234-5678 입니다"})
        assert "010-1234-5678" not in out["memo"]
        assert "***-****-****" in out["memo"]

    def test_non_string_values_preserved(self):
        logger = PIIAuditLogger(collection=None)
        out = logger._sanitize_metadata({"count": 3, "ok": True})
        assert out["count"] == 3
        assert out["ok"] is True

    def test_constructor_override_pattern(self):
        """생성자 phone_pattern 오버라이드가 정제에 반영된다."""
        # 공백 구분 미국식 패턴
        logger = PIIAuditLogger(
            collection=None, phone_pattern=r"\d{3} \d{3} \d{4}"
        )
        out = logger._sanitize_metadata({"memo": "call 123 456 7890"})
        assert "123 456 7890" not in out["memo"]
        assert "***-****-****" in out["memo"]

    def test_default_pattern_constant_is_single_source(self):
        """기본 패턴이 클래스 상수에서 컴파일됨(인라인 하드코딩 제거 확인)."""
        logger = PIIAuditLogger(collection=None)
        assert logger._phone_pattern.pattern == PIIAuditLogger.DEFAULT_AUDIT_PHONE_PATTERN
