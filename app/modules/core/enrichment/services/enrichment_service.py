"""
Enrichment Service

문서 보강을 오케스트레이션하는 서비스 계층입니다.

주요 기능:
- Enricher 인스턴스 관리 (NullEnricher vs LLMEnricher)
- 배치 처리 및 병렬 실행
- 에러 핸들링 및 로깅
- 성능 메트릭 수집
"""

import asyncio
from typing import Any

from app.lib.logger import get_logger

from ..enrichers.llm_enricher import LLMEnricher
from ..enrichers.null_enricher import NullEnricher
from ..interfaces.enricher_interface import EnricherInterface
from ..schemas.enrichment_schema import EnrichmentConfig, EnrichmentResult

logger = get_logger(__name__)


class EnrichmentService:
    """
    문서 보강 오케스트레이션 서비스

    설정에 따라 적절한 Enricher를 선택하고 관리합니다.
    - enabled=false: NullEnricher 사용 (보강 안 함)
    - enabled=true: LLMEnricher 사용 (LLM 보강)

    사용 예시:
        >>> from app.lib.config_loader import load_config
        >>> config = load_config()
        >>> service = EnrichmentService(config)
        >>> await service.initialize()
        >>>
        >>> # 단일 문서 보강
        >>> document = {"content": "..."}
        >>> enriched = await service.enrich(document)
        >>>
        >>> # 배치 처리
        >>> documents = [{"content": "..."}, ...]
        >>> enriched_docs = await service.enrich_batch(documents)
        >>>
        >>> await service.cleanup()
    """

    def __init__(self, config: dict[str, Any]):
        """
        EnrichmentService 초기화

        Args:
            config: 전체 설정 딕셔너리 (enrichment 섹션 포함)
        """
        self.config = config
        self.enrichment_config = self._parse_enrichment_config(config)
        self.enricher: EnricherInterface | None = None

        logger.info("EnrichmentService initialized", enabled=self.enrichment_config.enabled)

    def _parse_enrichment_config(self, config: dict[str, Any]) -> EnrichmentConfig:
        """
        설정에서 EnrichmentConfig 추출

        Args:
            config: 전체 설정 딕셔너리

        Returns:
            EnrichmentConfig: 파싱된 설정
        """
        enrichment_section = config.get("enrichment", {})

        # LLM 설정 추출
        llm_section = enrichment_section.get("llm", {})

        # 배치 설정 추출
        batch_section = enrichment_section.get("batch", {})

        # 타임아웃 설정 추출
        timeout_section = enrichment_section.get("timeout", {})

        # 재시도 설정 추출
        retry_section = enrichment_section.get("retry", {})

        # 캐싱 설정 추출
        cache_section = enrichment_section.get("cache", {})

        # 품질 설정 추출
        quality_section = enrichment_section.get("quality", {})

        # 프롬프트 설정 추출 (config 외부화)
        # 키가 없으면 None → 프롬프트 빌더가 코드 내장 한국어 기본값 사용 (회귀 0).
        prompt_section = enrichment_section.get("prompt", {})

        return EnrichmentConfig(
            enabled=enrichment_section.get("enabled", False),
            llm_model=llm_section.get("model", "gpt-4o-mini"),
            llm_temperature=llm_section.get("temperature", 0.1),
            llm_max_tokens=llm_section.get("max_tokens", 1000),
            batch_size=batch_section.get("size", 10),
            batch_concurrency=batch_section.get("concurrency", 3),
            timeout_single=timeout_section.get("single", 30),
            timeout_batch=timeout_section.get("batch", 90),
            max_retries=retry_section.get("max_attempts", 3),
            cache_enabled=cache_section.get("enabled", False),
            min_confidence=quality_section.get("min_confidence", 0.0),
            fallback_to_original=quality_section.get("fallback_to_original", True),
            # 프롬프트 오버라이드 (없으면 None → 코드 내장 한국어 기본 프롬프트)
            system_prompt=prompt_section.get("system_prompt"),
            few_shot_examples=prompt_section.get("few_shot_examples"),
            user_prompt_template=prompt_section.get("user_prompt_template"),
            include_examples=prompt_section.get("include_examples", True),
        )

    async def initialize(self) -> None:
        """
        Enricher 초기화

        설정에 따라 적절한 Enricher 인스턴스를 생성하고 초기화합니다.
        """
        try:
            if not self.enrichment_config.enabled:
                # 보강 비활성화 -> NullEnricher 사용
                self.enricher = NullEnricher()
                logger.info("Enrichment disabled, using NullEnricher")

            else:
                # 보강 활성화 -> LLMEnricher 사용
                openai_api_key = self._get_openai_api_key()

                if not openai_api_key:
                    logger.warning("OpenAI API key not found, falling back to NullEnricher")
                    self.enricher = NullEnricher()
                    return

                self.enricher = LLMEnricher(
                    config=self.enrichment_config, openai_api_key=openai_api_key
                )

                await self.enricher.initialize()
                logger.info("Enrichment enabled, using LLMEnricher")

        except Exception as e:
            logger.error(f"Failed to initialize enricher: {e}")
            # Fallback to NullEnricher
            self.enricher = NullEnricher()
            logger.warning("Falling back to NullEnricher due to initialization error")

    async def cleanup(self) -> None:
        """Enricher 정리"""
        if self.enricher:
            await self.enricher.cleanup()
            self.enricher = None
            logger.info("EnrichmentService cleaned up")

    async def enrich(self, document: dict[str, Any]) -> EnrichmentResult | None:
        """
        단일 문서 보강

        Args:
            document: 보강할 문서 (content 필드 필수)

        Returns:
            EnrichmentResult | None: 보강 결과 (실패 시 None)
        """
        if not self.enricher:
            logger.warning("Enricher not initialized")
            return None

        try:
            result = await self.enricher.enrich(document)
            return result

        except Exception as e:
            logger.error(f"Enrichment error: {e}", exc_info=True)
            return None

    async def enrich_batch(self, documents: list[dict[str, Any]]) -> list[EnrichmentResult | None]:
        """
        배치 문서 보강 (병렬 처리 지원)

        Args:
            documents: 보강할 문서 리스트

        Returns:
            list[EnrichmentResult | None]: 보강 결과 리스트
        """
        if not self.enricher:
            logger.warning("Enricher not initialized")
            return [None] * len(documents)

        if not documents:
            return []

        try:
            # 동시 처리 수에 따라 세마포어 설정
            concurrency = self.enrichment_config.batch_concurrency
            semaphore = asyncio.Semaphore(concurrency)

            # 배치 크기로 나누기
            batch_size = self.enrichment_config.batch_size
            batches = [documents[i : i + batch_size] for i in range(0, len(documents), batch_size)]

            # 병렬 처리
            async def process_batch(batch: list[dict[str, Any]]) -> list[EnrichmentResult | None]:
                async with semaphore:
                    return await self.enricher.enrich_batch(batch)

            # 모든 배치 병렬 실행
            batch_results = await asyncio.gather(
                *[process_batch(batch) for batch in batches], return_exceptions=True
            )

            # 결과 평탄화
            results: list[EnrichmentResult | None] = []
            for batch, batch_result in zip(batches, batch_results, strict=True):
                if isinstance(batch_result, Exception):
                    logger.error(f"Batch processing error: {batch_result}")
                    # 실패한 배치는 None으로 채우기
                    results.extend([None] * len(batch))
                else:
                    results.extend(batch_result)

            logger.info(
                f"Batch enrichment completed: {len(documents)} documents, "
                f"{sum(1 for r in results if r is not None)} successful"
            )

            return results

        except Exception as e:
            logger.error(f"Batch enrichment error: {e}", exc_info=True)
            return [None] * len(documents)

    def is_enabled(self) -> bool:
        """
        보강 기능 활성화 여부 확인

        Returns:
            bool: 활성화 여부
        """
        return self.enrichment_config.enabled

    def get_stats(self) -> dict[str, Any]:
        """
        통계 반환

        Returns:
            dict: 보강 통계 (LLMEnricher 사용 시에만 유효)
        """
        if isinstance(self.enricher, LLMEnricher):
            return self.enricher.get_stats()
        else:
            return {"enabled": False, "enricher_type": "NullEnricher"}

    def _get_openai_api_key(self) -> str | None:
        """
        OpenAI API 키 가져오기

        우선순위:
            1. enrichment.llm.api_key
            2. config의 다른 OpenAI 설정 (generation.openai.api_key 등)

        Returns:
            str | None: API 키 (없으면 None)
        """
        # 1순위: enrichment 전용 API 키
        enrichment_section = self.config.get("enrichment", {})
        llm_section = enrichment_section.get("llm", {})
        api_key = llm_section.get("api_key")

        if api_key:
            return api_key

        # 2순위: generation.openai.api_key
        generation_section = self.config.get("generation", {})
        openai_section = generation_section.get("openai", {})
        api_key = openai_section.get("api_key")

        if api_key:
            logger.info("Using OpenAI API key from generation.openai.api_key")
            return api_key

        # 3순위: llm.openai.api_key (레거시)
        llm_config = self.config.get("llm", {})
        openai_config = llm_config.get("openai", {})
        api_key = openai_config.get("api_key")

        if api_key:
            logger.info("Using OpenAI API key from llm.openai.api_key")
            return api_key

        logger.warning("No OpenAI API key found in config")
        return None
