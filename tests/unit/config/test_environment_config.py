"""
환경별 설정 분리 테스트

환경(development, test, production)에 따라 다른 설정값이 적용되는지 검증.
P2 항목: 설정 환경 분리
"""

import os
from unittest.mock import patch


class TestEnvironmentConfigSeparation:
    """환경별 설정 분리 테스트"""

    def test_production_reranking_min_score(self):
        """프로덕션 환경에서 reranking.min_score가 0.05인지 확인"""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=False):
            # 기존 환경변수 백업 및 프로덕션 관련 변수 제거
            # (is_production_environment가 True로 인식하도록)
            from app.lib.config_loader import ConfigLoader

            loader = ConfigLoader()
            loader.environment = "production"  # 강제 설정
            config = loader.load_config(validate=False)

            assert config.get("reranking", {}).get("min_score") == 0.05, (
                f"프로덕션에서 reranking.min_score는 0.05여야 함, "
                f"실제값: {config.get('reranking', {}).get('min_score')}"
            )

    def test_development_reranking_min_score(self):
        """개발 환경에서 reranking.min_score가 0.0인지 확인"""
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=False):
            from app.lib.config_loader import ConfigLoader

            loader = ConfigLoader()
            loader.environment = "development"  # 강제 설정
            config = loader.load_config(validate=False)

            assert config.get("reranking", {}).get("min_score") == 0.0, (
                f"개발환경에서 reranking.min_score는 0.0이어야 함, "
                f"실제값: {config.get('reranking', {}).get('min_score')}"
            )

    def test_test_reranking_min_score(self):
        """테스트 환경에서 reranking.min_score가 0.0인지 확인"""
        with patch.dict(os.environ, {"ENVIRONMENT": "test"}, clear=False):
            from app.lib.config_loader import ConfigLoader

            loader = ConfigLoader()
            loader.environment = "test"  # 강제 설정
            config = loader.load_config(validate=False)

            assert config.get("reranking", {}).get("min_score") == 0.0, (
                f"테스트환경에서 reranking.min_score는 0.0이어야 함, "
                f"실제값: {config.get('reranking', {}).get('min_score')}"
            )

    def test_empty_weaviate_api_key_resolves_to_empty_string(self):
        """Weaviate API 키가 없으면 placeholder가 남지 않아야 함"""
        with patch.dict(
            os.environ,
            {"ENVIRONMENT": "test", "WEAVIATE_API_KEY": ""},
            clear=False,
        ):
            from app.lib.config_loader import ConfigLoader

            loader = ConfigLoader()
            loader.environment = "test"
            config = loader.load_config(validate=False)

            assert config.get("weaviate", {}).get("api_key") == ""

    def test_missing_weaviate_api_key_resolves_to_empty_string(self):
        """Weaviate API 키 환경변수가 없어도 기본값은 빈 문자열이어야 함"""
        with patch.dict(os.environ, {"ENVIRONMENT": "test"}, clear=False):
            os.environ.pop("WEAVIATE_API_KEY", None)

            from app.lib.config_loader import ConfigLoader

            loader = ConfigLoader()
            loader.environment = "test"
            config = loader.load_config(validate=False)

            assert config.get("weaviate", {}).get("api_key") == ""


class TestProductionScoringConfig:
    """프로덕션 환경 스코어링 설정 테스트"""

    def test_production_collection_weight_enabled(self):
        """프로덕션에서 scoring.collection_weight_enabled가 true인지 확인"""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=False):
            from app.lib.config_loader import ConfigLoader

            loader = ConfigLoader()
            loader.environment = "production"
            config = loader.load_config(validate=False)

            assert config.get("scoring", {}).get("collection_weight_enabled") is True, (
                "프로덕션에서 collection_weight_enabled는 True여야 함"
            )

    def test_production_file_type_weight_enabled(self):
        """프로덕션에서 scoring.file_type_weight_enabled가 true인지 확인"""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=False):
            from app.lib.config_loader import ConfigLoader

            loader = ConfigLoader()
            loader.environment = "production"
            config = loader.load_config(validate=False)

            assert config.get("scoring", {}).get("file_type_weight_enabled") is True, (
                "프로덕션에서 file_type_weight_enabled는 True여야 함"
            )


class TestDevelopmentScoringConfig:
    """개발 환경 스코어링 설정 테스트"""

    def test_development_collection_weight_disabled(self):
        """개발환경에서 scoring.collection_weight_enabled가 false인지 확인"""
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=False):
            from app.lib.config_loader import ConfigLoader

            loader = ConfigLoader()
            loader.environment = "development"
            config = loader.load_config(validate=False)

            assert config.get("scoring", {}).get("collection_weight_enabled") is False, (
                "개발환경에서 collection_weight_enabled는 False여야 함"
            )

    def test_development_file_type_weight_disabled(self):
        """개발환경에서 scoring.file_type_weight_enabled가 false인지 확인"""
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=False):
            from app.lib.config_loader import ConfigLoader

            loader = ConfigLoader()
            loader.environment = "development"
            config = loader.load_config(validate=False)

            assert config.get("scoring", {}).get("file_type_weight_enabled") is False, (
                "개발환경에서 file_type_weight_enabled는 False여야 함"
            )
