"""
Retrieval (검색) 설정 스키마

MongoDB 하이브리드 검색, 문서 처리, Vector DB 설정 등을 정의합니다.
"""

from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from .base import BaseConfig


class VectorDBConfig(BaseConfig):
    """
    벡터 DB 설정

    Multi Vector DB 지원을 위한 설정 스키마입니다.
    지원 DB: weaviate, pinecone, chroma, qdrant, pgvector, mongodb

    Attributes:
        provider: 사용할 벡터 DB 프로바이더 (기본값: weaviate)

    Examples:
        >>> config = VectorDBConfig(provider="pinecone", api_key="xxx")
        >>> config.provider
        'pinecone'
    """

    # 지원하는 벡터 DB 프로바이더
    provider: Literal["weaviate", "pinecone", "chroma", "qdrant", "pgvector", "mongodb"] = Field(
        default="weaviate",
        description="벡터 DB 프로바이더 (weaviate, pinecone, chroma, qdrant, pgvector, mongodb)",
    )

    # DB별 추가 설정 허용 (api_key, url, index_name 등)
    model_config = ConfigDict(extra="allow")


class RetrievalConfig(BaseConfig):
    """
    검색 시스템 설정

    MongoDB Atlas 하이브리드 검색 (Dense Vector + Sparse BM25) 파라미터를 정의합니다.
    """

    # 필수 필드
    max_sources: int = Field(
        default=15,
        ge=1,
        le=100,
        description="검색할 최대 문서 수 (1-100)",
    )

    min_score: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="최소 관련성 점수 (0.0-1.0)",
    )

    top_k: int = Field(
        default=15,
        ge=1,
        le=50,
        description="반환할 최대 검색 결과 수 (1-50)",
    )

    # 하이브리드 검색 가중치
    hybrid_alpha: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Dense Vector 가중치 (0.0=BM25만, 1.0=Vector만)",
    )

    @field_validator("hybrid_alpha")
    @classmethod
    def validate_hybrid_alpha(cls, v: float) -> float:
        """
        하이브리드 검색 가중치 검증

        Dense Vector 가중치가 0.6이면, Sparse BM25 가중치는 0.4입니다.
        """
        if not 0.0 <= v <= 1.0:
            raise ValueError("hybrid_alpha must be between 0.0 and 1.0")
        return v


class DocumentProcessingConfig(BaseConfig):
    """
    문서 처리 설정

    청킹(Chunking), 임베딩, 파일 타입 지원 등을 정의합니다.
    """

    chunk_size: int = Field(
        default=1250,
        ge=500,
        le=3000,
        description="청크 크기 (문자 수, 500-3000)",
    )

    chunk_overlap: int = Field(
        default=100,
        ge=0,
        le=500,
        description="청크 오버랩 (문자 수, 0-500)",
    )

    splitter_type: str = Field(
        default="recursive",
        pattern="^(recursive|semantic|markdown)$",
        description="청킹 방식 (recursive, semantic, markdown)",
    )

    file_types: list[str] = Field(
        default=["pdf", "txt", "docx", "pptx", "xlsx", "csv", "html", "md", "json"],
        description="지원하는 파일 확장자 목록",
    )

    # Semantic 청킹 전용
    semantic_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Semantic 청킹 임계값 (0.0-1.0)",
    )

    target_chunk_size: int = Field(
        default=1250,
        ge=500,
        le=3000,
        description="목표 청크 크기 (Semantic)",
    )

    min_chunk_size: int = Field(
        default=1000,
        ge=100,
        le=2000,
        description="최소 청크 크기 (Semantic)",
    )

    max_chunk_size: int = Field(
        default=1500,
        ge=1000,
        le=5000,
        description="최대 청크 크기 (Semantic)",
    )

    @field_validator("chunk_overlap")
    @classmethod
    def validate_overlap(cls, v: int, info) -> int:
        """
        청크 오버랩이 청크 크기보다 작은지 검증
        """
        # info.data는 이미 검증된 필드만 포함 (Pydantic v2)
        chunk_size = info.data.get("chunk_size", 1250)
        if v >= chunk_size:
            raise ValueError(f"chunk_overlap ({v}) must be less than chunk_size ({chunk_size})")
        return v


class ContextExpansionConfig(BaseConfig):
    """
    인접 청크 컨텍스트 확장 설정

    검색 결과 주변 청크를 생성 컨텍스트에 추가합니다. 기본값은 비활성화입니다.
    """

    enabled: bool = Field(
        default=False,
        description="인접 청크 컨텍스트 확장 활성화 여부",
    )

    window: int = Field(
        default=1,
        ge=0,
        le=3,
        description="검색 hit 앞뒤로 포함할 청크 수 (0-3)",
    )

    max_window: int = Field(
        default=3,
        ge=1,
        le=3,
        description="요청 옵션으로 허용할 최대 청크 창 크기 (1-3)",
    )


class RAGConfig(BaseConfig):
    """
    RAG 파이프라인 설정

    RAG 워크플로우의 전반적인 동작을 정의합니다.
    """

    enabled: bool = Field(
        default=True,
        description="RAG 파이프라인 활성화 여부",
    )

    use_rerank: bool = Field(
        default=True,
        description="리랭킹 사용 여부",
    )

    reranker_model: str = Field(
        default="jina",
        pattern="^(jina|gemini_flash|cohere|llm)$",
        description="리랭커 모델 (jina, gemini_flash, cohere, llm)",
    )

    top_k: int = Field(
        default=15,
        ge=1,
        le=50,
        description="검색할 문서 수 (1-50)",
    )

    rerank_top_k: int = Field(
        default=15,
        ge=1,
        le=30,
        description="리랭킹 후 반환할 문서 수 (1-30)",
    )

    relevance_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="관련성 임계값 (0.0-1.0)",
    )

    context_expansion: ContextExpansionConfig = Field(
        default_factory=ContextExpansionConfig,
        description="인접 청크 컨텍스트 확장 설정",
    )

    @field_validator("rerank_top_k")
    @classmethod
    def validate_rerank_top_k(cls, v: int, info) -> int:
        """
        리랭킹 후 문서 수가 검색 문서 수보다 작거나 같은지 검증
        """
        top_k = info.data.get("top_k", 15)
        if v > top_k:
            raise ValueError(f"rerank_top_k ({v}) cannot be greater than top_k ({top_k})")
        return v
