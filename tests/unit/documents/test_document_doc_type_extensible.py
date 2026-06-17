"""
Document doc_type 검증 도메인 중립화/확장성 테스트 (14차 범용화)

Document.__post_init__의 닫힌 enum(FAQ/Guidebook/ChatLog/WebLink/Custom)을
도메인 중립 기본(FAQ/Custom) + factory.register() 확장으로 바꾼 변경을 검증한다.
register()로 등록한 커스텀 종류가 Document 검증을 통과해야 한다(닫힌 enum이
register() 확장성과 충돌하던 잠재 버그 해소). 대소문자 무시.
"""


import pytest

from app.modules.core.documents.base import BaseDocumentProcessor
from app.modules.core.documents.factory import DocumentProcessorFactory
from app.modules.core.documents.models import Document


class TestDocTypeValidation:
    def test_faq_allowed(self):
        """기존 'FAQ' 종류 허용 (회귀 0)."""
        doc = Document(source="data/faq.xlsx", doc_type="FAQ", data=[])
        assert doc.doc_type == "FAQ"

    def test_custom_allowed(self):
        doc = Document(source="x", doc_type="Custom", data=[])
        assert doc.doc_type == "Custom"

    def test_case_insensitive(self):
        """factory 소문자 키와 Document TitleCase 불일치를 흡수한다."""
        doc = Document(source="x", doc_type="faq", data=[])
        assert doc.doc_type == "faq"

    def test_unregistered_type_rejected(self):
        """등록·기본에 없는 종류는 거부(typo 방지 유지)."""
        with pytest.raises(ValueError, match="Invalid doc_type"):
            Document(source="x", doc_type="Manual", data=[])

    def test_default_set_is_domain_neutral(self):
        """기본 허용 집합에 도메인 placeholder(Guidebook 등)가 없다."""
        assert "Guidebook" not in Document.VALID_DOC_TYPES
        assert "WebLink" not in Document.VALID_DOC_TYPES
        assert Document.VALID_DOC_TYPES >= {"FAQ", "Custom"}


class _DummyProcessor(BaseDocumentProcessor):
    def load(self, source):  # type: ignore[override]
        return Document(source=source, doc_type="Custom", data=[])


class TestRegisterExtendsValidTypes:
    def test_registered_type_allowed_in_document(self):
        """register()로 등록한 커스텀 종류가 Document 검증을 통과한다."""
        try:
            DocumentProcessorFactory.register("manual", _DummyProcessor)
            # register가 Document.VALID_DOC_TYPES에 추가 → 생성 통과(대소문자 무시)
            assert Document(source="x", doc_type="manual", data=[]).doc_type == "manual"
            assert Document(source="x", doc_type="Manual", data=[]).doc_type == "Manual"
        finally:
            # 전역 상태 정리
            DocumentProcessorFactory._processors.pop("manual", None)
            Document.VALID_DOC_TYPES.discard("manual")
