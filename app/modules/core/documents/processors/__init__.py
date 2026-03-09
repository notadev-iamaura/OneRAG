"""
Document Processors - 문서 유형별 처리 전략 모듈

문서 유형에 따른 특화된 프로세서를 제공:
- FAQProcessor: FAQ 문서 처리 (MVP)
- PointRuleProcessor: 포인트 규정 처리 (MVP)
- GuidebookProcessor: 가이드북 처리 (Phase 2)
- ChatLogProcessor: 채팅 로그 대화 처리 (Phase 2)

사용 예시:
    from app.modules.core.documents.processors import FAQProcessor, PointRuleProcessor

    processor = FAQProcessor()
    chunks = processor.process('data/faq.xlsx')

    point_processor = PointRuleProcessor()
    chunks = point_processor.process('data/포인트 규정.xlsx')
"""

from .faq_processor import FAQProcessor
from .point_rule_processor import PointRuleProcessor

__all__ = [
    "FAQProcessor",
    "PointRuleProcessor",
]
