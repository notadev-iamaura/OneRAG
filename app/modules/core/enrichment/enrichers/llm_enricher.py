"""
LLM Enricher

OpenAI GPT-4o-mini를 사용하여 문서를 보강하는 구현체입니다.

주요 기능:
- 단일 문서 보강
- 배치 처리 (성능 최적화)
- 에러 처리 및 재시도
- 타임아웃 관리
- JSON 파싱 및 검증
"""

import asyncio
import json
from typing import Any

from openai import APIError, APITimeoutError, OpenAI

from app.lib.logger import get_logger

from ..interfaces.enricher_interface import EnricherInterface
from ..prompts.enrichment_prompts import build_batch_enrichment_prompt, build_enrichment_prompt
from ..schemas.enrichment_schema import EnrichmentConfig, EnrichmentResult

logger = get_logger(__name__)


class LLMEnricher(EnricherInterface):
    """
    LLM 기반 문서 보강 구현체

    OpenAI GPT-4o-mini를 사용하여 문서 메타데이터를 자동 생성합니다.

    특징:
        - Graceful Degradation: 실패 시 None 반환 (원본 문서 사용)
        - 재시도 로직: Exponential Backoff 적용
        - 타임아웃: 단건 30초, 배치 90초
        - 배치 최적화: 10개씩 묶어서 처리

    사용 예시:
        >>> config = EnrichmentConfig(
        ...     enabled=True,
        ...     llm_model="gpt-4o-mini",
        ...     llm_temperature=0.1,
        ...     batch_size=10
        ... )
        >>> enricher = LLMEnricher(config, openai_api_key="sk-...")
        >>> await enricher.initialize()
        >>>
        >>> document = {"content": "Python 리스트 컴프리헨션 사용법"}
        >>> result = await enricher.enrich(document)
        >>> print(result.category)  # "기술"
    """

    def __init__(self, config: EnrichmentConfig, openai_api_key: str):
        """
        LLMEnricher 초기화

        Args:
            config: Enrichment 설정
            openai_api_key: OpenAI API 키
        """
        self.config = config
        self.api_key = openai_api_key
        self.client: OpenAI | None = None

        # 통계
        self.stats = {
            "total_enrichments": 0,
            "successful_enrichments": 0,
            "failed_enrichments": 0,
            "total_tokens_used": 0,
            "average_latency": 0.0,
        }

        logger.info(
            "LLMEnricher initialized",
            model=config.llm_model,
            temperature=config.llm_temperature,
            batch_size=config.batch_size,
        )

    async def initialize(self) -> None:
        """OpenAI 클라이언트 초기화"""
        try:
            self.client = OpenAI(api_key=self.api_key)
            logger.info("OpenAI client initialized for enrichment")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise

    async def cleanup(self) -> None:
        """리소스 정리"""
        self.client = None
        logger.info("LLMEnricher cleaned up")

    async def enrich(self, document: dict[str, Any]) -> EnrichmentResult | None:
        """
        단일 문서 보강

        Args:
            document: 보강할 문서 (content 필드 필수)

        Returns:
            EnrichmentResult | None: 보강 결과 (실패 시 None)
        """
        if not self.client:
            logger.warning("OpenAI client not initialized")
            return None

        content = document.get("content")
        if not content:
            logger.warning("Document has no content field")
            return None

        self.stats["total_enrichments"] += 1

        try:
            # 프롬프트 생성
            system_prompt, user_prompt = build_enrichment_prompt(content)

            # LLM 호출 (재시도 포함)
            result_json = await self._call_llm_with_retry(
                system_prompt, user_prompt, timeout=self.config.timeout_single
            )

            if not result_json:
                return None

            # EnrichmentResult 생성
            enrichment = EnrichmentResult(**result_json)

            # 검증
            if not await self.validate_enrichment(enrichment):
                logger.warning("Enrichment validation failed")
                self.stats["failed_enrichments"] += 1
                return None

            self.stats["successful_enrichments"] += 1
            logger.debug(
                "Document enriched successfully",
                category=enrichment.category,
                keywords=len(enrichment.keywords),
            )

            return enrichment

        except Exception as e:
            logger.error(f"Enrichment failed: {e}", exc_info=True)
            self.stats["failed_enrichments"] += 1
            return None

    async def enrich_batch(self, documents: list[dict[str, Any]]) -> list[EnrichmentResult | None]:
        """
        배치 문서 보강 (최대 10개씩 묶어서 처리)

        Args:
            documents: 보강할 문서 리스트

        Returns:
            list[EnrichmentResult | None]: 보강 결과 리스트
        """
        if not self.client:
            logger.warning("OpenAI client not initialized")
            return [None] * len(documents)

        if not documents:
            return []

        # 배치 크기로 나누기
        batch_size = min(self.config.batch_size, 10)  # 최대 10개
        results: list[EnrichmentResult | None] = []

        for i in range(0, len(documents), batch_size):
            batch = documents[i : i + batch_size]

            try:
                # 배치 프롬프트 생성
                system_prompt, user_prompt = build_batch_enrichment_prompt(batch)

                # LLM 호출 (재시도 포함)
                batch_results_json = await self._call_llm_with_retry(
                    system_prompt, user_prompt, timeout=self.config.timeout_batch, expect_array=True
                )

                if not batch_results_json:
                    # 실패 시 None으로 채우기
                    results.extend([None] * len(batch))
                    continue

                # 각 결과를 EnrichmentResult로 변환
                for result_json in batch_results_json:
                    try:
                        enrichment = EnrichmentResult(**result_json)

                        # 검증
                        if await self.validate_enrichment(enrichment):
                            results.append(enrichment)
                            self.stats["successful_enrichments"] += 1
                        else:
                            results.append(None)
                            self.stats["failed_enrichments"] += 1

                    except Exception as e:
                        logger.error(f"Failed to parse enrichment result: {e}")
                        results.append(None)
                        self.stats["failed_enrichments"] += 1

            except Exception as e:
                logger.error(f"Batch enrichment failed: {e}", exc_info=True)
                results.extend([None] * len(batch))
                self.stats["failed_enrichments"] += len(batch)

        logger.info(
            f"Batch enrichment completed: {len(results)} documents, "
            f"{sum(1 for r in results if r is not None)} successful"
        )

        return results

    async def validate_enrichment(self, enrichment: EnrichmentResult) -> bool:
        """
        보강 결과 검증

        검증 기준:
            - 필수 필드 존재 여부
            - 키워드 최소 1개
            - 신뢰도 점수 (설정된 경우)

        Args:
            enrichment: 검증할 보강 결과

        Returns:
            bool: 검증 성공 여부
        """
        try:
            # 필수 필드 확인
            if not enrichment.category:
                logger.warning("Missing category")
                return False

            if not enrichment.summary:
                logger.warning("Missing summary")
                return False

            # 키워드 최소 개수 (권장)
            if len(enrichment.keywords) < 1:
                logger.warning("No keywords extracted")
                # 경고만 하고 통과 (선택적)

            # 신뢰도 점수 확인 (설정된 경우)
            if enrichment.confidence_score is not None:
                if enrichment.confidence_score < self.config.min_confidence:
                    logger.warning(f"Confidence score too low: {enrichment.confidence_score}")
                    return False

            return True

        except Exception as e:
            logger.error(f"Validation error: {e}")
            return False

    async def _call_llm_with_retry(
        self, system_prompt: str, user_prompt: str, timeout: int, expect_array: bool = False
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """
        LLM 호출 (재시도 로직 포함)

        Args:
            system_prompt: 시스템 프롬프트
            user_prompt: 사용자 프롬프트
            timeout: 타임아웃 (초)
            expect_array: JSON 배열 응답 여부

        Returns:
            dict | list[dict] | None: 파싱된 JSON 결과 (실패 시 None)
        """
        for attempt in range(self.config.max_retries):
            try:
                # LLM 호출
                response_text = await self._call_llm(system_prompt, user_prompt, timeout)

                if not response_text:
                    continue

                # JSON 파싱
                result = self._parse_json_response(response_text, expect_array)

                if result:
                    return result

            except APITimeoutError:
                logger.warning(f"LLM timeout (attempt {attempt + 1}/{self.config.max_retries})")
                # Exponential backoff: 1초 → 2초 → 4초
                await asyncio.sleep(1.0 * (2**attempt))

            except APIError as e:
                logger.error(f"LLM API error (attempt {attempt + 1}): {e}")
                # Exponential backoff: 1초 → 2초 → 4초
                await asyncio.sleep(1.0 * (2**attempt))

            except Exception as e:
                logger.error(f"Unexpected error (attempt {attempt + 1}): {e}")
                break

        logger.error("All LLM retry attempts failed")
        return None

    async def _call_llm(self, system_prompt: str, user_prompt: str, timeout: int) -> str | None:
        """
        OpenAI API 호출

        Args:
            system_prompt: 시스템 프롬프트
            user_prompt: 사용자 프롬프트
            timeout: 타임아웃 (초)

        Returns:
            str | None: LLM 응답 텍스트 (실패 시 None)
        """
        try:
            # asyncio.to_thread로 동기 API를 비동기로 래핑
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.chat.completions.create,
                    model=self.config.llm_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=self.config.llm_temperature,
                    max_tokens=self.config.llm_max_tokens,
                ),
                timeout=timeout,
            )

            # 토큰 사용량 추적
            if hasattr(response, "usage"):
                tokens = response.usage.total_tokens
                self.stats["total_tokens_used"] += tokens
                logger.debug(f"Tokens used: {tokens}")

            # 응답 텍스트 추출
            answer = response.choices[0].message.content
            return answer

        except TimeoutError:
            logger.error(f"LLM call timeout ({timeout}s)")
            raise APITimeoutError("Request timed out")

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

    def _parse_json_response(
        self, response_text: str, expect_array: bool = False
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """
        JSON 응답 파싱

        Args:
            response_text: LLM 응답 텍스트
            expect_array: JSON 배열 응답 여부

        Returns:
            dict | list[dict] | None: 파싱된 JSON (실패 시 None)
        """
        try:
            # Markdown 코드 블록 제거 (LLM이 ```json ... ``` 형식으로 응답하는 경우)
            cleaned_text = response_text.strip()
            if cleaned_text.startswith("```"):
                # ```json과 ``` 제거
                cleaned_text = cleaned_text.split("```")[1]
                if cleaned_text.startswith("json"):
                    cleaned_text = cleaned_text[4:].strip()

            # JSON 파싱
            result = json.loads(cleaned_text)

            # 타입 검증
            if expect_array and not isinstance(result, list):
                logger.warning("Expected JSON array but got object")
                return None

            if not expect_array and not isinstance(result, dict):
                logger.warning("Expected JSON object but got array")
                return None

            return result

        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed: {e}")
            logger.debug(f"Raw response: {response_text[:500]}")
            return None

        except Exception as e:
            logger.error(f"Unexpected parsing error: {e}")
            return None

    def get_stats(self) -> dict[str, Any]:
        """
        통계 반환

        Returns:
            dict: 보강 통계
        """
        success_rate = 0.0
        if self.stats["total_enrichments"] > 0:
            success_rate = (
                self.stats["successful_enrichments"] / self.stats["total_enrichments"]
            ) * 100

        return {**self.stats, "success_rate": success_rate}
