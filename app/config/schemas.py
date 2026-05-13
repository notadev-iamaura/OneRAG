"""
Configuration Schemas - Pydantic 기반 설정 검증
YAML 설정을 타입 안전하게 검증하고 IDE 자동완성 지원
"""

import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)

# ========================================
# App & Server Configuration
# ========================================


class AppConfig(BaseModel):
    """애플리케이션 기본 설정"""

    name: str = Field(..., min_length=1)
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    environment: Literal["development", "production", "test"] = "development"
    debug: bool = False


class ServerConfig(BaseModel):
    """서버 설정"""

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=1, ge=1)
    reload: bool = False


# ========================================
# LLM Configuration
# ========================================


class LLMProviderConfig(BaseModel):
    """개별 LLM 제공자 설정"""

    model: str = Field(..., min_length=1)
    api_key: str | None = Field(default=None)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1)
    timeout: int = Field(default=30, ge=1)
    max_retries: int = Field(default=3, ge=0)


class LLMConfig(BaseModel):
    """LLM 통합 설정"""

    default_provider: Literal["google", "openai", "anthropic", "openrouter", "ollama"] = "google"
    auto_fallback: bool = True  # 필드명 수정
    fallback_order: list[str] | None = None
    google: LLMProviderConfig
    openai: LLMProviderConfig
    anthropic: LLMProviderConfig

    # providers 리스트는 무시 (하위 호환성)
    model_config = {"extra": "allow"}


# ========================================
# Retrieval Configuration
# ========================================


class EmbeddingsConfig(BaseModel):
    """임베딩 설정"""

    model_config = ConfigDict(extra="allow")  # output_dimensionality, batch_size 등 추가 필드 허용

    provider: Literal["google", "openai", "openrouter", "local"] = "google"
    model: str = Field(default="text-embedding-004")
    api_key: str | None = None
    dimension: int = Field(default=768, ge=1)
    output_dimensionality: int | None = Field(default=None, ge=1)  # 선택적 필드
    batch_size: int | None = Field(default=None, ge=1)  # 선택적 필드
    task_type: str | None = None  # Google Gemini용


class RetrievalConfig(BaseModel):
    """검색 설정"""

    max_sources: int = Field(default=15, ge=1)
    min_score: float = Field(default=0.05, ge=0.0, le=1.0)
    hybrid_alpha: float = Field(default=0.6, ge=0.0, le=1.0)
    top_k: int = Field(default=15, ge=1)


# ========================================
# Reranking Configuration
# ========================================


class RerankingConfig(BaseModel):
    """리랭킹 설정"""

    model_config = ConfigDict(extra="allow")  # providers 등 추가 필드 허용

    enabled: bool = True
    default_provider: Literal["jina", "cohere", "llm", "gemini_flash", "openrouter_gemini"] = (
        "gemini_flash"
    )
    api_key: str | None = None
    top_n: int = Field(default=15, ge=1)
    min_score: float = Field(default=0.05, ge=0.0, le=1.0)


# ========================================
# Query Routing Configuration
# ========================================


class LLMRouterConfig(BaseModel):
    """LLM 라우터 설정"""

    enabled: bool = True  # 🆕 LLM 라우터 활성화 플래그
    provider: Literal["google", "openrouter"] = "google"
    model: str = Field(default="gemini-2.0-flash-lite")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)


class QueryRoutingConfig(BaseModel):
    """쿼리 라우팅 설정"""

    enabled: bool = False
    llm_router: LLMRouterConfig
    cache_ttl: int = Field(default=3600, ge=0)


# ========================================
# Phase 2: BM25 고도화 Configuration
# ========================================


class BM25SynonymConfig(BaseModel):
    """동의어 사전 설정"""

    enabled: bool = True
    csv_path: str = Field(default="docs/phase2/챗봇 - 동의어 사전.csv")
    expand_query: bool = True


class BM25StopwordConfig(BaseModel):
    """불용어 필터 설정"""

    enabled: bool = True
    use_defaults: bool = True
    custom: list[str] = Field(default_factory=list)


class BM25UserDictionaryConfig(BaseModel):
    """사용자 사전 설정"""

    enabled: bool = True
    use_defaults: bool = True
    custom: list[str] = Field(default_factory=list)


