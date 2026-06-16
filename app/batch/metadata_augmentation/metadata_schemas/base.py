"""
메타데이터 스키마 베이스 클래스

모든 카테고리 스키마가 상속하는 공통 기능 정의:
- 금액 문자열 → 정수 변환
- 날짜 문자열 파싱
- null 값 처리
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, model_validator

# =========================================================================
# 파싱 규칙 코드 기본값(범용화: 회귀 안전판)
# -------------------------------------------------------------------------
# 한국어 의존 파싱 토큰/규칙을 코드 기본값으로만 보존하고, 운영자는
# set_parsing_config()로 config(domain.metadata.schema.parsing)를 주입해
# 다른 통화권/언어를 코드 포크 없이 지원한다. config 미설정 시 아래 기본값을
# 사용해 기존 한국어 파싱 결과와 동치를 유지한다(회귀 0).
#
# ⚠️ 언어 중립 fallback은 config와 무관하게 항상 유지된다:
#   - 순수 숫자 추출(parse_currency)
#   - ISO(YYYY-MM-DD)/점표기(2025.01.01) 날짜(parse_date)
#   - true/false/o/x/yes/no 불리언(parse_boolean) — 기본 토큰에 포함
# =========================================================================

# null로 해석할 마커(언어 중립 null/none/n/a/- + 한국어 '없음').
_DEFAULT_NULL_TOKENS: tuple[str, ...] = ("null", "none", "n/a", "-", "없음")

# 통화 파싱: 제거할 기호 목록 + 단위 승수 맵(예: 만=10000, 천=1000).
# 한국어 기본: 쉼표/원 기호/공백 제거 후 만·천 단위 산술.
_DEFAULT_CURRENCY_STRIP_SYMBOLS: tuple[str, ...] = (",", "원", " ")
_DEFAULT_CURRENCY_UNIT_MULTIPLIERS: dict[str, int] = {"만": 10000, "천": 1000}

# 날짜 파싱: YYYY-MM-DD 정규화용 정규식 패턴 목록.
# 각 패턴은 (year, month, day) 순서의 3개 캡처 그룹을 가져야 한다.
# ISO/점표기는 언어 중립이라 코드에서 항상 우선 처리하고, 아래는 추가
# 언어 의존 패턴(한국어 년월일)만 둔다. 2자리 연도는 20xx로 보정한다.
_DEFAULT_DATE_PATTERNS: tuple[str, ...] = (r"(\d{2,4})년\s*(\d{1,2})월\s*(\d{1,2})일",)

# 불리언 파싱: True/False로 매핑할 토큰 목록(소문자 비교).
# 언어 중립 토큰(true/false/o/x/yes/no)을 기본 포함하고, 한국어 토큰을 동봉한다.
_DEFAULT_BOOLEAN_TRUE_TOKENS: tuple[str, ...] = (
    "true",
    "가능",
    "있음",
    "o",
    "예",
    "yes",
    "포함",
)
_DEFAULT_BOOLEAN_FALSE_TOKENS: tuple[str, ...] = (
    "false",
    "불가",
    "없음",
    "x",
    "아니오",
    "no",
    "미포함",
)

# 날짜 null 마커는 통화와 동일 집합을 쓰되 '없음'은 날짜에서 의미가 약해
# 기존 동작(null/none/n/a/-)을 유지한다. 통화/불리언과 달리 별도 상수로 둔다.
_DEFAULT_DATE_NULL_TOKENS: tuple[str, ...] = ("null", "none", "n/a", "-")


class BaseMetadataSchema(BaseModel):
    """메타데이터 스키마 베이스 클래스"""

    model_config = ConfigDict(
        # 추가 필드 허용 (LLM이 예상 외 필드 생성 시)
        extra="ignore",
        # 필드명 유효성 검사 강화
        validate_default=True,
        # JSON 직렬화 시 별칭 사용
        populate_by_name=True,
    )

    # 서브클래스에서 오버라이드할 필수 필드 목록
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    # ---- 파싱 규칙 클래스 레벨 설정(config 주입 가능, 미설정 시 코드 기본값) ----
    # parse_currency/parse_date/parse_boolean이 @classmethod로 호출되므로
    # 인스턴스 상태가 아닌 클래스 레벨에 설정을 둔다. set_parsing_config()로
    # 앱/배치 시작 시 주입하며, 미설정 시 한국어 기본값으로 회귀 0을 보장한다.
    _null_tokens: ClassVar[tuple[str, ...]] = _DEFAULT_NULL_TOKENS
    _currency_strip_symbols: ClassVar[tuple[str, ...]] = _DEFAULT_CURRENCY_STRIP_SYMBOLS
    _currency_unit_multipliers: ClassVar[dict[str, int]] = dict(
        _DEFAULT_CURRENCY_UNIT_MULTIPLIERS
    )
    _date_patterns: ClassVar[tuple[str, ...]] = _DEFAULT_DATE_PATTERNS
    _date_null_tokens: ClassVar[tuple[str, ...]] = _DEFAULT_DATE_NULL_TOKENS
    _boolean_true_tokens: ClassVar[tuple[str, ...]] = _DEFAULT_BOOLEAN_TRUE_TOKENS
    _boolean_false_tokens: ClassVar[tuple[str, ...]] = _DEFAULT_BOOLEAN_FALSE_TOKENS

    @classmethod
    def set_parsing_config(cls, parsing: dict[str, Any] | None) -> None:
        """
        파싱 규칙을 config로 외부 주입합니다(앱/배치 시작 시 호출).

        config(domain.metadata.schema.parsing) 구조 예시::

            parsing:
              null_tokens: ["null", "none", "n/a", "-", "없음"]
              currency:
                strip_symbols: [",", "원", " "]
                unit_multipliers: {"만": 10000, "천": 1000}
              date_patterns:
                - "(\\d{2,4})년\\s*(\\d{1,2})월\\s*(\\d{1,2})일"
              boolean_true_tokens: ["true", "가능", "있음", "o", "예", "yes", "포함"]
              boolean_false_tokens: ["false", "불가", "없음", "x", "아니오", "no", "미포함"]

        Args:
            parsing: 파싱 설정 딕셔너리. None이거나 키가 없으면 해당 항목은
                코드 기본값(한국어 + 언어 중립)을 유지한다 → 미설정 시 회귀 0.
                각 키를 명시하면 해당 항목만 교체된다(병합 아님).

        Note:
            언어 중립 fallback(순수 숫자, ISO/점표기 날짜)은 config와 무관하게
            항상 적용되며 이 메서드로 비활성화할 수 없다(정확성 보존).
        """
        if not parsing:
            return

        null_tokens = parsing.get("null_tokens")
        if isinstance(null_tokens, list) and null_tokens:
            cls._null_tokens = tuple(str(t).lower() for t in null_tokens)

        currency = parsing.get("currency")
        if isinstance(currency, dict):
            strip_symbols = currency.get("strip_symbols")
            if isinstance(strip_symbols, list) and strip_symbols:
                cls._currency_strip_symbols = tuple(str(s) for s in strip_symbols)
            unit_multipliers = currency.get("unit_multipliers")
            if isinstance(unit_multipliers, dict) and unit_multipliers:
                cls._currency_unit_multipliers = {
                    str(k): int(v) for k, v in unit_multipliers.items()
                }

        date_patterns = parsing.get("date_patterns")
        if isinstance(date_patterns, list):
            # 빈 리스트도 명시 의도로 존중(언어 의존 패턴 비활성화).
            # ISO/점표기는 언어 중립이라 별도로 항상 처리된다.
            cls._date_patterns = tuple(str(p) for p in date_patterns)

        date_null_tokens = parsing.get("date_null_tokens")
        if isinstance(date_null_tokens, list) and date_null_tokens:
            cls._date_null_tokens = tuple(str(t).lower() for t in date_null_tokens)

        true_tokens = parsing.get("boolean_true_tokens")
        if isinstance(true_tokens, list) and true_tokens:
            cls._boolean_true_tokens = tuple(str(t).lower() for t in true_tokens)

        false_tokens = parsing.get("boolean_false_tokens")
        if isinstance(false_tokens, list) and false_tokens:
            cls._boolean_false_tokens = tuple(str(t).lower() for t in false_tokens)

    @classmethod
    def reset_parsing_config(cls) -> None:
        """파싱 규칙을 코드 기본값(한국어 + 언어 중립)으로 복원합니다(테스트/재초기화용)."""
        cls._null_tokens = _DEFAULT_NULL_TOKENS
        cls._currency_strip_symbols = _DEFAULT_CURRENCY_STRIP_SYMBOLS
        cls._currency_unit_multipliers = dict(_DEFAULT_CURRENCY_UNIT_MULTIPLIERS)
        cls._date_patterns = _DEFAULT_DATE_PATTERNS
        cls._date_null_tokens = _DEFAULT_DATE_NULL_TOKENS
        cls._boolean_true_tokens = _DEFAULT_BOOLEAN_TRUE_TOKENS
        cls._boolean_false_tokens = _DEFAULT_BOOLEAN_FALSE_TOKENS

    @classmethod
    def parse_currency(cls, value: Any) -> int | None:
        """
        금액 문자열을 정수로 변환합니다.

        단위 승수(만/천 등)와 제거 기호는 config로 외부화되며, 미설정 시
        한국어 기본값을 사용한다(회귀 0). 순수 숫자 추출 fallback은 언어
        중립이라 config와 무관하게 항상 적용된다.

        지원 형식(코드 기본값):
        - "50,000원" → 50000
        - "5만원" → 50000
        - "5만 5천원" → 55000
        - "55000" → 55000
        - 55000 → 55000

        Args:
            value: 금액 문자열 또는 숫자

        Returns:
            정수 금액 또는 None
        """
        if value is None:
            return None

        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return int(value)

        if not isinstance(value, str):
            return None

        # 빈 문자열 / null 마커 처리(언어 중립 + config 주입 가능)
        value = value.strip()
        if not value or value.lower() in cls._null_tokens:
            return None

        # 숫자만 있는 경우(언어 중립)
        if value.isdigit():
            return int(value)

        # 설정된 제거 기호 제거(쉼표/통화 기호/공백 등)
        cleaned = value
        for symbol in cls._currency_strip_symbols:
            cleaned = cleaned.replace(symbol, "")

        # 단위 승수 변환(예: 만=10000, 천=1000 / k=1000, m=1000000)
        result = 0
        matched_unit = False
        for unit, multiplier in cls._currency_unit_multipliers.items():
            unit_match = re.search(rf"(\d+){re.escape(unit)}", cleaned)
            if unit_match:
                result += int(unit_match.group(1)) * multiplier
                matched_unit = True

        # 단위가 하나도 없으면 숫자만 추출(언어 중립 fallback)
        if not matched_unit:
            numbers = re.findall(r"\d+", cleaned)
            if numbers:
                result = int("".join(numbers))

        return result if result > 0 else None

    @classmethod
    def parse_date(cls, value: Any) -> str | None:
        """
        날짜 문자열을 YYYY-MM-DD 형식으로 변환합니다.

        ISO(YYYY-MM-DD)/점표기(2025.01.01)는 언어 중립이라 코드에서 항상 우선
        처리하고, 언어 의존 패턴(한국어 년월일 등)은 config(date_patterns)로
        외부화한다. 미설정 시 한국어 패턴을 기본값으로 사용한다(회귀 0).

        지원 형식(코드 기본값):
        - "2025-01-01"
        - "25년 1월 1일"
        - "2025.01.01"

        Args:
            value: 날짜 문자열

        Returns:
            YYYY-MM-DD 형식 문자열 또는 None
        """
        if value is None:
            return None

        if isinstance(value, date):
            return value.isoformat()

        if not isinstance(value, str):
            return None

        value = value.strip()
        if not value or value.lower() in cls._date_null_tokens:
            return None

        # YYYY-MM-DD 형식(언어 중립, 항상 우선)
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return value

        # 점 형식: 2025.01.01(언어 중립, 항상 처리)
        dot_match = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", value)
        if dot_match:
            year = dot_match.group(1)
            month = dot_match.group(2).zfill(2)
            day = dot_match.group(3).zfill(2)
            return f"{year}-{month}-{day}"

        # 언어 의존 패턴(config 주입 / 코드 기본 = 한국어 년월일).
        # 각 패턴은 (year, month, day) 순서 3개 캡처 그룹을 가진다.
        for pattern in cls._date_patterns:
            lang_match = re.search(pattern, value)
            if lang_match:
                year = lang_match.group(1)
                if len(year) == 2:
                    year = f"20{year}"
                month = lang_match.group(2).zfill(2)
                day = lang_match.group(3).zfill(2)
                return f"{year}-{month}-{day}"

        return value  # 파싱 실패 시 원본 반환

    @classmethod
    def parse_boolean(cls, value: Any) -> bool | None:
        """
        불리언 값을 파싱합니다.

        True/False 매핑 토큰은 config로 외부화되며, 미설정 시 한국어 + 언어
        중립(true/false/o/x/yes/no) 기본 토큰을 사용한다(회귀 0).

        지원 형식(코드 기본값):
        - true/false
        - "가능"/"불가", "있음"/"없음"
        - "O"/"X"

        Args:
            value: 불리언 값 또는 문자열

        Returns:
            불리언 값 또는 None
        """
        if value is None:
            return None

        if isinstance(value, bool):
            return value

        if not isinstance(value, str):
            return None

        value = value.strip().lower()

        if value in cls._boolean_true_tokens:
            return True
        if value in cls._boolean_false_tokens:
            return False

        return None

    @model_validator(mode="after")
    def validate_required_fields(self) -> BaseMetadataSchema:
        """필수 필드가 비어있지 않은지 검증합니다."""
        for field_name in self.REQUIRED_FIELDS:
            value = getattr(self, field_name, None)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValueError(f"필수 필드 '{field_name}'이(가) 비어있습니다.")
        return self

    def to_display_dict(self, field_aliases: dict[str, str]) -> dict[str, Any]:
        """
        한글 별칭을 키로 사용하는 딕셔너리를 반환합니다.

        Args:
            field_aliases: 필드명 → 한글 별칭 매핑

        Returns:
            한글 키를 사용하는 딕셔너리
        """
        result = {}
        for field_name, value in self.model_dump().items():
            if value is not None:
                alias = field_aliases.get(field_name, field_name)
                result[alias] = value
        return result

    def get_filled_field_count(self) -> tuple[int, int]:
        """
        채워진 필드 수와 전체 필드 수를 반환합니다.

        Returns:
            (채워진 필드 수, 전체 필드 수)
        """
        data = self.model_dump()
        total = len(data)
        filled = sum(1 for v in data.values() if v is not None)
        return filled, total

    def get_extraction_rate(self) -> float:
        """
        추출율(%)을 반환합니다.

        Returns:
            추출율 (0.0 ~ 100.0)
        """
        filled, total = self.get_filled_field_count()
        return (filled / total * 100) if total > 0 else 0.0
