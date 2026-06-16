"""
FAQProcessor use_konlpy 파라미터 노출 테스트 (12차 범용화)

기본 추출기의 KoNLPy(한국어 전용 형태소 분석기) 사용 여부가 코드에
True로 하드코딩돼 비한국어 운영자가 끌 수 없던 것을, 형제 파라미터
(category_keywords 등)와 동일하게 생성자로 노출한 변경을 검증한다.
기본 True로 회귀 0.

주: konlpy 미설치 환경에서는 RuleBasedExtractor.__init__이 use_konlpy=True여도
ImportError 폴백으로 self.use_konlpy=False가 되므로, 최종 속성이 아니라
FAQProcessor가 추출기에 어떤 use_konlpy 값을 '전달'하는지(호출 인자)를 검증한다.
"""

from unittest.mock import patch

from app.modules.core.documents.metadata.rule_based import RuleBasedExtractor
from app.modules.core.documents.processors.faq_processor import FAQProcessor

_EXTRACTOR_PATH = "app.modules.core.documents.processors.faq_processor.RuleBasedExtractor"


class TestFaqUseKonlpyForwarding:
    def test_default_forwards_true(self):
        """기본값으로 use_konlpy=True가 추출기에 전달된다(회귀 0)."""
        with patch(_EXTRACTOR_PATH, wraps=RuleBasedExtractor) as mock_ext:
            FAQProcessor()
        assert mock_ext.call_args.kwargs["use_konlpy"] is True

    def test_forwards_false_when_disabled(self):
        """use_konlpy=False가 추출기에 전달된다(비한국어 운영자 비활성화)."""
        with patch(_EXTRACTOR_PATH, wraps=RuleBasedExtractor) as mock_ext:
            FAQProcessor(use_konlpy=False)
        assert mock_ext.call_args.kwargs["use_konlpy"] is False

    def test_disabled_skips_konlpy_import(self):
        """use_konlpy=False면 추출기가 한국어 의존성 로드를 시도하지 않는다."""
        proc = FAQProcessor(use_konlpy=False)
        assert proc.metadata_extractor.use_konlpy is False

    def test_custom_extractor_unaffected(self):
        custom = RuleBasedExtractor(use_konlpy=False)
        proc = FAQProcessor(metadata_extractor=custom, use_konlpy=True)
        assert proc.metadata_extractor is custom
