"""
SimpleChunker content 폴백 언어중립화 테스트 (13차 범용화)

_format_content의 placeholder-없는-템플릿 폴백이 한국어 라벨('질문:'/'답변:')
대신 언어중립 결합을 쓰도록 바꾼 변경(잠재 누출 제거)을 검증한다.

주: 동의어 스키마(BM25SynonymConfig) origin 파일명 제거는 app/config/schemas.py
(패키지 app/config/schemas/에 가려진 dead 모듈)에서 수행했으나, 해당 모듈은
import 불가능한 shadowed dead code라 단위 테스트 대상이 아니다.
"""

from app.modules.core.documents.chunking.simple_chunker import SimpleChunker


class TestNeutralContentFallback:
    def test_default_template_unaffected(self):
        """기본 언어중립 템플릿은 그대로 동작(회귀 0)."""
        chunker = SimpleChunker()
        out = chunker._format_content("Q1", "A1")
        assert out == "Q1\nA1"

    def test_label_less_template_fallback_is_neutral(self):
        """placeholder 없는 템플릿 주입 시 폴백이 한국어 라벨을 넣지 않는다."""
        chunker = SimpleChunker(content_template="no placeholders here")
        out = chunker._format_content("Q1", "A1")
        assert "질문:" not in out
        assert "답변:" not in out
        assert out == "Q1\nA1"

    def test_korean_template_still_supported(self):
        """한국어 라벨이 필요하면 content_template로 명시 주입(여전히 지원)."""
        chunker = SimpleChunker(content_template="질문: {question}\n답변: {answer}")
        out = chunker._format_content("Q1", "A1")
        assert out == "질문: Q1\n답변: A1"
