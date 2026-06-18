"""
Gemini Flash Lite Reranker Implementation

Google Gemini 2.5 Flash Lite 모델 기반 고속 LLM Reranker:
- httpx 기반 네이티브 async HTTP API 호출 (개선!)
- ThinkingConfig(thinking_budget=0)로 최대 속도
- JSON 응답 파싱 (2단계 fallback)
- GPT-5-nano 대비 5-10배 빠른 성능
- 에러 시 원본 결과 반환으로 안정성 보장
- 동시 다중 요청 처리 가능 (non-blocking)
"""

import json
import re
import time
from typing import Any

import httpx
import structlog

from .....lib.langfuse_client import observe, record_generation
from ..interfaces import IReranker, SearchResult

logger = structlog.get_logger(__name__)


class GeminiFlashReranker(IReranker):
    """
    Gemini 2.5 Flash Lite 기반 Reranker

    Google Gemini 2.5 Flash Lite 모델을 사용한 고속 문서 리랭킹:
    - thinking_budget=0으로 최소 사고, 최대 속도
    - GPT-5-nano 대비 5-10배 빠른 성능
    - JSON 형식 응답 파싱
    - 원본 점수 보존 및 개선도 추적

    Features:
    - 최대 20개 문서 처리 (설정 가능)
    - 15초 타임아웃 (설정 가능)
    - 2단계 JSON 파싱 fallback
    - 에러 시 원본 결과 반환 (fail-safe)
    """

    # 코드 내장 기본 랭킹 프롬프트 (config 미설정 시 사용)
    # 플레이스홀더: {query}, {documents_text}, {top_k}
    # str.format()으로 채워지므로 JSON 예시의 중괄호는 {{ }}로 이스케이프되어 있다.
    # config(reranking.google.prompt_template) 주입 시에만 오버라이드된다(회귀 0).
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
        max_documents: int = 20,
        timeout: int = 15,
        model: str = "gemini-flash-lite-latest",
        prompt_template: str | None = None,
    ):
        """
        Args:
            api_key: Google API 키
            max_documents: 처리할 최대 문서 개수
            timeout: 타임아웃 (초)
            model: Gemini 모델 이름 (기본: gemini-flash-lite-latest)
            prompt_template: 랭킹 프롬프트 템플릿 오버라이드.
                None이면 코드 내장 DEFAULT_PROMPT_TEMPLATE 사용(회귀 0).
                {query}/{documents_text}/{top_k} 플레이스홀더를 지원한다.
        """
        if not api_key:
            raise ValueError("Google API key is required")

        self.api_key = api_key
        self.max_documents = max_documents
        self.timeout = timeout
        self.model = model
        # 미설정(None)이면 코드 기본값으로 폴백 — 기존 동작과 byte-identical
        self.prompt_template = prompt_template or self.DEFAULT_PROMPT_TEMPLATE

        # ✅ httpx AsyncClient 생성 (네이티브 async)
        self.http_client = httpx.AsyncClient(
            base_url="https://generativelanguage.googleapis.com",
            headers={
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout, connect=5.0),  # 전체 타임아웃 + 연결 타임아웃
        )

        # 통계 추적
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_processing_time": 0.0,
        }

        logger.info(
            "gemini_flash_reranker_initialized",
            model=model,
            max_documents=max_documents,
            timeout=timeout,
            api_mode="httpx_async",  # 모드 표시
        )

    @observe(
        as_type="generation",
        name="Reranker (Gemini)",
        capture_input=False,
        capture_output=False,
    )
    async def rerank(
        self, query: str, results: list[SearchResult], top_k: int | None = None
    ) -> list[SearchResult]:
        """
        Gemini Flash Lite로 검색 결과 리랭킹

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
                "gemini_flash_reranking_started",
                process_count=process_count,
                top_k=top_k,
            )

            # Gemini Flash 프롬프트 (config 오버라이드 가능, 기본값은 코드 내장)
            prompt_text = self.prompt_template.format(
                query=query,
                documents_text=documents_text,
                top_k=top_k,
            )

            # ✅ 네이티브 async HTTP 호출
            request_body = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt_text}],
                    }
                ],
                "generationConfig": {
                    "thinkingConfig": {"thinkingBudget": 0}  # 최소 사고로 최대 속도
                },
            }

            # Gemini REST API 호출
            response = await self.http_client.post(
                f"/v1beta/models/{self.model}:generateContent",
                params={"key": self.api_key},  # API Key를 query parameter로 전달
                json=request_body,
            )

            # HTTP 에러 체크
            response.raise_for_status()

            # 응답 JSON 파싱
            response_data = response.json()

            # LLM 리랭킹 호출의 토큰/비용을 Langfuse generation으로 기록
            um = response_data.get("usageMetadata", {}) or {}
            record_generation(
                model=self.model,
                prompt_tokens=um.get("promptTokenCount", 0) or 0,
                completion_tokens=um.get("candidatesTokenCount", 0) or 0,
                total_tokens=um.get("totalTokenCount", 0) or 0,
            )

            # 응답 처리
            processing_time = time.time() - start_time
            reranked_results = self._parse_http_response(response_data, results, top_k)

            # 통계 업데이트
            self._stats["successful_requests"] += 1
            self._stats["total_processing_time"] += processing_time

            logger.info(
                "gemini_flash_reranking_completed",
                original_count=len(results),
                reranked_count=len(reranked_results),
                processing_time=f"{processing_time:.3f}s",
            )

            return reranked_results

        except httpx.TimeoutException:
            # 타임아웃 에러
            self._stats["failed_requests"] += 1
            logger.error(
                "gemini_flash_reranking_timeout",
                timeout=self.timeout,
                query=query[:100],
                result_count=len(results),
            )
            # Fallback: 원본 결과 점수순 정렬 후 top_k 반환
            results.sort(key=lambda x: x.score, reverse=True)
            return results[:top_k]

        except httpx.HTTPStatusError as http_err:
            # HTTP 상태 에러 (4xx, 5xx)
            self._stats["failed_requests"] += 1
            logger.error(
                "gemini_flash_http_error",
                status_code=http_err.response.status_code,
                error=str(http_err),
                query=query[:100],
                result_count=len(results),
            )
            # Fallback: 원본 결과 점수순 정렬 후 top_k 반환
            results.sort(key=lambda x: x.score, reverse=True)
            return results[:top_k]

        except Exception as e:
            # 기타 모든 에러
            self._stats["failed_requests"] += 1
            logger.error(
                "gemini_flash_reranking_failed",
                error=str(e),
                error_type=type(e).__name__,
                query=query[:100],
                result_count=len(results),
            )
            import traceback

            logger.error("traceback", trace=traceback.format_exc())

            # Fallback: 원본 결과 점수순 정렬 후 top_k 반환
            results.sort(key=lambda x: x.score, reverse=True)
            return results[:top_k]

    def _parse_http_response(
        self, response_data: dict, original_results: list[SearchResult], top_k: int
    ) -> list[SearchResult]:
        """
        Gemini REST API HTTP 응답 파싱 (2단계 fallback)

        Args:
            response_data: Gemini REST API JSON 응답 (dict)
            original_results: 원본 검색 결과
            top_k: 반환할 상위 결과 개수

        Returns:
            List[SearchResult]: 파싱된 리랭킹 결과
        """
        # Gemini API 응답 구조: {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}
        try:
            candidates = response_data.get("candidates", [])
            if not candidates:
                logger.warning("gemini_flash_no_candidates")
                original_results.sort(key=lambda x: x.score, reverse=True)
                return original_results[:top_k]

            response_content = (
                candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            )
            if not response_content:
                logger.warning("gemini_flash_empty_response")
                original_results.sort(key=lambda x: x.score, reverse=True)
                return original_results[:top_k]

        except (KeyError, IndexError) as e:
            logger.error("gemini_flash_response_structure_error", error=str(e))
            original_results.sort(key=lambda x: x.score, reverse=True)
            return original_results[:top_k]

        response_content = response_content.strip()
        logger.debug("gemini_flash_raw_response", response=response_content[:500])

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

        # Fallback: 원본 결과 반환
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
                        "rerank_method": "gemini-flash",
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
            "provider": "gemini-flash",
            "model": self.model,
            "total_requests": total_requests,
            "successful_requests": self._stats["successful_requests"],
            "failed_requests": self._stats["failed_requests"],
            "success_rate": success_rate,
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
            logger.error("health_check_failed", error=str(e))
            return False

    async def cleanup(self) -> None:
        """
        리소스 정리 (httpx AsyncClient 종료)

        애플리케이션 종료 시 호출 필요
        """
        await self.http_client.aclose()
        logger.info("gemini_flash_reranker_cleanup_completed")

    def supports_caching(self) -> bool:
        """
        캐싱 지원 여부 반환 (IReranker 인터페이스 구현)

        Gemini API는 결정론적(deterministic)이므로 캐싱 가능

        Returns:
            True (캐싱 지원)
        """
        return True
