"""
OpenAI LLM Reranker Implementation

OpenAI 모델 기반 범용 LLM Reranker:
- 모델 설정 가능 (기본값: gpt-5-nano, gpt-4o-mini 등 지원)
- responses.create() API 사용 (input + reasoning + text 파라미터)
- JSON 응답 파싱 (3단계 fallback: 정상 → 코드블록 → 수동 추출)
- 문서 250자 프리뷰로 속도 최적화
- 에러 시 원본 결과 반환으로 안정성 보장

리팩토링 이력:
- v3.1.0: GPT5NanoReranker에서 리팩토링
- 모델명을 하드코딩에서 설정 가능으로 변경
"""

import asyncio
import json
import re
import time
from typing import Any, cast

import structlog

from ..interfaces import IReranker, SearchResult

logger = structlog.get_logger(__name__)


class OpenAILLMReranker(IReranker):
    """
    OpenAI LLM 기반 Reranker

    OpenAI 모델을 사용한 고속 문서 리랭킹:
    - 모델 설정 가능 (gpt-5-nano, gpt-4o-mini 등)
    - reasoning effort 최소화로 빠른 응답
    - verbosity 최소화로 토큰 효율성
    - JSON 형식 응답 파싱
    - 원본 점수 보존 및 개선도 추적

    Features:
    - 최대 20개 문서 처리 (설정 가능)
    - 15초 타임아웃 (설정 가능)
    - 3단계 JSON 파싱 fallback
    - 에러 시 원본 결과 반환 (fail-safe)
    """

    # 코드 내장 기본 랭킹 프롬프트 (config 미설정 시 사용)
    # 플레이스홀더: {query}, {documents_text}, {top_k}
    # str.format()으로 채워지므로 JSON 예시의 중괄호는 {{ }}로 이스케이프되어 있다.
    # config(reranking.openai.prompt_template) 주입 시에만 오버라이드된다(회귀 0).
    DEFAULT_PROMPT_TEMPLATE = """You are a document ranking expert. Evaluate and rank documents based on their relevance to the query.

Query: "{query}"

Documents:
{documents_text}

Task: Score each document from 0.0 to 1.0 based on relevance to the query.
Select only the top {top_k} most relevant documents.

IMPORTANT: Respond ONLY with valid JSON in this exact format:
{{"results": [{{"index": 0, "score": 0.95}}, {{"index": 2, "score": 0.8}}, {{"index": 1, "score": 0.6}}]}}

Do not include any other text, explanation, or formatting. Only the JSON object."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5-nano",
        max_documents: int = 20,
        timeout: int = 15,
        verbosity: str = "low",
        reasoning_effort: str = "minimal",
        prompt_template: str | None = None,
    ):
        """
        Args:
            api_key: OpenAI API 키
            model: 사용할 OpenAI 모델 (기본값: gpt-5-nano)
            max_documents: 처리할 최대 문서 개수
            timeout: 타임아웃 (초)
            verbosity: OpenAI verbosity 파라미터 (low, medium, high)
            reasoning_effort: reasoning effort 파라미터 (minimal, standard, high)
            prompt_template: 랭킹 프롬프트 템플릿 오버라이드.
                None이면 코드 내장 DEFAULT_PROMPT_TEMPLATE 사용(회귀 0).
                {query}/{documents_text}/{top_k} 플레이스홀더를 지원한다.
        """
        if not api_key:
            raise ValueError("OpenAI API key is required")

        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.max_documents = max_documents
        self.timeout = timeout
        self.verbosity = verbosity
        self.reasoning_effort = reasoning_effort
        # 미설정(None)이면 코드 기본값으로 폴백 — 기존 동작과 byte-identical
        self.prompt_template = prompt_template or self.DEFAULT_PROMPT_TEMPLATE

        # reasoning_effort를 OpenAI API effort 값으로 매핑
        self._effort_mapping = {"minimal": "low", "standard": "medium", "high": "high"}
        self._api_effort = self._effort_mapping.get(reasoning_effort, "low")

        # 통계 추적
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_processing_time": 0.0,
            "total_tokens_used": 0,
        }

        logger.info(
            "openai_llm_reranker_initialized",
            model=model,
            max_documents=max_documents,
            timeout=timeout,
            verbosity=verbosity,
            reasoning_effort=reasoning_effort,
        )

    async def rerank(
        self, query: str, results: list[SearchResult], top_k: int | None = None
    ) -> list[SearchResult]:
        """
        OpenAI LLM으로 검색 결과 리랭킹

        Args:
            query: 원본 사용자 쿼리
            results: 검색 결과 리스트
            top_k: 반환할 상위 결과 개수

        Returns:
            List[SearchResult]: 리랭킹된 결과 (상위 top_k개)
        """
        if not results:
            return []

        # top_k 기본값 처리 (IReranker 인터페이스와 일치)
        if top_k is None:
            top_k = 15

        start_time = time.time()
        self._stats["total_requests"] += 1

        try:
            # 처리할 문서 개수 제한
            process_count = min(len(results), self.max_documents)

            # 문서 텍스트 생성 (250자 프리뷰)
            documents_text = ""
            for i, result in enumerate(results[:process_count]):
                content_preview = result.content[:250].replace("\n", " ").strip()
                documents_text += f"\n[{i}] {content_preview}..."

            logger.debug(
                "openai_llm_reranking_started",
                model=self.model,
                process_count=process_count,
                top_k=top_k,
            )

            # OpenAI LLM 프롬프트 (config 오버라이드 가능, 기본값은 코드 내장)
            prompt = self.prompt_template.format(
                query=query,
                documents_text=documents_text,
                top_k=top_k,
            )

            # input 텍스트 구성
            input_text = f"""System: You are a fast document ranking specialist. Focus on speed and accuracy.

