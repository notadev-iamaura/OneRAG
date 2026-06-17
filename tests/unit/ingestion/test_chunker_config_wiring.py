"""
IngestionService → MetadataChunker config 배선 테스트

domain.yaml의 `domain.batch.section_keywords`/`target_fields`가 실제로
MetadataChunker에 전달되는지(데드 config 키가 아닌지) 검증한다.

핵심 단언:
- (c) ingestion 경로가 config를 실제로 chunker에 전달함(데드 키 아님)
- config 미설정 시 도메인 중립 기본값 사용
"""

from unittest.mock import AsyncMock

from app.modules.ingestion.service import IngestionService


class TestChunkerConfigWiring:
    """IngestionService가 config로 chunker를 구성하는지 검증"""

    def _make_service(self, config: dict | None) -> IngestionService:
        """config만 주입한 IngestionService 생성 헬퍼"""
        return IngestionService(
            vector_store=AsyncMock(),
            metadata_store=AsyncMock(),
            config=config,
        )

    def test_section_keywords_flow_into_chunker(self) -> None:
        """domain.batch.section_keywords가 chunker에 전달되어야 한다(데드 키 아님)"""
        config = {
            "domain": {
                "batch": {
                    "section_keywords": {"의료": ["진료", "처방"]},
                    "target_fields": ["내용", "설명"],
                }
            }
        }
        service = self._make_service(config)

        # 데드 키 해소 증명: config 값이 그대로 chunker에 반영되어야 함
        assert service.chunker.section_keywords == {"의료": ["진료", "처방"]}
        assert service.chunker.target_fields == ["내용", "설명"]

    def test_injected_keywords_affect_chunking_result(self) -> None:
        """config로 주입한 키워드가 실제 청킹 섹션 분류에 반영되어야 한다"""
        config = {
            "domain": {
                "batch": {
                    "section_keywords": {"의료": ["진료", "처방"]},
                    "target_fields": ["내용"],
                }
            }
        }
        service = self._make_service(config)
        result = service.chunker.chunk_entity_data(
            entity_id="d-001",
            entity_name="진료 안내",
            category="병원",
            properties={"내용": "진료 시간 및 처방전 발급 안내."},
        )
        assert "의료" in result.sections_found

    def test_no_config_uses_neutral_defaults(self) -> None:
        """config 미설정 시 도메인 중립 기본값(빈 section_keywords)을 사용해야 한다"""
        service = self._make_service(None)
        assert service.chunker.section_keywords == {}

    def test_empty_domain_config_uses_neutral_defaults(self) -> None:
        """domain 키는 있으나 batch가 비면 중립 기본값을 사용해야 한다"""
        service = self._make_service({"domain": {}})
        assert service.chunker.section_keywords == {}

    def test_explicit_chunker_overrides_config(self) -> None:
        """명시적으로 chunker를 주입하면 config보다 우선해야 한다"""
        from app.batch.metadata_chunker import MetadataChunker

        custom = MetadataChunker(section_keywords={"우선": ["override"]})
        service = IngestionService(
            vector_store=AsyncMock(),
            metadata_store=AsyncMock(),
            config={"domain": {"batch": {"section_keywords": {"무시": ["ignored"]}}}},
            chunker=custom,
        )
        assert service.chunker is custom
        assert service.chunker.section_keywords == {"우선": ["override"]}
