"""
여권번호·운전면허번호 PII 마스킹 테스트

TDD 방식: 먼저 테스트 작성 후 패턴 구현
한국 여권번호(M12345678)와 운전면허번호(12-34-567890-12) 마스킹을 검증합니다.
"""

import pytest
from pydantic import ValidationError

from app.modules.core.privacy import PrivacyMasker
from app.modules.core.privacy.masker import MaskingResult


class TestPassportPattern:
    """여권번호 패턴 마스킹 테스트"""

    @pytest.fixture
    def masker(self):
        """모든 마스킹 옵션 활성화"""
        return PrivacyMasker(
            mask_phone=True,
            mask_name=True,
            mask_ssn=True,
            mask_passport=True,
            mask_driver_license=True,
        )

    def test_mask_passport_standard_format(self, masker):
        """표준 여권번호 마스킹: M12345678 → M********"""
        text = "여권번호는 M12345678입니다."
        result = masker.mask_text(text)
        assert "M12345678" not in result, "여권번호가 마스킹되지 않았습니다"
        assert "M" in result, "여권번호 앞 영문자는 유지되어야 합니다"

    def test_mask_passport_lowercase_rejected(self, masker):
        """소문자 여권번호는 마스킹 대상이 아님 (표준 여권은 대문자)"""
        text = "m12345678은 유효한 여권번호가 아닙니다."
        result = masker.mask_text(text)
        assert "m12345678" in result, "소문자 여권번호는 마스킹하면 안 됩니다"

    def test_mask_passport_various_letters(self, masker):
        """다양한 알파벳 시작 여권번호"""
        for letter in ["M", "S", "R", "G"]:
            text = f"여권: {letter}98765432"
            result = masker.mask_text(text)
            assert f"{letter}98765432" not in result, f"{letter} 시작 여권번호 마스킹 실패"

    def test_passport_detailed_result_count(self, masker):
        """mask_text_detailed에서 passport_count 확인"""
        text = "여권번호 M12345678과 S87654321이 있습니다."
        result = masker.mask_text_detailed(text)
        assert result.passport_count == 2, f"여권번호 2개 감지 필요. 실제: {result.passport_count}"

    def test_passport_total_masked_includes_passport(self, masker):
        """total_masked에 passport_count 포함"""
        text = "여권번호는 M12345678입니다."
        result = masker.mask_text_detailed(text)
        assert result.total_masked >= 1, "total_masked에 여권번호가 포함되어야 합니다"

    def test_passport_contains_pii_detects_passport(self, masker):
        """contains_pii가 여권번호를 감지"""
        assert masker.contains_pii("여권: M12345678"), "여권번호가 PII로 감지되어야 합니다"
        assert not masker.contains_pii("모델번호: A1234"), "짧은 코드는 여권으로 오인 금지"

    def test_passport_disabled_by_default(self):
        """mask_passport=False일 때 마스킹 안 함"""
        masker = PrivacyMasker(mask_passport=False)
        text = "여권번호: M12345678"
        result = masker.mask_text(text)
        assert "M12345678" in result, "비활성화 시 여권번호 마스킹하면 안 됩니다"

    def test_passport_eight_digits_only(self, masker):
        """정확히 8자리만 매칭 (7자리, 9자리 제외)"""
        # 7자리는 매칭 안 됨
        assert masker.contains_pii("M1234567 ") is False or "M1234567" in masker.mask_text(
            "M1234567 "
        ), "7자리는 여권번호가 아닙니다"

    def test_passport_masking_format(self, masker):
        """마스킹 형식: 앞 영문자 유지, 숫자 부분 마스킹"""
        text = "M12345678"
        result = masker.mask_text(text)
        # M + 8개 마스킹 문자
        assert result.startswith("M"), "영문자는 유지"
        assert "12345678" not in result, "숫자는 마스킹되어야 함"


