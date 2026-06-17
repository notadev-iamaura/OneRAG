"""
관리자 분석 엔티티 분포 필드 config 파생 테스트 (7차 범용화)

weaviate_admin_router의 엔티티 분포 통계가 집계 필드를 코드에
하드코딩("entity_name")하던 것을 domain.metadata.entity_distribution_field
config로 파생하도록 바꾼 변경을 검증한다(미설정 시 기본값 폴백 → 회귀 0).
"""

from unittest.mock import patch

from app.api.routers import weaviate_admin_router as mod

# 함수 내부에서 지연 임포트되므로 원본 심볼 경로를 패치 대상으로 한다.
_LOAD_CONFIG = "app.lib.config_loader.load_config"


class TestResolveEntityDistributionField:
    def test_default_when_config_unset(self):
        """미설정(빈 config) 시 기본 'entity_name'으로 폴백한다 (회귀 0)."""
        with patch(_LOAD_CONFIG, return_value={}):
            assert mod._resolve_entity_distribution_field() == "entity_name"

    def test_default_when_key_null(self):
        cfg = {"domain": {"metadata": {"entity_distribution_field": None}}}
        with patch(_LOAD_CONFIG, return_value=cfg):
            assert mod._resolve_entity_distribution_field() == "entity_name"

    def test_override_from_config(self):
        """운영자가 다른 도메인 필드명을 지정하면 그 값을 집계한다."""
        cfg = {"domain": {"metadata": {"entity_distribution_field": "item_title"}}}
        with patch(_LOAD_CONFIG, return_value=cfg):
            assert mod._resolve_entity_distribution_field() == "item_title"

    def test_blank_override_falls_back_to_default(self):
        cfg = {"domain": {"metadata": {"entity_distribution_field": "   "}}}
        with patch(_LOAD_CONFIG, return_value=cfg):
            assert mod._resolve_entity_distribution_field() == "entity_name"

    def test_config_load_failure_falls_back_to_default(self):
        """config 로드 실패해도 기본 필드로 graceful 폴백한다."""
        with patch(_LOAD_CONFIG, side_effect=RuntimeError("boom")):
            assert mod._resolve_entity_distribution_field() == "entity_name"
