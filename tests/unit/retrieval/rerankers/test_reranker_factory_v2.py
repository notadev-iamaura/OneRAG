"""
RerankerFactory v2 테스트
새로운 approach/provider/model 구조 지원
"""

from unittest.mock import patch

import pytest


class TestRerankerFactoryV2Registry:
    """리랭커 레지스트리 테스트"""

    def test_approach_registry_exists(self):
        """approach별 리랭커 레지스트리 존재 확인"""
        from app.modules.core.retrieval.rerankers.factory import APPROACH_REGISTRY

        assert "llm" in APPROACH_REGISTRY
        assert "cross-encoder" in APPROACH_REGISTRY
        assert "late-interaction" in APPROACH_REGISTRY

    def test_provider_registry_exists(self):
        """provider별 리랭커 레지스트리 존재 확인"""
        from app.modules.core.retrieval.rerankers.factory import PROVIDER_REGISTRY

        assert "google" in PROVIDER_REGISTRY
        assert "openai" in PROVIDER_REGISTRY
        assert "jina" in PROVIDER_REGISTRY


class TestRerankerFactoryV2Create:
    """RerankerFactory v2 생성 테스트"""

    @patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"})
    def test_create_llm_google(self):
        """LLM approach + Google provider 리랭커 생성"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        config = {
            "reranking": {
                "approach": "llm",
                "provider": "google",
                "google": {
                    "model": "gemini-flash-lite-latest",
                    "max_documents": 20,
                },
            }
        }
        reranker = RerankerFactoryV2.create(config)
        assert reranker.__class__.__name__ == "GeminiFlashReranker"

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
    def test_create_llm_openai(self):
        """LLM approach + OpenAI provider 리랭커 생성"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        config = {
            "reranking": {
                "approach": "llm",
                "provider": "openai",
                "openai": {
                    "model": "gpt-5-nano",
                },
            }
        }
        reranker = RerankerFactoryV2.create(config)
        assert reranker.__class__.__name__ == "OpenAILLMReranker"

    @patch.dict("os.environ", {"JINA_API_KEY": "test-key"})
    def test_create_cross_encoder_jina(self):
        """Cross-encoder approach + Jina provider 리랭커 생성"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        config = {
            "reranking": {
                "approach": "cross-encoder",
                "provider": "jina",
                "jina": {
                    "model": "jina-reranker-v2-base-multilingual",
                },
            }
        }
        reranker = RerankerFactoryV2.create(config)
        assert reranker.__class__.__name__ == "JinaReranker"

    @patch.dict("os.environ", {"JINA_API_KEY": "test-key"})
    def test_create_late_interaction_jina(self):
        """Late-interaction approach + Jina provider 리랭커 생성"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        config = {
            "reranking": {
                "approach": "late-interaction",
                "provider": "jina",
                "jina": {
                    "model": "jina-colbert-v2",
                },
            }
        }
        reranker = RerankerFactoryV2.create(config)
        assert reranker.__class__.__name__ == "JinaColBERTReranker"

    @patch.dict("os.environ", {"COHERE_API_KEY": "test-key"})
    def test_create_cross_encoder_cohere(self):
        """Cross-encoder approach + Cohere provider 리랭커 생성"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        config = {
            "reranking": {
                "approach": "cross-encoder",
                "provider": "cohere",
                "cohere": {
                    "model": "rerank-multilingual-v3.0",
                },
            }
        }
        reranker = RerankerFactoryV2.create(config)
        assert reranker.__class__.__name__ == "CohereReranker"

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"})
    def test_create_llm_openrouter(self):
        """LLM approach + OpenRouter provider 리랭커 생성"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        config = {
            "reranking": {
                "approach": "llm",
                "provider": "openrouter",
                "openrouter": {
                    "model": "google/gemini-2.5-flash-lite",
                },
            }
        }
        reranker = RerankerFactoryV2.create(config)
        assert reranker.__class__.__name__ == "OpenRouterReranker"

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"})
    def test_create_llm_openrouter_with_default_config(self):
        """LLM approach + OpenRouter provider 기본 설정으로 리랭커 생성"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        config = {
            "reranking": {
                "approach": "llm",
                "provider": "openrouter",
            }
        }
        reranker = RerankerFactoryV2.create(config)
        assert reranker.__class__.__name__ == "OpenRouterReranker"

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"})
    def test_create_llm_openrouter_custom_model(self):
        """LLM approach + OpenRouter provider 커스텀 모델로 리랭커 생성"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        config = {
            "reranking": {
                "approach": "llm",
                "provider": "openrouter",
                "openrouter": {
                    "model": "anthropic/claude-3-haiku",
                    "max_documents": 30,
                    "timeout": 20,
                },
            }
        }
        reranker = RerankerFactoryV2.create(config)
        assert reranker.__class__.__name__ == "OpenRouterReranker"
        assert reranker.model == "anthropic/claude-3-haiku"
        assert reranker.max_documents == 30
        assert reranker.timeout == 20

    def test_create_local_sentence_transformers(self):
        """Local approach + sentence-transformers provider 리랭커 생성"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        config = {
            "reranking": {
                "approach": "local",
                "provider": "sentence-transformers",
                "sentence-transformers": {
                    "model": "cross-encoder/ms-marco-MiniLM-L-12-v2",
                },
            }
        }
        reranker = RerankerFactoryV2.create(config)
        assert reranker.__class__.__name__ == "LocalReranker"

    def test_create_local_with_default_config(self):
        """Local approach 기본 설정으로 리랭커 생성"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        config = {
            "reranking": {
                "approach": "local",
                "provider": "sentence-transformers",
            }
        }
        reranker = RerankerFactoryV2.create(config)
        assert reranker.__class__.__name__ == "LocalReranker"

    def test_create_with_invalid_approach_raises_error(self):
        """유효하지 않은 approach 시 에러"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        config = {
            "reranking": {
                "approach": "invalid",
                "provider": "jina",
            }
        }
        with pytest.raises(ValueError, match="지원하지 않는 approach"):
            RerankerFactoryV2.create(config)

    def test_create_with_invalid_combination_raises_error(self):
        """유효하지 않은 approach-provider 조합 시 에러"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        config = {
            "reranking": {
                "approach": "llm",
                "provider": "jina",  # LLM approach에서 jina는 불가
            }
        }
        with pytest.raises(ValueError, match="approach.*provider"):
            RerankerFactoryV2.create(config)

    @patch.dict("os.environ", {}, clear=True)
    def test_create_without_api_key_raises_error(self):
        """API 키 없이 생성 시 에러"""
        # 환경변수 전부 제거 후 테스트
        import os

        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2
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
            with pytest.raises(ValueError, match="API|key|환경변수"):
                RerankerFactoryV2.create(config)
        finally:
            # 원래 환경변수 복원
            for k, v in original_keys.items():
                if v is not None:
                    os.environ[k] = v


