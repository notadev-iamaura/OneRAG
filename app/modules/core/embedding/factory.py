"""
Embedder Factory - 임베더 팩토리 모듈

설정 기반으로 적절한 임베더 인스턴스를 생성하는 팩토리 클래스.
Strategy 패턴과 Factory 패턴을 결합하여 다양한 임베딩 제공자를 지원.

지원 제공자:
- google: Google Gemini Embedding (직접 API)
- openai: OpenAI Embedding (직접 API)
- openrouter: OpenRouter 통합 게이트웨이 (다양한 모델 지원)

OpenRouter 지원 모델:
- google/gemini-embedding-001 (3072차원, 한국어 최적화)
- openai/text-embedding-3-large (3072차원)
- openai/text-embedding-3-small (1536차원)
- qwen/qwen3-embedding-8b (동적 차원)
- intfloat/e5-large-v2 (1024차원)

사용 예시:
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

import os
from typing import Any

from ....lib.logger import get_logger
from .gemini_embedder import GeminiEmbedder
from .interfaces import IEmbedder
from .local_embedder import DEFAULT_LOCAL_MODEL, LocalEmbedder
from .openai_embedder import OpenAIEmbedder, OpenRouterEmbedder
from .vertex_embedder import (
    DEFAULT_VERTEX_EMBEDDING_DIMENSIONS,
    DEFAULT_VERTEX_EMBEDDING_LOCATION,
    DEFAULT_VERTEX_EMBEDDING_MODEL,
    VertexAIEmbedder,
)

logger = get_logger(__name__)


# 지원 모델 정의 (모델명 → 기본 차원)
SUPPORTED_MODELS: dict[str, dict[str, Any]] = {
    # OpenRouter 지원 모델
    "google/gemini-embedding-001": {
        "provider": "openrouter",
        "default_dimensions": 3072,
        "supports_dimensions_param": False,
        "description": "Google Gemini Embedding - 한국어 최적화, MTEB 1위",
    },
    "openai/text-embedding-3-large": {
        "provider": "openrouter",
        "default_dimensions": 3072,
        "supports_dimensions_param": True,
        "description": "OpenAI 최신 대형 임베딩 모델",
    },
    "openai/text-embedding-3-small": {
        "provider": "openrouter",
        "default_dimensions": 1536,
        "supports_dimensions_param": True,
        "description": "OpenAI 경량 임베딩 모델",
    },
    "qwen/qwen3-embedding-8b": {
        "provider": "openrouter",
        "default_dimensions": 3072,
        "supports_dimensions_param": False,
        "description": "Qwen3 8B 임베딩 - 다국어 지원",
    },
    "intfloat/e5-large-v2": {
        "provider": "openrouter",
        "default_dimensions": 1024,
        "supports_dimensions_param": False,
        "description": "E5 Large V2 - 범용 임베딩",
    },
    # Google 직접 API 모델
    "models/gemini-embedding-001": {
        "provider": "google",
        "default_dimensions": 3072,
        "supports_dimensions_param": True,
        "description": "Google Gemini Embedding (직접 API)",
    },
    "gemini-embedding-001": {
        "provider": "google",
        "default_dimensions": 3072,
        "supports_dimensions_param": True,
        "description": "Google Gemini Embedding (직접 API, legacy alias)",
    },
    # Vertex AI (ADC/GCP 운영용) 모델
    "vertex/gemini-embedding-001": {
        "provider": "vertex",
        "default_dimensions": 3072,
        "supports_dimensions_param": True,
        "description": "Vertex AI Gemini Embedding (ADC 인증, GCP 운영용)",
    },
    "models/embedding-001": {
        "provider": "google",
        "default_dimensions": 768,
        "supports_dimensions_param": False,
        "description": "Google 기본 임베딩 모델",
    },
    # OpenAI 직접 API 모델
    "text-embedding-3-large": {
        "provider": "openai",
        "default_dimensions": 3072,
        "supports_dimensions_param": True,
        "description": "OpenAI 최신 대형 임베딩 (직접 API)",
    },
    "text-embedding-3-small": {
        "provider": "openai",
        "default_dimensions": 1536,
        "supports_dimensions_param": True,
        "description": "OpenAI 경량 임베딩 (직접 API)",
    },
    "text-embedding-ada-002": {
        "provider": "openai",
        "default_dimensions": 1536,
        "supports_dimensions_param": False,
        "description": "OpenAI Ada 임베딩 (레거시)",
    },
}


class EmbedderFactory:
    """
    임베더 팩토리 클래스

    설정 딕셔너리를 기반으로 적절한 IEmbedder 구현체를 생성합니다.
    Factory 패턴을 사용하여 임베더 생성 로직을 중앙화하고,
    새로운 제공자 추가 시 확장이 용이하도록 설계.

    주요 기능:
    - 설정 기반 임베더 자동 선택
    - 환경 변수 폴백 지원
    - 모델별 기본값 자동 적용
    - 상세한 초기화 로깅
    """

    @staticmethod
    def create(config: dict[str, Any]) -> IEmbedder:
        """
        설정 기반 임베더 인스턴스 생성

        Args:
            config: 전체 설정 딕셔너리 (embeddings 섹션 포함)
                {
                    "embeddings": {
                        "provider": "openrouter" | "google" | "openai",
                        "openrouter": {...},  # provider가 openrouter일 때
                        "google": {...},       # provider가 google일 때
                        "openai": {...},       # provider가 openai일 때
                    },
                    "llm": {...}  # API 키 폴백용
                }

        Returns:
            IEmbedder: 생성된 임베더 인스턴스

        Raises:
            ValueError: 지원하지 않는 provider인 경우
        """
        embeddings_config = config.get("embeddings", {})
        provider = embeddings_config.get("provider", "google")

        logger.info(f"🏭 EmbedderFactory: provider={provider} 임베더 생성 시작")

        if provider == "google":
            return EmbedderFactory._create_google_embedder(config, embeddings_config)
        elif provider == "vertex":
            return EmbedderFactory._create_vertex_embedder(config, embeddings_config)
        elif provider == "openai":
            return EmbedderFactory._create_openai_embedder(config, embeddings_config)
        elif provider == "openrouter":
            return EmbedderFactory._create_openrouter_embedder(config, embeddings_config)
        elif provider == "local":
            return EmbedderFactory._create_local_embedder(config, embeddings_config)
        else:
            raise ValueError(
                f"지원하지 않는 임베딩 provider: {provider}. "
                f"지원 목록: google, vertex, openai, openrouter, local"
            )

    @staticmethod
    def _create_google_embedder(
        config: dict[str, Any],
        embeddings_config: dict[str, Any]
    ) -> GeminiEmbedder:
        """
        Google Gemini 임베더 생성

        Args:
            config: 전체 설정
            embeddings_config: embeddings 섹션 설정

        Returns:
            GeminiEmbedder 인스턴스
        """
        google_config = embeddings_config.get("google", {})

        # 모델 설정
        model_name = google_config.get(
            "model",
            embeddings_config.get("model", "models/gemini-embedding-001")
        )
        if model_name == "gemini-embedding-001":
            model_name = "models/gemini-embedding-001"

        # 차원 설정 (모델별 기본값 적용)
        model_info = SUPPORTED_MODELS.get(model_name, {})
        default_dim = model_info.get("default_dimensions", 3072)
        output_dim = google_config.get(
            "output_dimensionality",
            embeddings_config.get("output_dimensionality", default_dim)
        )

        # 기타 설정
        task_type = google_config.get(
            "task_type",
            embeddings_config.get("task_type", "RETRIEVAL_DOCUMENT")
        )
        batch_size = google_config.get(
            "batch_size",
            embeddings_config.get("batch_size", 100)
        )

        # API 키 (설정 → LLM 설정 → 환경 변수)
        api_key = google_config.get("api_key")
        if not api_key:
            api_key = config.get("llm", {}).get("google", {}).get("api_key")
        if not api_key:
            api_key = os.getenv("GOOGLE_API_KEY")

        logger.info(
            f"✅ Google 임베더 생성: model={model_name}, "
            f"dim={output_dim}, task={task_type}"
        )

        return GeminiEmbedder(
            google_api_key=api_key,
            model_name=model_name,
            output_dimensionality=output_dim,
            batch_size=batch_size,
            task_type=task_type,
        )

    @staticmethod
    def _as_int(value: Any, default: int) -> int:
        """None/빈 문자열이면 기본값, 그 외에는 int로 캐스팅한다."""
        if value in (None, ""):
            return default
        return int(value)

    @staticmethod
    def _as_float(value: Any, default: float) -> float:
        """None/빈 문자열이면 기본값, 그 외에는 float로 캐스팅한다."""
        if value in (None, ""):
            return default
        return float(value)

    @staticmethod
    def _create_vertex_embedder(
        config: dict[str, Any],
        embeddings_config: dict[str, Any],
    ) -> VertexAIEmbedder:
        """Vertex AI(ADC) 임베더 생성.

        project_id/location은 설정(embeddings.vertex) → generation.vertex →
        Vertex/Google Cloud 표준 환경변수 순으로 해석한다. ADC 인증이므로 API 키는
        사용하지 않으며, google-auth 미설치 시 인증 시점에 안내 에러가 발생한다.

        Args:
            config: 전체 설정 딕셔너리.
            embeddings_config: embeddings 섹션 설정.

        Returns:
            VertexAIEmbedder 인스턴스.
        """
        vertex_config = embeddings_config.get("vertex", {})
        generation_vertex_config = config.get("generation", {}).get("vertex", {})

        model_name = (
            vertex_config.get("model")
            or os.getenv("VERTEX_AI_EMBEDDING_MODEL")
            or DEFAULT_VERTEX_EMBEDDING_MODEL
        )
        output_dim = EmbedderFactory._as_int(
            vertex_config.get("output_dimensionality")
            or os.getenv("VERTEX_AI_EMBEDDING_DIMENSIONS"),
            DEFAULT_VERTEX_EMBEDDING_DIMENSIONS,
        )
        batch_size = EmbedderFactory._as_int(vertex_config.get("batch_size"), 16)
        timeout = EmbedderFactory._as_float(vertex_config.get("timeout"), 60.0)

        # project_id 폴백: OneRAG에는 Document AI가 없으므로 관련 환경변수는 제외한다.
        project_id = (
            vertex_config.get("project_id")
            or generation_vertex_config.get("project_id")
            or os.getenv("VERTEX_AI_PROJECT_ID")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
            or os.getenv("GCLOUD_PROJECT")
        )
        location = (
            os.getenv("VERTEX_AI_EMBEDDING_LOCATION")
            or vertex_config.get("location")
            or generation_vertex_config.get("location")
            or os.getenv("VERTEX_AI_LOCATION")
            or os.getenv("GOOGLE_CLOUD_LOCATION")
            or DEFAULT_VERTEX_EMBEDDING_LOCATION
        )

        logger.info(
            f"✅ Vertex AI 임베더 생성: model={model_name}, "
            f"dim={output_dim}, location={location}"
        )

        return VertexAIEmbedder(
            project_id=project_id,
            location=str(location),
            model_name=str(model_name),
            output_dimensionality=output_dim,
            batch_size=batch_size,
            timeout=timeout,
        )

    @staticmethod
    def _create_openai_embedder(
        config: dict[str, Any],
        embeddings_config: dict[str, Any]
    ) -> OpenAIEmbedder:
        """
        OpenAI 임베더 생성

        Args:
            config: 전체 설정
            embeddings_config: embeddings 섹션 설정

        Returns:
            OpenAIEmbedder 인스턴스
        """
        openai_config = embeddings_config.get("openai", {})

        # 모델 설정
        model_name = openai_config.get(
            "model",
            embeddings_config.get("model", "text-embedding-3-large")
        )

        # 차원 설정
        model_info = SUPPORTED_MODELS.get(model_name, {})
        default_dim = model_info.get("default_dimensions", 3072)
        output_dim = openai_config.get(
            "output_dimensionality",
            embeddings_config.get("output_dimensionality", default_dim)
        )

        # 기타 설정
        batch_size = openai_config.get(
            "batch_size",
            embeddings_config.get("batch_size", 100)
        )

        # API 키
        api_key = openai_config.get("api_key")
        if not api_key:
            api_key = config.get("llm", {}).get("openai", {}).get("api_key")
        if not api_key:
            api_key = os.getenv("OPENAI_API_KEY")

        logger.info(
            f"✅ OpenAI 임베더 생성: model={model_name}, dim={output_dim}"
        )

        return OpenAIEmbedder(
            openai_api_key=api_key,
            model_name=model_name,
            output_dimensionality=output_dim,
            batch_size=batch_size,
        )

    @staticmethod
    def _create_openrouter_embedder(
        config: dict[str, Any],
        embeddings_config: dict[str, Any]
    ) -> OpenRouterEmbedder:
        """
        OpenRouter 임베더 생성

        OpenRouter는 통합 게이트웨이로 다양한 임베딩 모델을 지원합니다:
        - google/gemini-embedding-001: 한국어 최적화
        - openai/text-embedding-3-large: OpenAI 최신 모델
        - qwen/qwen3-embedding-8b: Qwen3 다국어 모델
        - intfloat/e5-large-v2: E5 범용 모델

        Args:
            config: 전체 설정
            embeddings_config: embeddings 섹션 설정

        Returns:
            OpenRouterEmbedder 인스턴스
        """
        openrouter_config = embeddings_config.get("openrouter", {})

        # 모델 설정
        model_name = openrouter_config.get("model", "google/gemini-embedding-001")

        # 차원 설정 (모델별 기본값 적용)
        model_info = SUPPORTED_MODELS.get(model_name, {})
        default_dim = model_info.get("default_dimensions", 3072)
        output_dim = openrouter_config.get("output_dimensionality", default_dim)

        # 기타 설정
        batch_size = openrouter_config.get("batch_size", 100)
        site_url = openrouter_config.get("site_url", "")
        app_name = openrouter_config.get("app_name", "RAG-Chatbot")

        # API 키
        api_key = openrouter_config.get("api_key")
        if not api_key:
            api_key = os.getenv("OPENROUTER_API_KEY")

        # 모델 정보 로깅
        model_desc = model_info.get("description", "알 수 없는 모델")
        supports_dim = model_info.get("supports_dimensions_param", False)

        logger.info(
            f"✅ OpenRouter 임베더 생성: model={model_name}, "
            f"dim={output_dim}, supports_dim_param={supports_dim}"
        )
        logger.debug(f"📝 모델 설명: {model_desc}")

        return OpenRouterEmbedder(
            api_key=api_key,
            model_name=model_name,
            output_dimensionality=output_dim,
            batch_size=batch_size,
            site_url=site_url,
            app_name=app_name,
        )

    @staticmethod
    def _create_local_embedder(
        config: dict[str, Any],
        embeddings_config: dict[str, Any]
    ) -> LocalEmbedder:
        """
        로컬 임베더 생성

        sentence-transformers를 사용하여 로컬에서 임베딩을 생성합니다.
        API 키 없이 동작하며, Quickstart 환경에서 사용됩니다.

        지원 모델:
        - Qwen/Qwen3-Embedding-0.6B (기본): 1024차원, 32K 컨텍스트
        - intfloat/multilingual-e5-small: 384차원, 경량

        Args:
            config: 전체 설정
            embeddings_config: embeddings 섹션 설정

        Returns:
            LocalEmbedder 인스턴스
        """
        local_config = embeddings_config.get("local", {})

        # 모델 설정
        model_name = local_config.get("model", DEFAULT_LOCAL_MODEL)

        # 차원 설정 (None이면 모델 기본값 사용)
        output_dim = local_config.get("output_dimensionality")

        # 기타 설정
        batch_size = local_config.get("batch_size", 32)
        normalize = local_config.get("normalize", True)
        device = local_config.get("device")

        logger.info(
            f"✅ 로컬 임베더 생성: model={model_name}, "
            f"dim={output_dim or 'auto'}, batch_size={batch_size}"
        )

        return LocalEmbedder(
            model_name=model_name,
            output_dimensionality=output_dim,
            batch_size=batch_size,
            normalize=normalize,
            device=device,
        )

    @staticmethod
    def get_supported_models() -> dict[str, dict[str, Any]]:
        """
        지원되는 모든 모델 정보 반환

        Returns:
            모델명 → 모델 정보 딕셔너리
        """
        return SUPPORTED_MODELS.copy()

    @staticmethod
    def get_model_info(model_name: str) -> dict[str, Any] | None:
        """
        특정 모델의 정보 조회

        Args:
            model_name: 모델 이름 (예: "qwen/qwen3-embedding-8b")

        Returns:
            모델 정보 딕셔너리 또는 None (미지원 모델)
        """
        return SUPPORTED_MODELS.get(model_name)

    @staticmethod
    def list_models_by_provider(provider: str) -> list[str]:
        """
        특정 제공자의 모델 목록 반환

        Args:
            provider: "google", "openai", "openrouter"

        Returns:
            해당 제공자의 모델명 리스트
        """
        return [
            model_name
            for model_name, info in SUPPORTED_MODELS.items()
            if info.get("provider") == provider
        ]