class TestDriverLicensePattern:
    """운전면허번호 패턴 마스킹 테스트"""

    @pytest.fixture
    def masker(self):
        """모든 마스킹 옵션 활성화"""
        return PrivacyMasker(
            mask_phone=True,
            mask_name=True,
            mask_ssn=True,
            mask_passport=True,
            mask_driver_license=True,
        )

    def test_mask_driver_license_standard_format(self, masker):
        """표준 운전면허번호 마스킹: 12-34-567890-12"""
        text = "운전면허번호는 11-22-334455-66입니다."
        result = masker.mask_text(text)
        assert "11-22-334455-66" not in result, "운전면허번호가 마스킹되지 않았습니다"

    def test_mask_driver_license_preserves_region_code(self, masker):
        """지역코드(앞 2자리) 유지"""
        text = "면허번호: 13-05-123456-78"
        result = masker.mask_text(text)
        assert "13-" in result, "지역코드는 유지되어야 합니다"
        assert "123456" not in result, "개인 식별 번호는 마스킹되어야 합니다"

    def test_driver_license_detailed_result_count(self, masker):
        """mask_text_detailed에서 driver_license_count 확인"""
        text = "면허 11-22-334455-66과 13-05-123456-78이 있습니다."
        result = masker.mask_text_detailed(text)
        assert result.driver_license_count == 2, (
            f"운전면허 2개 감지 필요. 실제: {result.driver_license_count}"
        )

    def test_driver_license_total_masked_includes_count(self, masker):
        """total_masked에 driver_license_count 포함"""
        text = "면허번호: 11-22-334455-66"
        result = masker.mask_text_detailed(text)
        assert result.total_masked >= 1, "total_masked에 운전면허가 포함되어야 합니다"

    def test_driver_license_contains_pii(self, masker):
        """contains_pii가 운전면허번호를 감지"""
        assert masker.contains_pii("면허: 13-05-123456-78"), "운전면허번호가 PII로 감지되어야 합니다"

    def test_driver_license_disabled_by_default(self):
        """mask_driver_license=False일 때 마스킹 안 함"""
        masker = PrivacyMasker(mask_driver_license=False)
        text = "면허번호: 11-22-334455-66"
        result = masker.mask_text(text)
        assert "11-22-334455-66" in result, "비활성화 시 면허번호 마스킹하면 안 됩니다"

    def test_driver_license_format_strict(self, masker):
        """정확한 포맷만 매칭 (XX-XX-XXXXXX-XX)"""
        # 포맷이 다르면 매칭 안 됨
        text = "11-2-334455-66"  # 두 번째 그룹이 1자리
        result = masker.mask_text(text)
        assert "11-2-334455-66" in result, "포맷이 다르면 마스킹하면 안 됩니다"


class TestMaskingResultExtension:
    """MaskingResult에 passport_count, driver_license_count 필드 추가 확인"""

    def test_masking_result_has_passport_count(self):
        """MaskingResult에 passport_count 필드 존재"""
        result = MaskingResult(
            original="test",
            masked="test",
            phone_count=0,
            name_count=0,
            ssn_count=0,
            passport_count=1,
            driver_license_count=0,
        )
        assert result.passport_count == 1

    def test_masking_result_has_driver_license_count(self):
        """MaskingResult에 driver_license_count 필드 존재"""
        result = MaskingResult(
            original="test",
            masked="test",
            phone_count=0,
            name_count=0,
            ssn_count=0,
            passport_count=0,
            driver_license_count=2,
        )
        assert result.driver_license_count == 2

    def test_total_masked_includes_all_types(self):
        """total_masked가 모든 PII 타입 합산"""
        result = MaskingResult(
            original="test",
            masked="test",
            phone_count=1,
            name_count=2,
            ssn_count=1,
            passport_count=1,
            driver_license_count=1,
        )
        assert result.total_masked == 6, f"1+2+1+1+1=6. 실제: {result.total_masked}"

    def test_masking_result_defaults_to_zero(self):
        """passport_count, driver_license_count 기본값 0"""
        result = MaskingResult(
            original="test",
            masked="test",
            phone_count=0,
            name_count=0,
        )
        assert result.passport_count == 0
        assert result.driver_license_count == 0


class TestPriorityOrder:
    """PII 처리 우선순위 테스트: SSN → 여권 → 면허 → 전화번호 → 이름"""

    @pytest.fixture
    def masker(self):
        return PrivacyMasker(
            mask_phone=True,
            mask_name=True,
            mask_ssn=True,
            mask_passport=True,
            mask_driver_license=True,
        )

    def test_mixed_pii_all_masked(self, masker):
        """여러 PII 타입이 섞여 있을 때 모두 마스킹"""
        text = (
            "주민번호 990101-1234567, "
            "여권 M12345678, "
            "면허 13-05-123456-78, "
            "전화 010-1234-5678"
        )
        result = masker.mask_text_detailed(text)
        assert result.ssn_count >= 1, "주민번호 감지"
        assert result.passport_count >= 1, "여권번호 감지"
        assert result.driver_license_count >= 1, "운전면허 감지"
        assert result.phone_count >= 1, "전화번호 감지"
        assert "990101-1234567" not in result.masked
        assert "M12345678" not in result.masked
        assert "13-05-123456-78" not in result.masked
        assert "010-1234-5678" not in result.masked
