"""
Generation (답변 생성) 설정 스키마

LLM 답변 생성, 프롬프트 관리 등의 설정을 정의합니다.
"""

from pydantic import Field, field_validator

from .base import BaseConfig


class GenerationConfig(BaseConfig):
    """
    답변 생성 설정

    LLM 파라미터, 프롬프트 템플릿 등을 정의합니다.
    """

    # 기본 LLM 설정
    default_provider: str = Field(
        default="google",
        pattern="^(google|openai|anthropic|openrouter)$",
        description="기본 LLM 제공자 (google, openai, anthropic, openrouter)",
    )

    default_model: str = Field(
        default="gemini-2.5-pro-latest",
        description="기본 LLM 모델",
    )

    temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description="생성 온도 (0.0=결정적, 2.0=창의적)",
    )

    max_tokens: int = Field(
        default=2048,
        ge=100,
        le=32000,
        description="최대 생성 토큰 수 (100-32000)",
    )

    # 프롬프트 설정
    system_prompt: str | None = Field(
        default=None,
        description="시스템 프롬프트 (None이면 기본 프롬프트 사용)",
    )

    use_few_shot: bool = Field(
        default=True,
        description="Few-shot 예제 사용 여부",
    )

    # Failover 설정
    enable_failover: bool = Field(
        default=True,
        description="LLM Failover 활성화 여부",
    )

    failover_providers: list[str] = Field(
        default=["google", "openai", "anthropic"],
        description="Failover 순서",
    )

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        """
        온도가 0.0-2.0 범위인지 검증
        """
        if not 0.0 <= v <= 2.0:
            raise ValueError("temperature must be between 0.0 and 2.0")
        return v

    @field_validator("failover_providers")
    @classmethod
    def validate_failover_providers(cls, v: list[str]) -> list[str]:
        """
        Failover 제공자가 유효한지 검증
        """
        valid_providers = {"google", "openai", "anthropic", "openrouter"}
        for provider in v:
            if provider not in valid_providers:
                raise ValueError(
                    f"Invalid provider: {provider}. " f"Must be one of {valid_providers}"
                )
        return v
