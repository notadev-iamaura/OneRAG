"""
PrivacyMasker None 방어 테스트 (Phase 1.1)

목적:
    설정 누락으로 None 인자가 주입돼도 마스킹이 무력화되거나 크래시하지
    않도록 보장한다. 특히 phone_mask_char=None일 때 SSN 마스킹의
    `char * 7` 연산이 TypeError를 일으키던 회귀를 차단한다.
"""

from __future__ import annotations

from app.modules.core.privacy.masker import PrivacyMasker


def test_none_args_do_not_disable_masking() -> None:
    """None 인자로 생성해도 마스킹 플래그가 안전한 기본값으로 보정돼야 한다."""
    masker = PrivacyMasker(
        mask_phone=None,  # type: ignore[arg-type]
        mask_name=None,  # type: ignore[arg-type]
        mask_email=None,  # type: ignore[arg-type]
        phone_mask_char=None,  # type: ignore[arg-type]
        name_mask_char=None,  # type: ignore[arg-type]
    )
    assert masker.mask_phone is True
    assert masker.mask_name is True
    assert masker.phone_mask_char == "*"
    assert masker.name_mask_char == "*"


def test_ssn_masking_does_not_crash_with_none_char() -> None:
    """phone_mask_char=None 주입 시에도 SSN 텍스트가 크래시 없이 마스킹돼야 한다."""
    masker = PrivacyMasker(phone_mask_char=None)  # type: ignore[arg-type]
    result = masker.mask_text("주민번호 990101-1234567 입니다")
    # 크래시하지 않고 뒷자리가 마스킹되어야 함
    assert "1234567" not in result
    assert "990101" in result


def test_phone_masking_active_with_none_args() -> None:
    """None 인자 생성기로도 개인 전화번호가 실제로 마스킹돼야 한다."""
    masker = PrivacyMasker(
        mask_phone=None,  # type: ignore[arg-type]
        phone_mask_char=None,  # type: ignore[arg-type]
    )
    result = masker.mask_text("연락처는 010-1234-5678 입니다")
    assert "010-1234-5678" not in result
