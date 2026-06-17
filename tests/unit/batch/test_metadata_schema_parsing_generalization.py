"""
메타데이터 스키마 파서(parse_currency/parse_date/parse_boolean) 도메인 범용화 테스트

한국어 의존 파싱 토큰(원/만/천, 년월일, 가능/불가/예/아니오, null 마커 '없음')을
config 외부화한 변경을 검증한다. 라이브 경로는 GenericMetadataSchema가
notion 인제스천에서 _numeric_fields/_boolean_fields에 대해 parse_currency/
parse_boolean을 호출하는 것이다.

핵심 단언:
- (a) config 미설정 시 기존 한국어 파싱 결과와 동치(회귀 0)
- (b) 언어 중립 fallback(순수 숫자, ISO/점표기 날짜, true/false/o/x/yes/no)은 항상 유지
- (c) config 주입 시 USD/JPY 통화, 西暦 年月日, はい/いいえ 등 추가 파싱 가능
"""

from __future__ import annotations

import pytest

from app.batch.metadata_augmentation.metadata_schemas.base import BaseMetadataSchema
from app.batch.metadata_augmentation.metadata_schemas.generic import (
    GenericMetadataSchema,
)


@pytest.fixture(autouse=True)
def _reset_schema_config() -> None:
    """각 테스트 후 클래스 레벨 파싱 설정을 코드 기본값으로 복원한다."""
    yield
    BaseMetadataSchema.reset_parsing_config()


class TestCurrencyDefaultRegression:
    """parse_currency 한국어 기본값 회귀 0 검증"""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("50,000원", 50000),
            ("5만원", 50000),
            ("5만 5천원", 55000),
            ("55000", 55000),
            (55000, 55000),
            (None, None),
            ("없음", None),  # 한국어 null 마커
            ("null", None),  # 언어 중립 null 마커
        ],
    )
    def test_default_korean_currency(self, value: object, expected: int | None) -> None:
        assert BaseMetadataSchema.parse_currency(value) == expected

    def test_pure_number_fallback_is_language_neutral(self) -> None:
        """순수 숫자 추출 fallback은 config와 무관하게 유지된다(언어 중립)."""
        assert BaseMetadataSchema.parse_currency("12345") == 12345


class TestCurrencyConfigInjection:
    """parse_currency config 외부화 검증 — USD/JPY 등 추가 파싱"""

    def test_usd_unit_multiplier(self) -> None:
        """config로 $/k 단위와 strip 기호를 주입하면 USD 파싱이 가능하다."""
        BaseMetadataSchema.set_parsing_config(
            {
                "currency": {
                    "strip_symbols": ["$", ",", " "],
                    "unit_multipliers": {"k": 1000, "m": 1000000},
                }
            }
        )
        assert BaseMetadataSchema.parse_currency("$50,000") == 50000
        assert BaseMetadataSchema.parse_currency("50k") == 50000
        assert BaseMetadataSchema.parse_currency("2m") == 2000000

    def test_custom_null_tokens(self) -> None:
        """null_tokens를 교체하면 새 마커가 None으로 매핑된다."""
        BaseMetadataSchema.set_parsing_config({"null_tokens": ["なし", "null"]})
        assert BaseMetadataSchema.parse_currency("なし") is None


class TestDateDefaultRegression:
    """parse_date 한국어 기본값 회귀 0 검증"""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2025-01-01", "2025-01-01"),  # 언어 중립 ISO
            ("25년 1월 1일", "2025-01-01"),  # 한국어 년월일
            ("2025년 12월 31일", "2025-12-31"),
            ("2025.01.01", "2025-01-01"),  # 언어 중립 점표기
        ],
    )
    def test_default_korean_date(self, value: str, expected: str) -> None:
        assert BaseMetadataSchema.parse_date(value) == expected

    def test_iso_is_language_neutral(self) -> None:
        """ISO 표기는 config와 무관하게 항상 처리된다."""
        BaseMetadataSchema.set_parsing_config({"date_patterns": []})
        assert BaseMetadataSchema.parse_date("2025-06-15") == "2025-06-15"


