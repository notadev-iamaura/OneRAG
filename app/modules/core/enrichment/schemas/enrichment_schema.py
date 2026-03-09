"""
Enrichment Schema 정의

LLM 보강 데이터 구조를 Pydantic으로 정의하여 타입 안전성과 검증을 보장합니다.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class EnrichmentResult(BaseModel):
    """
    LLM 보강 결과 데이터 모델

    Attributes:
        category: 주요 카테고리 (예: "기술", "비즈니스", "교육", "건강")
        subcategory: 세부 카테고리 (예: "프로그래밍", "마케팅", "튜토리얼")
        intent: 텍스트의 주요 의도 (예: "정보 제공", "문제 해결", "안내")
        content_type: 콘텐츠 유형 (예: "FAQ", "가이드", "보고서", "공지사항")
        keywords: 키워드 리스트 (예: ["Python", "리스트", "반복문"])
        summary: 문서 요약 (한 줄 설명)
        is_tool_related: 도구/기능 관련 여부
        requires_db_check: 데이터베이스 확인 필요 여부
        confidence_score: LLM 응답 신뢰도 (0.0-1.0, 선택적)
        enriched_at: 보강 수행 시각 (UTC)

    사용 예시:
        >>> result = EnrichmentResult(
        ...     category="기술",
        ...     subcategory="프로그래밍",
        ...     intent="정보 제공",
        ...     content_type="튜토리얼",
        ...     keywords=["Python", "리스트 컴프리헨션"],
        ...     summary="Python 리스트 컴프리헨션 사용법 설명",
        ...     is_tool_related=True,
        ...     requires_db_check=False
        ... )
        >>> result.to_dict()
    """

    category: str = Field(..., description="주요 카테고리", min_length=1, max_length=100)

    subcategory: str = Field(..., description="세부 카테고리", min_length=1, max_length=100)

    intent: str = Field(..., description="텍스트의 주요 의도", min_length=1, max_length=200)

    content_type: str = Field(..., description="콘텐츠 유형", min_length=1, max_length=100)

    keywords: list[str] = Field(
        default_factory=list, description="키워드 리스트", min_length=0, max_length=20
    )

    summary: str = Field(..., description="문서 요약", min_length=1, max_length=500)

    is_tool_related: bool = Field(default=False, description="도구/기능 관련 여부")

    requires_db_check: bool = Field(default=False, description="데이터베이스 확인 필요 여부")

    confidence_score: float | None = Field(
        default=None, description="LLM 응답 신뢰도 (0.0-1.0)", ge=0.0, le=1.0
    )

    enriched_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="보강 수행 시각 (UTC)"
    )

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, v: list[str]) -> list[str]:
        """키워드 유효성 검증 (중복 제거 및 빈 문자열 제거)"""
        # 빈 문자열 제거
        keywords = [k.strip() for k in v if k and k.strip()]
        # 중복 제거 (순서 유지)
        seen = set()
        unique_keywords = []
        for k in keywords:
            if k not in seen:
                seen.add(k)
                unique_keywords.append(k)
        return unique_keywords

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        """요약문 유효성 검증 (공백 제거)"""
        return v.strip()

    def to_dict(self) -> dict[str, Any]:
        """
        딕셔너리로 변환 (MongoDB 저장용)

        Returns:
            dict: enriched_at을 ISO 8601 문자열로 변환한 딕셔너리
        """
        data = self.model_dump()
        # datetime을 ISO 8601 문자열로 변환
        data["enriched_at"] = self.enriched_at.isoformat()
        return data

    class Config:
        """Pydantic 설정"""

        json_encoders = {datetime: lambda v: v.isoformat()}


class EnrichmentConfig(BaseModel):
    """
    Enrichment 설정 모델

    Attributes:
        enabled: 보강 기능 활성화 여부
        llm_model: 사용할 LLM 모델명
        llm_temperature: LLM 온도 (0.0-1.0)
        llm_max_tokens: 최대 토큰 수
        batch_size: 배치 크기
        batch_concurrency: 동시 처리 수
        timeout_single: 단건 타임아웃 (초)
        timeout_batch: 배치 타임아웃 (초)
        max_retries: 최대 재시도 횟수
        cache_enabled: 캐싱 활성화 여부
        min_confidence: 최소 신뢰도 점수
        fallback_to_original: 실패 시 원본 사용 여부

    사용 예시:
        >>> config = EnrichmentConfig(
        ...     enabled=True,
        ...     llm_model="gpt-4o-mini",
        ...     batch_size=10
        ... )
    """

    enabled: bool = Field(default=False, description="보강 기능 활성화 여부")

    llm_model: str = Field(default="gpt-4o-mini", description="사용할 LLM 모델명")

    llm_temperature: float = Field(default=0.1, description="LLM 온도 (0.0-1.0)", ge=0.0, le=1.0)

    llm_max_tokens: int = Field(default=1000, description="최대 토큰 수", gt=0, le=4096)

    batch_size: int = Field(default=10, description="배치 크기", gt=0, le=100)

    batch_concurrency: int = Field(default=3, description="동시 처리 수", gt=0, le=10)

    timeout_single: int = Field(default=30, description="단건 타임아웃 (초)", gt=0, le=300)

    timeout_batch: int = Field(default=90, description="배치 타임아웃 (초)", gt=0, le=600)

    max_retries: int = Field(default=3, description="최대 재시도 횟수", ge=0, le=10)

    cache_enabled: bool = Field(default=False, description="캐싱 활성화 여부")

    min_confidence: float = Field(
        default=0.0, description="최소 신뢰도 점수 (0.0-1.0)", ge=0.0, le=1.0
    )

    fallback_to_original: bool = Field(default=True, description="실패 시 원본 사용 여부")

    class Config:
        """Pydantic 설정"""

        extra = "allow"  # 추가 필드 허용 (확장성)
