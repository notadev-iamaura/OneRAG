"""
MetadataChunker 섹션 폴백 라벨 외부화 테스트 (11차 범용화)

classify_section 미분류 폴백 "기타"와 split_by_section_header 기본 헤더
"일반"을 생성자 파라미터/config로 외부화한 변경을 검증한다(미설정 시
한국어 기본 유지 → 회귀 0). 이 라벨은 인덱싱 청크 메타데이터로 저장된다.
"""

from app.batch.metadata_chunker import (
    DEFAULT_SECTION_HEADER,
    DEFAULT_SECTION_LABEL,
    MetadataChunker,
    classify_section,
    split_by_section_header,
)


class TestClassifySectionDefaultLabel:
    def test_default_korean_label(self):
        """키워드 미매칭 시 기본 한국어 라벨 "기타" (회귀 0)."""
        assert classify_section("무관한 텍스트", {}) == "기타"
        assert DEFAULT_SECTION_LABEL == "기타"

    def test_override_default_label(self):
        """default_label 주입 시 미분류 폴백이 그 값이 된다."""
        assert classify_section("무관한 텍스트", {}, "Others") == "Others"

    def test_matched_keyword_unaffected_by_default(self):
        result = classify_section("가격 문의", {"pricing": ["가격"]}, "Others")
        assert result == "pricing"


class TestSplitBySectionHeaderDefault:
    def test_default_korean_header(self):
        """헤더 없는 선행 내용은 기본 헤더 "일반" (회귀 0)."""
        result = split_by_section_header("헤더 없는 내용")
        assert result == [("일반", "헤더 없는 내용")]
        assert DEFAULT_SECTION_HEADER == "일반"

    def test_override_default_header(self):
        result = split_by_section_header("헤더 없는 내용", "General")
        assert result == [("General", "헤더 없는 내용")]


class TestChunkerStoresLabels:
    def test_defaults(self):
        chunker = MetadataChunker()
        assert chunker.default_section_label == "기타"
        assert chunker.default_section_header == "일반"

    def test_override(self):
        chunker = MetadataChunker(
            default_section_label="Others", default_section_header="General"
        )
        assert chunker.default_section_label == "Others"
        assert chunker.default_section_header == "General"
