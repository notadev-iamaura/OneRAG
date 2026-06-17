"""
RuleBasedExtractor 정규식 패턴(NUMERIC/DATE/PHONE) 도메인 범용화 테스트

한국 통화(원/만원/₩)·한국 날짜(년월일)·한국 전화형식 정규식 하드코딩을
생성자 파라미터 + config 주입으로 전환한 변경을 검증한다.

핵심 단언:
- (a) config 미설정 시 한국어 기본 패턴으로 동작(회귀 0)
- (b) numeric_pattern/date_pattern/phone_pattern 주입 시 다른 통화/날짜/전화 매칭
"""

from __future__ import annotations

from app.modules.core.documents.metadata.rule_based import RuleBasedExtractor
from app.modules.core.documents.models import Chunk


def _chunk(text: str) -> Chunk:
    return Chunk(content=text)


class TestPatternDefaultRegression:
    """기본 패턴(한국어) 회귀 0 검증"""

    def test_korean_numeric_detected_by_default(self) -> None:
        extractor = RuleBasedExtractor(use_konlpy=False)
        meta = extractor.extract(_chunk("이 상품의 가격은 50,000원입니다."))
        assert meta["contains_numeric"] is True

    def test_korean_date_detected_by_default(self) -> None:
        extractor = RuleBasedExtractor(use_konlpy=False)
        meta = extractor.extract(_chunk("행사 기간은 2025년 1월 1일까지입니다."))
        assert meta["has_date"] is True

    def test_korean_phone_detected_by_default(self) -> None:
        extractor = RuleBasedExtractor(use_konlpy=False)
        meta = extractor.extract(_chunk("문의 전화는 02-1234-5678 입니다."))
        assert meta["has_phone"] is True

    def test_usd_not_detected_by_korean_default(self) -> None:
        """한국어 기본 패턴은 USD 통화를 매칭하지 않는다(현 동작 보존)."""
        extractor = RuleBasedExtractor(use_konlpy=False)
        meta = extractor.extract(_chunk("The price is $50,000 only here."))
        assert meta["contains_numeric"] is False


class TestPatternConfigInjection:
    """패턴 config 주입 검증 — 다른 통화/날짜/전화"""

    def test_injected_usd_numeric_pattern(self) -> None:
        extractor = RuleBasedExtractor(
            use_konlpy=False,
            numeric_pattern=r"\$\d{1,3}(,\d{3})*",
        )
        meta = extractor.extract(_chunk("The price is $50,000 only here."))
        assert meta["contains_numeric"] is True

    def test_injected_iso_date_pattern(self) -> None:
        extractor = RuleBasedExtractor(
            use_konlpy=False,
            date_pattern=r"\d{4}-\d{2}-\d{2}",
        )
        meta = extractor.extract(_chunk("Event date is 2025-01-01 for sure here."))
        assert meta["has_date"] is True

    def test_injected_intl_phone_pattern(self) -> None:
        extractor = RuleBasedExtractor(
            use_konlpy=False,
            phone_pattern=r"\+\d{1,3}\s?\d{3,4}\s?\d{4}",
        )
        meta = extractor.extract(_chunk("Call us at +1 555 1234 anytime please."))
        assert meta["has_phone"] is True

    def test_default_patterns_class_vars_preserved(self) -> None:
        """클래스 변수 기본 패턴은 회귀 안전판으로 유지되어야 한다."""
        assert hasattr(RuleBasedExtractor, "DEFAULT_NUMERIC_PATTERN")
        assert hasattr(RuleBasedExtractor, "DEFAULT_DATE_PATTERN")
        assert hasattr(RuleBasedExtractor, "DEFAULT_PHONE_PATTERN")