class TestRerankerFactoryV2Helpers:
    """RerankerFactory v2 헬퍼 메서드 테스트"""

    def test_get_approaches(self):
        """지원하는 approach 목록 조회"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        approaches = RerankerFactoryV2.get_approaches()
        assert "llm" in approaches
        assert "cross-encoder" in approaches
        assert "late-interaction" in approaches
        assert "local" in approaches

    def test_get_providers_for_approach(self):
        """approach별 유효한 provider 목록 조회"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        llm_providers = RerankerFactoryV2.get_providers_for_approach("llm")
        assert "google" in llm_providers
        assert "openai" in llm_providers
        assert "jina" not in llm_providers

        ce_providers = RerankerFactoryV2.get_providers_for_approach("cross-encoder")
        assert "jina" in ce_providers
        assert "google" not in ce_providers

        local_providers = RerankerFactoryV2.get_providers_for_approach("local")
        assert "sentence-transformers" in local_providers

    def test_get_approach_description(self):
        """approach 설명 조회"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        desc = RerankerFactoryV2.get_approach_description("llm")
        assert "LLM" in desc or "언어" in desc

        desc = RerankerFactoryV2.get_approach_description("cross-encoder")
        assert "Cross" in desc or "인코더" in desc

        desc = RerankerFactoryV2.get_approach_description("late-interaction")
        assert "Late" in desc or "토큰" in desc

        desc = RerankerFactoryV2.get_approach_description("local")
        assert "로컬" in desc or "API" in desc

    def test_get_all_providers(self):
        """모든 provider 목록 조회"""
        from app.modules.core.retrieval.rerankers.factory import RerankerFactoryV2

        providers = RerankerFactoryV2.get_all_providers()
        assert "google" in providers
        assert "openai" in providers
        assert "jina" in providers
        assert "cohere" in providers
        assert "openrouter" in providers
        assert "sentence-transformers" in providers
