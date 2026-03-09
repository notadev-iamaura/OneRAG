"""
Scoring Service 모듈

설정 기반 점수 가중치 적용 서비스.
Blank System 철학에 따라 기본값은 가중치 없이 순수 점수를 반환한다.

사용법:
    config = {"collection_weight_enabled": True, ...}
    service = ScoringService(config)
    weighted_score = service.apply_weight(score, collection, file_type)

설계 원칙:
    - 기본값(enabled=False): 가중치 없이 원본 점수 반환 (Plain Result)
    - 활성화(enabled=True): 설정된 가중치를 점수에 곱함 (Opt-in)
    - 알 수 없는 컬렉션/파일타입: 기본 가중치 1.0 적용 (안전한 폴백)
"""
from __future__ import annotations

from app.lib.logger import get_logger

logger = get_logger(__name__)


class ScoringService:
    """
    설정 기반 점수 가중치 서비스

    원칙:
    - 기본값(enabled=False): 가중치 없이 원본 점수 반환
    - 활성화(enabled=True): 설정된 가중치를 점수에 곱함

    Attributes:
        collection_weight_enabled: 컬렉션별 가중치 활성화 여부
        file_type_weight_enabled: 파일 타입별 가중치 활성화 여부
        collection_weights: 컬렉션별 가중치 딕셔너리 (예: {"Metadata": 1.5})
        file_type_weights: 파일 타입별 가중치 딕셔너리 (예: {"PDF": 1.2})
    """

    def __init__(self, config: dict) -> None:
        """
        ScoringService 초기화

        Args:
            config: scoring 설정 딕셔너리
                - collection_weight_enabled: bool (기본값 False)
                - file_type_weight_enabled: bool (기본값 False)
                - collection_weights: dict[str, float] (기본값 {})
                - file_type_weights: dict[str, float] (기본값 {})
        """
        self.collection_weight_enabled: bool = config.get("collection_weight_enabled", False)
        self.file_type_weight_enabled: bool = config.get("file_type_weight_enabled", False)

        self.collection_weights: dict[str, float] = config.get("collection_weights", {})
        self.file_type_weights: dict[str, float] = config.get("file_type_weights", {})

        logger.debug(
            f"ScoringService 초기화: "
            f"collection_weight={self.collection_weight_enabled}, "
            f"file_type_weight={self.file_type_weight_enabled}"
        )

    def apply_weight(
        self,
        score: float,
        collection: str | None = None,
        file_type: str | None = None,
    ) -> float:
        """
        점수에 가중치를 적용한다.

        Args:
            score: 원본 점수
            collection: 컬렉션 이름 (예: "Metadata", "Documents")
            file_type: 파일 타입 (예: "PDF", "TXT")

        Returns:
            가중치가 적용된 점수 (비활성화 시 원본 그대로)

        Examples:
            >>> service = ScoringService({"collection_weight_enabled": True, "collection_weights": {"Metadata": 1.5}})
            >>> service.apply_weight(0.5, collection="Metadata")
            0.75
        """
        result = score

        # 컬렉션 가중치 적용
        if self.collection_weight_enabled and collection:
            multiplier = self.collection_weights.get(collection, 1.0)
            result *= multiplier

        # 파일 타입 가중치 적용
        if self.file_type_weight_enabled and file_type:
            # 대소문자 정규화 (PDF, pdf, Pdf → PDF)
            file_type_upper = file_type.upper()
            multiplier = self.file_type_weights.get(file_type_upper, 1.0)
            result *= multiplier

        return result

    def __repr__(self) -> str:
        """디버깅용 문자열 표현"""
        return (
            f"ScoringService("
            f"collection_weight={self.collection_weight_enabled}, "
            f"file_type_weight={self.file_type_weight_enabled}, "
            f"collection_weights={self.collection_weights}, "
            f"file_type_weights={self.file_type_weights})"
        )

