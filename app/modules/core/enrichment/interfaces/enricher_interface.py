"""
Enricher Interface

모든 보강 구현체가 따라야 할 추상 인터페이스입니다.
Strategy 패턴을 적용하여 다양한 보강 방법을 교체 가능하게 합니다.
"""

from abc import ABC, abstractmethod
from typing import Any

from ..schemas.enrichment_schema import EnrichmentResult


class EnricherInterface(ABC):
    """
    문서 보강 인터페이스

    모든 보강 구현체(LLMEnricher, NullEnricher 등)는 이 인터페이스를 구현해야 합니다.

    Strategy 패턴:
        - Context: EnrichmentService
        - Strategy: EnricherInterface
        - ConcreteStrategy: LLMEnricher, NullEnricher, RuleBasedEnricher 등

    사용 예시:
        >>> class MyEnricher(EnricherInterface):
        ...     async def enrich(self, document: dict) -> EnrichmentResult:
        ...         # 보강 로직 구현
        ...         return EnrichmentResult(...)
        ...
        ...     async def enrich_batch(self, documents: list[dict]) -> list[EnrichmentResult]:
        ...         return [await self.enrich(doc) for doc in documents]
    """

    @abstractmethod
    async def enrich(self, document: dict[str, Any]) -> EnrichmentResult | None:
        """
        단일 문서 보강

        Args:
            document: 보강할 문서 (content 필드 필수)
                예시: {"content": "Python 리스트 컴프리헨션 사용법에 대한 설명입니다."}

        Returns:
            EnrichmentResult: 보강 결과
            None: 보강 실패 또는 스킵

        Raises:
            ValueError: document에 content 필드가 없는 경우
            TimeoutError: 보강 시간 초과
            Exception: 기타 보강 실패

        사용 예시:
            >>> enricher = LLMEnricher(config)
            >>> document = {"content": "Python 리스트 컴프리헨션 사용법"}
            >>> result = await enricher.enrich(document)
            >>> print(result.category)  # "기술"
        """
        pass

    @abstractmethod
    async def enrich_batch(self, documents: list[dict[str, Any]]) -> list[EnrichmentResult | None]:
        """
        배치 문서 보강

        여러 문서를 한 번에 처리하여 성능을 최적화합니다.
        일부 문서 실패 시에도 나머지는 계속 처리합니다.

        Args:
            documents: 보강할 문서 리스트

        Returns:
            list[EnrichmentResult | None]: 보강 결과 리스트
                - 성공: EnrichmentResult
                - 실패: None

        사용 예시:
            >>> enricher = LLMEnricher(config)
            >>> documents = [
            ...     {"content": "Python 리스트 컴프리헨션 설명"},
            ...     {"content": "2024년 매출 보고서"}
            ... ]
            >>> results = await enricher.enrich_batch(documents)
            >>> print(len(results))  # 2
            >>> print(results[0].category if results[0] else None)  # "기술"
        """
        pass

    @abstractmethod
    async def validate_enrichment(self, enrichment: EnrichmentResult) -> bool:
        """
        보강 결과 검증

        보강 결과가 품질 기준을 만족하는지 확인합니다.

        Args:
            enrichment: 검증할 보강 결과

        Returns:
            bool: 검증 성공 여부
                - True: 품질 기준 만족
                - False: 품질 기준 미달

        검증 기준 (예시):
            - 필수 필드 존재 여부
            - 키워드 개수 (최소 1개)
            - 신뢰도 점수 (최소 threshold 이상)
            - 카테고리 유효성

        사용 예시:
            >>> result = await enricher.enrich(document)
            >>> is_valid = await enricher.validate_enrichment(result)
            >>> if is_valid:
            ...     # 보강 결과 사용
            ...     pass
            >>> else:
            ...     # 원본 문서 사용 (fallback)
            ...     pass
        """
        pass

    async def initialize(self) -> None:  # noqa: B027
        """
        Enricher 초기화 (선택적)

        LLM 클라이언트 연결, 캐시 준비 등 초기화 작업을 수행합니다.
        기본 구현은 아무 작업도 하지 않습니다.

        사용 예시:
            >>> enricher = LLMEnricher(config)
            >>> await enricher.initialize()  # LLM 클라이언트 연결
        """
        pass

    async def cleanup(self) -> None:  # noqa: B027
        """
        Enricher 정리 (선택적)

        연결 종료, 리소스 해제 등 정리 작업을 수행합니다.
        기본 구현은 아무 작업도 하지 않습니다.

        사용 예시:
            >>> enricher = LLMEnricher(config)
            >>> await enricher.cleanup()  # LLM 클라이언트 연결 종료
        """
        pass
