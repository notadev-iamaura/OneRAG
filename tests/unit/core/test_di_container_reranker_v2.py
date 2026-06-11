"""
DI 컨테이너 RerankerFactoryV2 통합 테스트
"""

from unittest.mock import patch

import pytest


class TestDIContainerRerankerV2:
    """DI 컨테이너 Reranker v2 통합 테스트"""

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"JINA_API_KEY": "test-key"})
    async def test_create_reranker_with_new_config_structure(self):
        """새로운 설정 구조로 리랭커 생성"""
        from app.core.di_container import create_reranker_instance_v2

        config = {
            "reranking": {
                "approach": "late-interaction",
                "provider": "jina",
                "jina": {
                    "model": "jina-colbert-v2",
                },
            }
        }
        reranker = await create_reranker_instance_v2(config)
        assert reranker is not None
        assert reranker.__class__.__name__ == "JinaColBERTReranker"

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"})
    async def test_create_llm_reranker_via_di(self):
        """DI를 통한 LLM 리랭커 생성"""
        from app.core.di_container import create_reranker_instance_v2

        config = {
            "reranking": {
                "approach": "llm",
                "provider": "google",
            }
        }
        reranker = await create_reranker_instance_v2(config)
        assert reranker is not None
        assert reranker.__class__.__name__ == "GeminiFlashReranker"

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"JINA_API_KEY": "test-key"})
    async def test_create_cross_encoder_reranker_via_di(self):
        """DI를 통한 Cross-encoder 리랭커 생성"""
        from app.core.di_container import create_reranker_instance_v2

        config = {
            "reranking": {
                "approach": "cross-encoder",
                "provider": "jina",
            }
        }
        reranker = await create_reranker_instance_v2(config)
        assert reranker is not None
        assert reranker.__class__.__name__ == "JinaReranker"

    @pytest.mark.asyncio
    async def test_create_reranker_without_api_key_returns_none(self):
        """API 키 없으면 None 반환 (graceful degradation)"""
        import os

        from app.core.di_container import create_reranker_instance_v2

        # 환경변수 전부 제거 후 테스트
        original_keys = {
            k: os.environ.pop(k, None)
            for k in ["GOOGLE_API_KEY", "OPENAI_API_KEY", "JINA_API_KEY"]
            if k in os.environ
        }

        try:
            config = {
                "reranking": {
                    "approach": "llm",
                    "provider": "google",
                }
            }
            reranker = await create_reranker_instance_v2(config)
            assert reranker is None
        finally:
            # 원래 환경변수 복원
            for k, v in original_keys.items():
                if v is not None:
                    os.environ[k] = v

    @pytest.mark.asyncio
    async def test_create_reranker_with_disabled_returns_none(self):
        """enabled: false 설정 시 None 반환"""
        from app.core.di_container import create_reranker_instance_v2

        config = {
            "reranking": {
                "enabled": False,
                "approach": "llm",
                "provider": "google",
            }
        }
        reranker = await create_reranker_instance_v2(config)
        assert reranker is None

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"GOOGLE_API_KEY": "dummy-key-for-construction"})
    async def test_shipped_config_creates_reranker_with_google_key_only(self):
        """회귀 테스트: 출하 기본 설정이 GOOGLE_API_KEY만으로 리랭커를 생성해야 한다.

        과거 출하 기본값(late-interaction/jina)은 GOOGLE_API_KEY만 설정한
        quickstart 배포에서 JINA_API_KEY 부재로 리랭커가 조용히 비활성화되는
        결함이 있었다. 출하 기본값은 GOOGLE_API_KEY만으로 동작해야 한다.
        """
        import os

        from app.core.di_container import create_reranker_instance_v2
        from app.lib.config_loader import load_config

        # quickstart 환경 재현: JINA_API_KEY 부재 (patch.dict가 종료 시 복원)
        os.environ.pop("JINA_API_KEY", None)

        config = load_config()
        reranking = config.get("reranking", {})

        # 출하 기본값이 GOOGLE_API_KEY만으로 동작하는 조합인지 확인
        assert reranking.get("approach") == "llm"
        assert reranking.get("provider") == "google"

        # 리랭커가 실제로 생성되어야 함 (조용한 비활성화 회귀 방지)
        reranker = await create_reranker_instance_v2(config)
        assert reranker is not None
        assert reranker.__class__.__name__ == "GeminiFlashReranker"
