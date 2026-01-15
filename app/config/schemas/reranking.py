"""
Reranking (리랭킹) 설정 스키마

검색된 문서의 관련성 재평가 및 순위 조정 설정을 정의합니다.
"""

from pydantic import Field, field_validator

from .base import BaseConfig


class RerankingDefaultsConfig(BaseConfig):
    """
    리랭킹 기본값 설정

    모든 LLM 기반 리랭커에 적용되는 공통 기본값입니다.
    """

    max_documents: int = Field(
        default=20,
        ge=1,
        le=100,
        description="리랭킹할 최대 문서 수 (1-100)",
    )

    timeout: int = Field(
        default=15,
        ge=5,
        le=60,
        description="리랭킹 타임아웃 (초, 5-60)",
    )

    verbosity: str = Field(
        default="low",
        pattern="^(low|medium|high)$",
        description="리랭킹 상세도 (low, medium, high)",
    )

    reasoning_effort: str = Field(
        default="minimal",
        pattern="^(minimal|moderate|extensive)$",
        description="추론 노력 수준 (minimal, moderate, extensive)",
    )

    max_completion_tokens: int = Field(
        default=15000,
        ge=1000,
        le=30000,
        description="최대 완성 토큰 수 (1000-30000)",
    )


class RerankingProviderConfig(BaseConfig):
    """
    개별 리랭커 제공자 설정

    각 리랭커의 활성화 여부, 모델, API 키 등을 정의합니다.
    """

    enabled: bool = Field(
        default=False,
        description="리랭커 활성화 여부",
    )

    model: str = Field(
        default="",
        description="리랭커 모델명",
    )

    api_key: str | None = Field(
        default=None,
        description="API 키 (환경 변수 치환 가능)",
    )

    # Provider 특화 필드 (선택적)
    provider: str | None = Field(
        default=None,
        description="LLM 제공자 (llm 리랭커 전용)",
    )

    timeout: int | None = Field(
        default=None,
        ge=5,
        le=120,
        description="개별 타임아웃 (초, 5-120, None이면 defaults 사용)",
    )

    max_documents: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="개별 최대 문서 수 (1-100, None이면 defaults 사용)",
    )

    verbosity: str | None = Field(
        default=None,
        pattern="^(low|medium|high)$",
        description="개별 상세도 (None이면 defaults 사용)",
    )

    reasoning_effort: str | None = Field(
        default=None,
        pattern="^(minimal|moderate|extensive)$",
        description="개별 추론 노력 (None이면 defaults 사용)",
    )


class RerankingConfig(BaseConfig):
    """
    리랭킹 시스템 설정

    리랭킹 활성화, 기본 제공자, 최소 점수, 제공자별 설정을 정의합니다.
    """

    enabled: bool = Field(
        default=True,
        description="리랭킹 시스템 활성화 여부",
    )

    default_provider: str = Field(
        default="gemini_flash",
        pattern="^(gemini_flash|llm|gpt5_nano|jina|cohere|openrouter_gemini)$",
        description="기본 리랭커 제공자 (gemini_flash, llm, gpt5_nano, jina, cohere, openrouter_gemini)",
    )

    min_score: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="리랭킹 후 최소 점수 (0.0-1.0)",
    )

    # 공통 기본값
    defaults: RerankingDefaultsConfig = Field(
        default_factory=RerankingDefaultsConfig,
        description="모든 리랭커에 적용되는 기본값",
    )

    # 제공자별 설정
    providers: dict[str, RerankingProviderConfig] = Field(
        default_factory=dict,
        description="리랭커 제공자별 설정",
    )

    @field_validator("min_score")
    @classmethod
    def validate_min_score(cls, v: float) -> float:
        """
        최소 점수가 0.0-1.0 범위인지 검증
        """
        if not 0.0 <= v <= 1.0:
            raise ValueError("min_score must be between 0.0 and 1.0")
        return v

    @field_validator("providers")
    @classmethod
    def validate_providers(
        cls, v: dict[str, RerankingProviderConfig]
    ) -> dict[str, RerankingProviderConfig]:
        """
        제공자 설정 검증

        - 최소 1개 이상의 제공자가 활성화되어 있어야 함
        - 활성화된 제공자는 model이 필수
        """
        if not v:
            # providers가 비어있으면 그냥 반환 (YAML 로딩 시 설정됨)
            return v

        enabled_providers = [name for name, config in v.items() if config.enabled]

        if not enabled_providers:
            raise ValueError("At least one reranking provider must be enabled")

        # 활성화된 제공자는 model 필수
        for name, config in v.items():
            if config.enabled and not config.model:
                raise ValueError(f"Provider '{name}' is enabled but has no model specified")

        return v
