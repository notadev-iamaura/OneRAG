"""
Embedding Module - 임베딩 생성 모듈

다양한 임베딩 제공자(Gemini, OpenAI, OpenRouter 등)를 위한
통일된 인터페이스 제공

사용 예시 1 - 직접 임베더 사용:
    from app.modules.core.embedding import GeminiEmbedder

    embedder = GeminiEmbedder(
        google_api_key="your_api_key",
        output_dimensionality=1536
    )

    # 문서 임베딩
    doc_embeddings = embedder.embed_documents(["text1", "text2"])

    # 쿼리 임베딩
    query_embedding = embedder.embed_query("query text")

사용 예시 2 - Factory를 통한 설정 기반 생성 (권장):
    from app.modules.core.embedding import EmbedderFactory

    config = {
        "embeddings": {
            "provider": "openrouter",
            "openrouter": {
                "model": "qwen/qwen3-embedding-8b",
                "output_dimensionality": 3072
            }
        }
    }

    embedder = EmbedderFactory.create(config)
"""

# 인터페이스, 팩토리, 구현체 import
from .factory import SUPPORTED_MODELS, EmbedderFactory
from .gemini_embedder import GeminiEmbedder
from .interfaces import BaseEmbedder, IEmbedder
from .local_embedder import DEFAULT_LOCAL_MODEL, SUPPORTED_LOCAL_MODELS, LocalEmbedder
from .openai_embedder import OpenAIEmbedder, OpenRouterEmbedder

# 하위 호환성을 위한 별칭 (기존 코드가 GeminiEmbeddings를 사용하는 경우)
GeminiEmbeddings = GeminiEmbedder

__all__ = [
    # 인터페이스
    "IEmbedder",
    "BaseEmbedder",
    # 팩토리
    "EmbedderFactory",
    "SUPPORTED_MODELS",
    # 구현체
    "GeminiEmbedder",
    "OpenAIEmbedder",
    "OpenRouterEmbedder",
    "LocalEmbedder",
    # 로컬 임베더 상수
    "SUPPORTED_LOCAL_MODELS",
    "DEFAULT_LOCAL_MODEL",
    # 하위 호환성 별칭
    "GeminiEmbeddings",
]
