"""
IngestionService 제목 정제 config 외부화 테스트

★ 하드코딩 제거 검증: 기본은 제목을 정제하지 않으며(notion_extractor.py와 통일),
domain.batch.title_strip_chars로 옵트인 시에만 마커가 제거되는지(데드 키 아님) 검증한다.
"""

from unittest.mock import AsyncMock

from app.modules.ingestion.service import IngestionService


class TestTitleStripConfig:
    """제목 정제 문자 주입 + 기본 무정제 검증"""

    def _service(self, config: dict | None) -> IngestionService:
        return IngestionService(
            vector_store=AsyncMock(),
            metadata_store=AsyncMock(),
            config=config,
        )

    def test_default_no_strip_keeps_star(self) -> None:
        """기본(미설정) 시 ★를 제거하지 않음(notion_extractor.py와 통일, 회귀 0)"""
        service = self._service(None)
        chars = service._get_title_strip_chars()
        assert chars == []

        # ★는 그대로 보존, 양끝 공백만 제거
        cleaned = service._clean_title("  ★삼성전자  ", chars)
        assert cleaned == "★삼성전자"

    def test_empty_domain_config_no_strip(self) -> None:
        """domain은 있으나 batch 비면 정제 안 함(회귀 0)"""
        service = self._service({"domain": {}})
        assert service._get_title_strip_chars() == []

    def test_configured_strip_chars_applied(self) -> None:
        """config로 ★ 옵트인 시 제거됨(데드 키 해소)"""
        config = {"domain": {"batch": {"title_strip_chars": ["★"]}}}
        service = self._service(config)
        chars = service._get_title_strip_chars()
        assert chars == ["★"]

        cleaned = service._clean_title("★삼성전자", chars)
        assert cleaned == "삼성전자"

    def test_multiple_markers_stripped(self) -> None:
        """여러 마커 지정 시 모두 제거"""
        config = {"domain": {"batch": {"title_strip_chars": ["★", "●", "◆"]}}}
        service = self._service(config)
        chars = service._get_title_strip_chars()

        cleaned = service._clean_title("★●삼성◆전자", chars)
        assert cleaned == "삼성전자"

    def test_clean_title_strips_whitespace_only_by_default(self) -> None:
        """strip_chars 비면 양끝 공백만 제거(다른 마커 보존)"""
        cleaned = IngestionService._clean_title("  ●중요  ", [])
        assert cleaned == "●중요"
