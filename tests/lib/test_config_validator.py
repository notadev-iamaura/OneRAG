"""환경 변수 검증 테스트"""

import pytest

from app.lib.config_validator import (
    ConfigValidationError,
    get_env_bool,
    get_env_int,
    get_env_url,
)


class TestConfigValidator:
    """환경 변수 검증기 테스트"""

    def test_get_env_int_valid(self, monkeypatch):
        """정수 파싱 성공"""
        monkeypatch.setenv("TEST_PORT", "8080")
        assert get_env_int("TEST_PORT") == 8080

    def test_get_env_int_with_default(self, monkeypatch):
        """기본값 반환"""
        monkeypatch.delenv("TEST_PORT", raising=False)
        assert get_env_int("TEST_PORT", default=3000) == 3000

    def test_get_env_int_invalid_raises_error(self, monkeypatch):
        """잘못된 형식은 에러"""
        monkeypatch.setenv("TEST_PORT", "invalid")
        with pytest.raises(ConfigValidationError) as exc_info:
            get_env_int("TEST_PORT")
        assert "TEST_PORT" in str(exc_info.value)
        assert "invalid" in str(exc_info.value).lower()

    def test_get_env_bool_true_values(self, monkeypatch):
        """True 값들"""
        for val in ["true", "True", "1", "yes", "YES"]:
            monkeypatch.setenv("TEST_FLAG", val)
            assert get_env_bool("TEST_FLAG") is True

    def test_get_env_bool_false_values(self, monkeypatch):
        """False 값들"""
        for val in ["false", "False", "0", "no", "NO"]:
            monkeypatch.setenv("TEST_FLAG", val)
            assert get_env_bool("TEST_FLAG") is False

    def test_get_env_url_validates_scheme(self, monkeypatch):
        """URL 스킴 검증"""
        monkeypatch.setenv("TEST_URL", "https://example.com")
        assert get_env_url("TEST_URL") == "https://example.com"

        monkeypatch.setenv("TEST_URL", "invalid-url")
        with pytest.raises(ConfigValidationError):
            get_env_url("TEST_URL")

    def test_get_env_int_range_validation(self, monkeypatch):
        """정수 범위 검증"""
        monkeypatch.setenv("TEST_TIMEOUT", "30")
        assert get_env_int("TEST_TIMEOUT", min_value=1, max_value=60) == 30

        monkeypatch.setenv("TEST_TIMEOUT", "100")
        with pytest.raises(ConfigValidationError) as exc_info:
            get_env_int("TEST_TIMEOUT", max_value=60)
        assert "최대값" in str(exc_info.value)

    def test_get_env_url_require_https(self, monkeypatch):
        """HTTPS 필수 검증"""
        monkeypatch.setenv("TEST_SECURE_URL", "http://example.com")
        with pytest.raises(ConfigValidationError) as exc_info:
            get_env_url("TEST_SECURE_URL", require_https=True)
        assert "HTTPS" in str(exc_info.value)