class TestDateConfigInjection:
    """parse_date config 외부화 검증 — 일본어 年月日 등"""

    def test_japanese_date_pattern(self) -> None:
        """date_patterns에 일본어 年月日 패턴을 주입하면 정규화된다."""
        BaseMetadataSchema.set_parsing_config(
            {
                "date_patterns": [
                    r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日",
                ]
            }
        )
        assert BaseMetadataSchema.parse_date("2025年1月1日") == "2025-01-01"


class TestBooleanDefaultRegression:
    """parse_boolean 한국어 기본값 회귀 0 검증"""

    @pytest.mark.parametrize(
        "value,expected",
        [
            (True, True),
            (False, False),
            ("true", True),
            ("false", False),
            ("가능", True),
            ("불가", False),
            ("있음", True),
            ("없음", False),
            ("예", True),
            ("아니오", False),
            ("o", True),
            ("x", False),
            ("yes", True),
            ("no", False),
            ("포함", True),
            ("미포함", False),
            ("알수없음", None),
        ],
    )
    def test_default_korean_boolean(
        self, value: object, expected: bool | None
    ) -> None:
        assert BaseMetadataSchema.parse_boolean(value) == expected


class TestBooleanConfigInjection:
    """parse_boolean config 외부화 검증 — はい/いいえ 등"""

    def test_japanese_boolean_tokens(self) -> None:
        """boolean_true/false_tokens를 주입하면 일본어 불리언이 파싱된다."""
        BaseMetadataSchema.set_parsing_config(
            {
                "boolean_true_tokens": ["true", "はい", "o"],
                "boolean_false_tokens": ["false", "いいえ", "x"],
            }
        )
        assert BaseMetadataSchema.parse_boolean("はい") is True
        assert BaseMetadataSchema.parse_boolean("いいえ") is False

    def test_language_neutral_true_false_preserved_when_injected(self) -> None:
        """주입해도 true/false 같은 언어 중립 토큰을 포함하면 보존된다."""
        BaseMetadataSchema.set_parsing_config(
            {
                "boolean_true_tokens": ["true", "yes"],
                "boolean_false_tokens": ["false", "no"],
            }
        )
        assert BaseMetadataSchema.parse_boolean("true") is True
        assert BaseMetadataSchema.parse_boolean("no") is False


class TestGenericSchemaLivePath:
    """GenericMetadataSchema 라이브 경로(notion 인제스천)에서 파싱 동작 검증.

    라이브 경로는 pre_validate_and_parse(model_validator before)가 _numeric_fields/
    _boolean_fields에 대해 parse_currency/parse_boolean으로 dict를 in-place 변환하는
    지점이다. 따라서 변환 결과는 pre_validate_and_parse 출력으로 검증한다.
    """

    def test_numeric_field_uses_injected_currency_config(self) -> None:
        """set_validation_rules + set_parsing_config로 USD 필드가 파싱된다."""
        BaseMetadataSchema.set_parsing_config(
            {
                "currency": {
                    "strip_symbols": ["$", ",", " "],
                    "unit_multipliers": {"k": 1000},
                }
            }
        )
        GenericMetadataSchema.set_validation_rules(
            required=["name"], numeric=["price"], boolean=[]
        )
        parsed = GenericMetadataSchema.pre_validate_and_parse(
            {"Name": "Widget", "price": "$1,500"}
        )
        assert parsed["price"] == 1500

    def test_numeric_field_default_korean_regression(self) -> None:
        """config 미설정 시 한국어 통화 필드 파싱이 그대로 동작한다."""
        GenericMetadataSchema.set_validation_rules(
            required=["name"], numeric=["amount"], boolean=[]
        )
        parsed = GenericMetadataSchema.pre_validate_and_parse(
            {"Name": "상품", "amount": "5만원"}
        )
        assert parsed["amount"] == 50000

    def test_boolean_field_uses_injected_config(self) -> None:
        """set_parsing_config로 주입한 일본어 불리언 토큰이 라이브 경로에 반영된다."""
        BaseMetadataSchema.set_parsing_config(
            {
                "boolean_true_tokens": ["true", "はい"],
                "boolean_false_tokens": ["false", "いいえ"],
            }
        )
        GenericMetadataSchema.set_validation_rules(
            required=["name"], numeric=[], boolean=["active"]
        )
        parsed = GenericMetadataSchema.pre_validate_and_parse(
            {"Name": "X", "active": "はい"}
        )
        assert parsed["active"] is True
