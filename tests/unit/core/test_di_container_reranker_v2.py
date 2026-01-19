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
