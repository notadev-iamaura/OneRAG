"""
EmbedderFactory 로컬 provider 테스트

local provider가 올바르게 LocalEmbedder를 생성하는지 검증합니다.
"""

from unittest.mock import patch


class TestEmbedderFactoryLocalProvider:
    """EmbedderFactory local provider 테스트"""

    def test_create_local_embedder(self):
        """local provider로 LocalEmbedder 생성"""
        from app.modules.core.embedding.factory import EmbedderFactory
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        config = {
            "embeddings": {
                "provider": "local",
                "local": {
                    "model": "Qwen/Qwen3-Embedding-0.6B",
                    "output_dimensionality": 1024,
                    "batch_size": 32,
                }
            }
        }

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = EmbedderFactory.create(config)
            assert isinstance(embedder, LocalEmbedder)

    def test_local_embedder_default_config(self):
        """local provider 기본 설정으로 생성"""
        from app.modules.core.embedding.factory import EmbedderFactory
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        config = {
            "embeddings": {
                "provider": "local"
            }
        }

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = EmbedderFactory.create(config)
            assert isinstance(embedder, LocalEmbedder)
            assert embedder.model_name == "Qwen/Qwen3-Embedding-0.6B"

    def test_local_embedder_custom_model(self):
        """커스텀 모델로 LocalEmbedder 생성"""
        from app.modules.core.embedding.factory import EmbedderFactory
        from app.modules.core.embedding.local_embedder import LocalEmbedder

        config = {
            "embeddings": {
                "provider": "local",
                "local": {
                    "model": "intfloat/multilingual-e5-small",
                    "output_dimensionality": 384,
                }
            }
        }

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            embedder = EmbedderFactory.create(config)
            assert isinstance(embedder, LocalEmbedder)
            assert embedder.output_dimensionality == 384

    def test_local_provider_in_supported_list(self):
        """local이 지원 provider 목록에 포함되는지 확인"""
        from app.modules.core.embedding.factory import EmbedderFactory

        # ValueError가 발생하지 않아야 함
        config = {
            "embeddings": {
                "provider": "local"
            }
        }

        with patch('app.modules.core.embedding.local_embedder.SentenceTransformer'):
            # 정상적으로 생성되어야 함
            embedder = EmbedderFactory.create(config)
            assert embedder is not None
