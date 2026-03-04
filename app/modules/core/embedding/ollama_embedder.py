"""
Ollama 로컬 Embedding 구현체

Ollama의 OpenAI 호환 API를 사용하여 로컬 임베딩을 생성합니다.
API 키 없이 동작하며, Ollama 서버가 로컬에서 실행 중이어야 합니다.

기본 모델: nomic-embed-text (768차원)
대체 모델: mxbai-embed-large (1024차원), all-minilm (384차원)

사용법:
    ollama pull nomic-embed-text
    embedder = OllamaEmbedder()
"""

from ....lib.logger import get_logger
from .openai_embedder import OpenRouterEmbedder

logger = get_logger(__name__)

# Ollama 기본 설정
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_DEFAULT_MODEL = "nomic-embed-text"
OLLAMA_DEFAULT_DIM = 768


class OllamaEmbedder(OpenRouterEmbedder):
    """
    Ollama 로컬 Embedding 모델 래퍼

    OpenRouterEmbedder를 상속하여 OpenAI 호환 API를 재사용합니다.
    Ollama 서버(http://localhost:11434)에 직접 연결하여
    API 키 없이 로컬 임베딩을 생성합니다.

    지원 모델:
    - nomic-embed-text (768차원, 기본)
    - mxbai-embed-large (1024차원)
    - all-minilm (384차원)
    - snowflake-arctic-embed (1024차원)
    """

    def __init__(
        self,
        base_url: str | None = None,
        model_name: str = OLLAMA_DEFAULT_MODEL,
        output_dimensionality: int = OLLAMA_DEFAULT_DIM,
        batch_size: int = 32,
    ):
        """
        Ollama Embedder 초기화

        Args:
            base_url: Ollama API URL (기본: http://localhost:11434/v1)
            model_name: Ollama 임베딩 모델 이름 (기본: nomic-embed-text)
            output_dimensionality: 출력 차원 (기본: 768)
            batch_size: 배치 크기 (로컬 모델은 작게 설정)
        """
        resolved_base_url = base_url or OLLAMA_BASE_URL

        # OpenRouterEmbedder 초기화 (api_key="not-needed"로 클라이언트 생성 우회)
        super().__init__(
            api_key="not-needed",
            model_name=model_name,
            output_dimensionality=output_dimensionality,
            batch_size=batch_size,
            base_url=resolved_base_url,
        )

        logger.info(
            f"✅ Initialized OllamaEmbedder: "
            f"model={model_name}, dim={output_dimensionality}, "
            f"url={resolved_base_url}"
        )