class BM25Config(BaseModel):
    """BM25 고도화 통합 설정"""

    enabled: bool = True
    synonym: BM25SynonymConfig = Field(default_factory=BM25SynonymConfig)
    stopword: BM25StopwordConfig = Field(default_factory=BM25StopwordConfig)
    user_dictionary: BM25UserDictionaryConfig = Field(default_factory=BM25UserDictionaryConfig)


# ========================================
# Phase 2: Privacy Configuration
# ========================================


class PrivacyMaskingConfig(BaseModel):
    """마스킹 대상 설정"""

    phone: bool = True  # 개인 전화번호 마스킹
    name: bool = True  # 이름 마스킹
    email: bool = False  # 이메일 마스킹 (기본 비활성화)


class PrivacyCharactersConfig(BaseModel):
    """마스킹 문자 설정"""

    phone: str = "*"
    name: str = "*"


class PrivacyExceptionsConfig(BaseModel):
    """예외 처리 설정"""

    phone_prefixes: list[str] = Field(
        default_factory=lambda: [
            "02",
            "031",
            "032",
            "033",
            "041",
            "042",
            "043",
            "044",
            "051",
            "052",
            "053",
            "054",
            "055",
            "061",
            "062",
            "063",
            "064",
        ]
    )


class PrivacyConfig(BaseModel):
    """개인정보 보호 통합 설정"""

    enabled: bool = True
    masking: PrivacyMaskingConfig = Field(default_factory=PrivacyMaskingConfig)
    characters: PrivacyCharactersConfig = Field(default_factory=PrivacyCharactersConfig)
    exceptions: PrivacyExceptionsConfig = Field(default_factory=PrivacyExceptionsConfig)


# ========================================
# Self-RAG Configuration
# ========================================


class SelfRAGEvaluationConfig(BaseModel):
    """Self-RAG 평가 모듈 설정"""

    provider: Literal["google", "openai", "anthropic", "openrouter"] = "google"
    model: str = Field(default="gemini-2.0-flash-lite")
    api_key: str | None = None
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=500, ge=1)
    timeout: int = Field(default=10, ge=1)
    max_retries: int = Field(default=3, ge=0)
    retry_delay: float = Field(default=0.5, ge=0.0)
    retry_exponential_base: int = Field(default=2, ge=1)
    enable_caching: bool = False


class SelfRAGReRetrievalConfig(BaseModel):
    """Self-RAG 재검색 설정"""

    strategy: Literal["issue_based", "query_expansion", "hybrid"] = "issue_based"
    max_additional_docs: int = Field(default=5, ge=1)
    min_relevance_score: float = Field(default=0.05, ge=0.0, le=1.0)
    merge_strategy: Literal["append", "replace"] = "append"


class SelfRAGMonitoringConfig(BaseModel):
    """Self-RAG 모니터링 설정"""

    enable_metrics: bool = True
    log_evaluations: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    tracked_metrics: list[str] = Field(
        default_factory=lambda: [
            "complexity_distribution",
            "quality_scores",
            "regeneration_rate",
            "improvement_delta",
            "evaluation_time",
            "total_processing_time",
            "cost_per_query",
        ]
    )


class SelfRAGCostControlConfig(BaseModel):
    """Self-RAG 비용 제어 설정"""

    enable_budget_limit: bool = False
    daily_budget_usd: float = Field(default=10.0, ge=0.0)
    auto_disable_on_budget_exceeded: bool = False
    alert_threshold: float = Field(default=0.8, ge=0.0, le=1.0)


class SelfRAGDevelopmentConfig(BaseModel):
    """Self-RAG 개발 설정"""

    enable_debug_mode: bool = False
    log_prompts: bool = False
    save_evaluation_history: bool = True
    max_history_entries: int = Field(default=1000, ge=1)


class SelfRAGConfig(BaseModel):
    """Self-RAG 통합 설정"""

    enabled: bool = False
    complexity_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    quality_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    max_iterations: int = Field(default=1, ge=1, le=3)
    enable_rollback: bool = True
    rollback_threshold: float = Field(default=-0.1, ge=-1.0, le=0.0)
    response_mode: Literal["batch", "streaming"] = "batch"

    # Self-RAG Orchestrator 파라미터 (DI Container 호환)
    initial_top_k: int = Field(
        default=5, ge=1, le=50, description="초기 검색 시 반환할 문서 수 (Self-RAG 적용 전)"
    )
    retry_top_k: int = Field(
        default=15, ge=1, le=100, description="재검색 시 반환할 문서 수 (품질이 낮을 때)"
    )
    max_retries: int = Field(default=1, ge=0, le=3, description="최대 재생성 횟수 (0=재생성 없음)")

    evaluation: SelfRAGEvaluationConfig
    re_retrieval: SelfRAGReRetrievalConfig
    monitoring: SelfRAGMonitoringConfig
    cost_control: SelfRAGCostControlConfig
    development: SelfRAGDevelopmentConfig


