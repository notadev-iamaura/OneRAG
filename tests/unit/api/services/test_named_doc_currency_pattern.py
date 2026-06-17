"""
named_document_rescue 고가치 패턴 통화 국제화 테스트 (16차 범용화)

_NAMED_DOCUMENT_HIGH_VALUE_PATTERN이 한국 원화('원')만 인식하고 ₩/¥/元/円
등 타 통화를 누락하던 비대칭을, 국제 통화 기본셋으로 확장한 변경을 검증한다.
한국어 기본('원') 유지(회귀 0) + 타 통화 동등 인식.
"""

from app.api.services.rag_pipeline import _NAMED_DOCUMENT_HIGH_VALUE_PATTERN as PAT


class TestCurrencyPattern:
    def test_korean_won_still_matched(self):
        """한국어 기본 통화 '원' 계속 인식 (회귀 0)."""
        assert PAT.search("총 10000원 입니다")

    def test_international_currencies_matched(self):
        """₩/¥/元/円/$/€/£ 국제 통화도 동등 인식."""
        for amount in ["100₩", "100¥", "100元", "100円", "100$", "100€", "100£"]:
            assert PAT.search(amount), f"미매칭: {amount}"

    def test_non_currency_signals_unaffected(self):
        """URL/연락처/날짜 등 기존 신호는 그대로 인식(회귀 0)."""
        assert PAT.search("https://example.com")
        assert PAT.search("tel 02-1234-5678")
        assert PAT.search("2024-01-01")
        assert PAT.search("12.5 kg")