User: {prompt}"""

            # OpenAI responses API 호출
            response = cast(
                Any,
                await asyncio.to_thread(
                    self.client.responses.create,  # type: ignore[arg-type]
                    model=self.model,
                    input=input_text,
                    reasoning={"effort": self._api_effort},
                    text={"verbosity": self.verbosity},
                ),
            )

            # 응답 처리
            processing_time = time.time() - start_time
            reranked_results = self._parse_response(response, results, top_k)

            # 통계 업데이트
            self._stats["successful_requests"] += 1
            self._stats["total_processing_time"] += processing_time
            if hasattr(response, "usage") and response.usage:
                self._stats["total_tokens_used"] += response.usage.total_tokens

            logger.info(
                "openai_llm_reranking_completed",
                model=self.model,
                original_count=len(results),
                reranked_count=len(reranked_results),
                processing_time=f"{processing_time:.3f}s",
                tokens_used=(
                    getattr(response.usage, "total_tokens", "unknown")
                    if hasattr(response, "usage")
                    else "unknown"
                ),
            )

            return reranked_results

        except Exception as e:
            self._stats["failed_requests"] += 1
            logger.error(
                "openai_llm_reranking_failed",
                model=self.model,
                error=str(e),
                query=query[:100],
                result_count=len(results),
            )

            # Fallback: 원본 결과 점수순 정렬 후 top_k 반환
            results.sort(key=lambda x: x.score, reverse=True)
            return results[:top_k]

    def supports_caching(self) -> bool:
        """OpenAI LLM 리랭커는 캐싱을 지원하지 않음"""
        return False

    def _parse_response(
        self, response: Any, original_results: list[SearchResult], top_k: int
    ) -> list[SearchResult]:
        """
        OpenAI LLM 응답 파싱 (3단계 fallback)

        Args:
            response: OpenAI API 응답 객체
            original_results: 원본 검색 결과
            top_k: 반환할 상위 결과 개수

        Returns:
            List[SearchResult]: 파싱된 리랭킹 결과
        """
        response_content = response.output_text
        if not response_content:
            logger.warning("openai_llm_empty_response", model=self.model)
            original_results.sort(key=lambda x: x.score, reverse=True)
            return original_results[:top_k]

        response_content = response_content.strip()
        logger.debug("openai_llm_raw_response", response=response_content[:500])

        # 1단계: 전체 응답을 JSON으로 파싱 시도
        try:
            rerank_data = json.loads(response_content)
            logger.debug("json_parse_success", method="direct")
            return self._build_reranked_results(rerank_data, original_results, top_k)
        except json.JSONDecodeError:
            pass

        # 2단계: JSON 코드 블록 추출 시도
        json_match = re.search(r"\{.*\}", response_content, re.DOTALL)
        if json_match:
            try:
                rerank_data = json.loads(json_match.group())
                logger.debug("json_parse_success", method="regex_extraction")
                return self._build_reranked_results(rerank_data, original_results, top_k)
            except json.JSONDecodeError as je:
                logger.error(
                    "json_parse_failed_after_extraction",
                    error=str(je),
                    extracted_text=json_match.group()[:500],
                )

        # 3단계: Fallback - 원본 결과 반환
        logger.warning("json_parse_failed_all_methods", response=response_content[:500])
        original_results.sort(key=lambda x: x.score, reverse=True)
        return original_results[:top_k]

    def _build_reranked_results(
        self, rerank_data: dict[str, Any], original_results: list[SearchResult], top_k: int
    ) -> list[SearchResult]:
        """
        JSON 데이터로부터 리랭킹된 SearchResult 리스트 생성

        Args:
            rerank_data: 파싱된 JSON 데이터
            original_results: 원본 검색 결과
            top_k: 반환할 상위 결과 개수

        Returns:
            List[SearchResult]: 리랭킹된 결과
        """
        reranked_results = []

        for item in rerank_data.get("results", [])[:top_k]:
            idx = item.get("index", 0)
            score = max(0.0, min(1.0, float(item.get("score", 0.5))))  # 0~1 범위 제한

            if 0 <= idx < len(original_results):
                original_result = original_results[idx]
                reranked_result = SearchResult(
                    id=original_result.id,
                    content=original_result.content,
                    score=score,
                    metadata={
                        **original_result.metadata,
                        "rerank_method": f"openai-llm:{self.model}",
                        "original_score": original_result.score,
                    },
                )
                reranked_results.append(reranked_result)

                # 개선도 로깅
                improvement = score - original_result.score
                logger.debug(
                    "reranked_document",
                    index=idx,
                    original_score=f"{original_result.score:.3f}",
                    new_score=f"{score:.3f}",
                    improvement=f"{improvement:+.3f}",
                )

        # 점수순 정렬
        reranked_results.sort(key=lambda x: x.score, reverse=True)

        # 상위 결과 개선도 요약
        for i, result in enumerate(reranked_results[:3]):
            original_score = result.metadata.get("original_score", 0)
            improvement = result.score - original_score
            logger.debug(
                "top_result_summary",
                rank=i + 1,
                original_score=f"{original_score:.3f}",
                new_score=f"{result.score:.3f}",
                improvement=f"{improvement:+.3f}",
            )

        return reranked_results if reranked_results else original_results[:top_k]

    def get_stats(self) -> dict[str, Any]:
        """
        Reranker 통계 정보 반환

        Returns:
            Dict: 통계 정보
        """
        total_requests = self._stats["total_requests"]
        success_rate = (
            self._stats["successful_requests"] / total_requests if total_requests > 0 else 0.0
        )
        avg_processing_time = (
            self._stats["total_processing_time"] / self._stats["successful_requests"]
            if self._stats["successful_requests"] > 0
            else 0.0
        )

        return {
            "provider": "openai-llm",
            "model": self.model,
            "total_requests": total_requests,
            "successful_requests": self._stats["successful_requests"],
            "failed_requests": self._stats["failed_requests"],
            "success_rate": success_rate,
            "total_tokens_used": self._stats["total_tokens_used"],
            "avg_processing_time": avg_processing_time,
        }

    async def health_check(self) -> bool:
        """
        Reranker 상태 확인

        Returns:
            bool: 정상 동작 여부
        """
        try:
            # 간단한 테스트 리랭킹 수행
            test_results = [
                SearchResult(
                    id="test_1",
                    content="This is a test document about Python programming.",
                    score=0.8,
                    metadata={},
                ),
                SearchResult(
                    id="test_2",
                    content="Another test document about machine learning.",
                    score=0.7,
                    metadata={},
                ),
            ]

            reranked = await self.rerank(query="Python programming", results=test_results, top_k=2)

            # 리랭킹 성공 및 결과 존재 확인
            return len(reranked) > 0

        except Exception as e:
            logger.error("health_check_failed", model=self.model, error=str(e))
            return False