# ========================================
# Root Configuration
# ========================================


class RootConfig(BaseModel):
    """루트 설정 - 전체 시스템 설정"""

    app: AppConfig
    server: ServerConfig
    llm: LLMConfig
    embeddings: EmbeddingsConfig
    retrieval: RetrievalConfig
    reranking: RerankingConfig
    query_routing: QueryRoutingConfig
    self_rag: SelfRAGConfig

    # Phase 2: BM25 고도화 및 개인정보 보호
    bm25: BM25Config = Field(default_factory=BM25Config)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)

    # 추가 설정은 느슨하게 허용
    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def validate_api_keys(self):
        """활성화된 기능의 API 키 검증"""
        errors = []

        # LLM 제공자 API 키 검증
        for provider_name in ["google", "openai", "anthropic"]:
            provider_config = getattr(self.llm, provider_name, None)
            if provider_config and not provider_config.api_key:
                errors.append(f"LLM {provider_name} API 키 누락")

        # 임베딩 API 키 검증
        if not self.embeddings.api_key:
            errors.append("임베딩 API 키 누락")

        # 리랭킹 API 키 검증 (활성화 시)
        if self.reranking.enabled and not self.reranking.api_key:
            if self.reranking.default_provider in ["jina", "cohere"]:
                errors.append(f"리랭킹 {self.reranking.default_provider} API 키 누락")

        # Self-RAG API 키 검증 (활성화 시)
        if self.self_rag.enabled and not self.self_rag.evaluation.api_key:
            errors.append("Self-RAG 평가 모듈 API 키 누락")

        if errors:
            logger.warning(f"API 키 경고: {', '.join(errors)}")
            # 경고만 출력, 에러는 발생시키지 않음 (환경변수로 제공 가능)

        return self

    @model_validator(mode="after")
    def validate_self_rag_consistency(self):
        """Self-RAG 설정 일관성 검증"""
        if self.self_rag.enabled:
            # 품질 임계값이 복잡도 임계값보다 높아야 함
            if self.self_rag.quality_threshold <= self.self_rag.complexity_threshold:
                raise ValueError(
                    f"quality_threshold({self.self_rag.quality_threshold})는 "
                    f"complexity_threshold({self.self_rag.complexity_threshold})보다 높아야 함"
                )

            # 예산 제어 활성화 시 예산 값 검증
            if self.self_rag.cost_control.enable_budget_limit:
                if self.self_rag.cost_control.daily_budget_usd <= 0:
                    raise ValueError("daily_budget_usd는 0보다 커야 함")

        return self


# ========================================
# Helper Functions
# ========================================


def validate_config_dict(config_dict: dict[str, Any]) -> RootConfig:
    """
    딕셔너리를 Pydantic 모델로 검증

    Args:
        config_dict: YAML에서 로드한 설정 딕셔너리

    Returns:
        검증된 RootConfig 객체

    Raises:
        ValidationError: 설정 검증 실패 시
    """
    return RootConfig.model_validate(config_dict)


def detect_duplicate_keys_in_yaml(yaml_path: str) -> list[str]:
    """
    YAML 파일에서 중복된 최상위 키 탐지

    Args:
        yaml_path: YAML 파일 경로

    Returns:
        중복된 키 목록
    """
    with open(yaml_path, encoding="utf-8") as f:
        lines = f.readlines()

    # 최상위 키만 추출 (들여쓰기 없는 키)
    top_level_pattern = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*):\s*")
    keys_seen: dict[str, int] = {}
    duplicates = []

    for i, line in enumerate(lines, start=1):
        match = top_level_pattern.match(line)
        if match:
            key = match.group(1)
            if key in keys_seen:
                duplicates.append(f"{key} (첫 번째: {keys_seen[key]}줄, 중복: {i}줄)")
            else:
                keys_seen[key] = i

    return duplicates
