"""
MetadataChunker 도메인 범용화 테스트

웨딩 스튜디오/예약업 도메인 키워드 하드코딩을 제거하고
domain.yaml 주입으로 전환한 변경을 검증한다.

핵심 단언:
- (a) config 미설정 시 도메인 키워드가 적용되지 않음(모든 청크 = "기타")
- (b) section_keywords 주입 시 섹션 분류가 동작
"""

from app.batch.metadata_chunker import (
    DEFAULT_SECTION_KEYWORDS,
    DEFAULT_TARGET_FIELDS,
    MetadataChunker,
    classify_section,
)


class TestSectionKeywordsNeutralDefault:
    """기본값(도메인 중립) 검증"""

    def test_default_section_keywords_is_empty(self) -> None:
        """코드 기본 섹션 키워드는 빈 dict(도메인 중립)여야 한다"""
        assert DEFAULT_SECTION_KEYWORDS == {}, (
            "OSS 기본 배포는 도메인 중립이어야 한다. "
            "특정 도메인 키워드(취소/환불/원본/수정본 등)가 코드에 남으면 안 됨"
        )

    def test_default_target_fields_is_domain_neutral(self) -> None:
        """기본 청킹 대상 필드는 도메인 범용 필드만 포함해야 한다"""
        # 웨딩/예약 도메인 필드(비용/정책/구성/혜택)가 코드 기본값에 없어야 함
        domain_specific = {"비용", "정책", "구성", "혜택"}
        assert not domain_specific.intersection(DEFAULT_TARGET_FIELDS), (
            f"도메인 특화 필드가 기본값에 남아있음: {DEFAULT_TARGET_FIELDS}"
        )

    def test_classify_section_returns_etc_without_keywords(self) -> None:
        """키워드 미주입 시 어떤 텍스트든 '기타'로 분류"""
        # 과거 웨딩 도메인 키워드였던 단어들도 분류되지 않아야 함
        assert classify_section("취소 및 환불 패널티 안내") == "기타"
        assert classify_section("원본/수정본 추가금 비용 안내") == "기타"
        assert classify_section("역세권 주차 위치") == "기타"

    def test_chunker_default_is_neutral(self) -> None:
        """청커 기본 생성 시 section_keywords가 비어 있어야 한다"""
        chunker = MetadataChunker()
        assert chunker.section_keywords == {}


class TestSectionKeywordsInjection:
    """domain.yaml 주입 시 섹션 분류 동작 검증"""

    def test_injected_keywords_classify_section(self) -> None:
        """주입한 키워드로 섹션 분류가 동작해야 한다"""
        keywords = {
            "의료": ["진료", "처방", "투약"],
            "보험": ["보험", "청구", "보장"],
        }
        assert classify_section("진료 및 처방 안내", keywords) == "의료"
        assert classify_section("보험 청구 보장 범위", keywords) == "보험"
        # 매칭 안 되면 기타
        assert classify_section("관련 없는 일반 텍스트", keywords) == "기타"

    def test_chunker_uses_injected_keywords(self) -> None:
        """청커에 주입한 키워드가 청킹 결과 섹션에 반영되어야 한다"""
        keywords = {"의료": ["진료", "처방"]}
        chunker = MetadataChunker(
            section_keywords=keywords,
            target_fields=["내용"],
        )
        result = chunker.chunk_entity_data(
            entity_id="m-001",
            entity_name="진료 안내",
            category="병원",
            properties={"내용": "진료 시간 및 처방전 발급 안내입니다."},
        )
        assert result.total_chunks > 0
        assert "의료" in result.sections_found

    def test_chunker_neutral_default_classifies_as_etc(self) -> None:
        """기본(중립) 청커는 청크를 '기타'로만 분류해야 한다"""
        chunker = MetadataChunker(target_fields=["내용"])
        result = chunker.chunk_entity_data(
            entity_id="m-002",
            entity_name="취소 환불 안내",
            category="예약",
            properties={"내용": "취소 및 환불 패널티 비용 안내입니다."},
        )
        assert result.total_chunks > 0
        assert result.sections_found == ["기타"]