class TestLenientCoercion:
    """coerce_int / coerce_float / get_env_float / strict=False 관대 모드 테스트"""

    def test_coerce_int_valid_and_clamped(self):
        from app.lib.config_validator import coerce_int

        assert coerce_int("10", 5) == 10
        assert coerce_int(7.9, 5) == 7
        assert coerce_int(0, 5, minimum=1) == 1
        assert coerce_int("99", 5, maximum=10) == 10

    def test_coerce_int_invalid_or_empty_uses_default(self):
        from app.lib.config_validator import coerce_int

        assert coerce_int("abc", 5) == 5
        assert coerce_int(None, 5) == 5
        assert coerce_int("", 5, minimum=7) == 7  # 기본값도 clamp
        assert coerce_int(object(), 5) == 5

    def test_coerce_float_valid_invalid_and_clamped(self):
        from app.lib.config_validator import coerce_float

        assert coerce_float("1.5", 1.0) == 1.5
        assert coerce_float("abc", 1.0) == 1.0
        assert coerce_float(None, 1.0) == 1.0
        assert coerce_float("9", 1.0, maximum=2.0) == 2.0
        assert coerce_float(0.0, 1.5, minimum=0.1) == 0.1

    def test_get_env_float_valid_and_default(self, monkeypatch):
        from app.lib.config_validator import get_env_float

        monkeypatch.setenv("TEST_RATIO", "0.75")
        assert get_env_float("TEST_RATIO") == 0.75
        monkeypatch.delenv("TEST_RATIO", raising=False)
        assert get_env_float("TEST_RATIO", default=1.5) == 1.5

    def test_get_env_float_strict_errors(self, monkeypatch):
        from app.lib.config_validator import get_env_float

        monkeypatch.delenv("TEST_RATIO", raising=False)
        with pytest.raises(ConfigValidationError):
            get_env_float("TEST_RATIO")

        monkeypatch.setenv("TEST_RATIO", "abc")
        with pytest.raises(ConfigValidationError) as exc_info:
            get_env_float("TEST_RATIO")
        assert "TEST_RATIO" in str(exc_info.value)

        monkeypatch.setenv("TEST_RATIO", "5")
        with pytest.raises(ConfigValidationError) as exc_info:
            get_env_float("TEST_RATIO", max_value=1.0)
        assert "최대값" in str(exc_info.value)
        with pytest.raises(ConfigValidationError) as exc_info:
            get_env_float("TEST_RATIO", min_value=10.0)
        assert "최소값" in str(exc_info.value)

    def test_get_env_int_lenient_mode(self, monkeypatch):
        """strict=False: 잘못된/빈 값은 기본값, 범위 밖은 clamp (예외 없음)"""
        monkeypatch.setenv("TEST_RETRIES", "abc")
        assert get_env_int("TEST_RETRIES", default=3, strict=False) == 3
        monkeypatch.setenv("TEST_RETRIES", "")
        assert get_env_int("TEST_RETRIES", default=3, strict=False) == 3
        monkeypatch.setenv("TEST_RETRIES", "-5")
        assert get_env_int("TEST_RETRIES", default=3, min_value=0, strict=False) == 0
        monkeypatch.setenv("TEST_RETRIES", "7")
        assert get_env_int("TEST_RETRIES", default=3, max_value=5, strict=False) == 5
        assert get_env_int("TEST_RETRIES", default=3, strict=False) == 7

    def test_get_env_float_lenient_mode(self, monkeypatch):
        from app.lib.config_validator import get_env_float

        monkeypatch.setenv("TEST_DELAY", "abc")
        assert get_env_float("TEST_DELAY", default=1.0, strict=False) == 1.0
        monkeypatch.setenv("TEST_DELAY", "")
        assert get_env_float("TEST_DELAY", default=1.0, strict=False) == 1.0
        monkeypatch.setenv("TEST_DELAY", "5")
        assert get_env_float("TEST_DELAY", default=1.0, max_value=1.0, strict=False) == 1.0
        monkeypatch.setenv("TEST_DELAY", "2.5")
        assert get_env_float("TEST_DELAY", default=1.0, strict=False) == 2.5

    def test_strict_mode_still_rejects_empty_string(self, monkeypatch):
        """strict=True(기본)는 빈 문자열을 정수가 아닌 값으로 거부한다 (기존 동작 보존)"""
        monkeypatch.setenv("TEST_PORT", "")
        with pytest.raises(ConfigValidationError):
            get_env_int("TEST_PORT", default=3000)

    def test_lenient_mode_requires_default(self, monkeypatch):
        from app.lib.config_validator import get_env_float

        monkeypatch.setenv("TEST_VALUE", "1")
        with pytest.raises(ConfigValidationError):
            get_env_int("TEST_VALUE", strict=False)
        with pytest.raises(ConfigValidationError):
            get_env_float("TEST_VALUE", strict=False)
