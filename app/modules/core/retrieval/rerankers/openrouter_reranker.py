"""
OpenRouter LLM 기반 리랭커

OpenRouter API를 통해 다양한 LLM 모델로 리랭킹 수행.
지원 모델: google/gemini-2.5-flash-lite, anthropic/claude-3-haiku 등

참고: https://openrouter.ai/docs
"""

import json
import re
import time
from typing import Any

import httpx

from .....lib.logger import get_logger
from ..interfaces import IReranker, SearchResult

logger = get_logger(__name__)


class OpenRouterReranker(IReranker):
    """
    OpenRouter API 기반 LLM 리랭커

    특징:
    - 다양한 LLM 모델 지원 (Gemini, Claude, GPT 등)
    - httpx 비동기 HTTP 호출
    - JSON 형식 응답 파싱
    - Graceful Fallback (오류 시 원본 반환)
    """

    def __init__(
        self,
        api_key: str,
        model: str = "google/gemini-2.5-flash-lite",
        max_documents: int = 20,
        timeout: int = 15,
    ):
        """
        Args:
            api_key: OpenRouter API 키
            model: 사용할 모델 (provider/model 형식)
            max_documents: 처리할 최대 문서 개수
            timeout: 타임아웃 (초)
        """
        if not api_key:
            raise ValueError("OpenRouter API key is required")

        self.api_key = api_key
        self.model = model
        self.max_documents = max_documents
        self.timeout = timeout

        # httpx AsyncClient 생성
        self.http_client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            timeout=httpx.Timeout(timeout, connect=5.0),
        )

        # 통계 추적
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_processing_time": 0.0,
        }

        logger.info(f"OpenRouterReranker 초기화: model={model}")

    async def initialize(self) -> None:
        """리랭커 초기화 (HTTP API이므로 추가 초기화 불필요)"""
        logger.debug("OpenRouterReranker 초기화 완료")

    async def close(self) -> None:
        """리소스 정리"""
        await self.http_client.aclose()
        logger.info("OpenRouterReranker 종료 완료")

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_n: int | None = None,
    ) -> list[SearchResult]:
        """
        검색 결과 리랭킹

        Args:
            query: 사용자 쿼리
            results: 원본 검색 결과
            top_n: 반환할 최대 결과 수 (None이면 전체)

        Returns:
            리랭킹된 검색 결과
        """
        if not results:
            logger.warning("리랭킹할 결과가 없습니다")
            return []

        self._stats["total_requests"] += 1
        start_time = time.time()

        # 문서 수 제한
        documents = results[: self.max_documents]

        try:
            # 프롬프트 구성
            prompt = self._build_prompt(query, documents)

            # API 요청
            response = await self.http_client.post(
                "/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,  # 결정론적 응답
                },
            )
            response.raise_for_status()
            response_data = response.json()

            # 응답 파싱
            content = response_data["choices"][0]["message"]["content"]
            rankings = self._parse_rankings(content, len(documents))

            # 결과 재구성
            reranked = self._apply_rankings(documents, rankings)

            # top_n 적용
            if top_n is not None:
                reranked = reranked[:top_n]

            self._stats["successful_requests"] += 1
            self._stats["total_processing_time"] += time.time() - start_time

            logger.info(
                f"OpenRouter 리랭킹 완료: {len(results)} -> {len(reranked)}개 반환"
            )
            return reranked

        except httpx.TimeoutException:
            self._stats["failed_requests"] += 1
            logger.error(f"OpenRouter API 타임아웃 (timeout={self.timeout}s)")
            return results

        except httpx.HTTPStatusError as e:
            self._stats["failed_requests"] += 1
            logger.error(f"OpenRouter API HTTP 에러: {e.response.status_code}")
            return results

        except Exception as e:
            self._stats["failed_requests"] += 1
            logger.error(f"OpenRouter 리랭킹 실패: {e}")
            return results

    def _build_prompt(self, query: str, documents: list[SearchResult]) -> str:
        """리랭킹 프롬프트 생성"""
        docs_text = "\n".join(
            f"[{i}] {doc.content[:500]}" for i, doc in enumerate(documents)
        )

        return f"""다음 문서들을 쿼리와의 관련성에 따라 순위를 매겨주세요.

쿼리: {query}

문서들:
{docs_text}

JSON 형식으로 응답해주세요:
{{"rankings": [{{"index": 문서번호, "score": 0.0-1.0 점수}}]}}

점수가 높은 순서대로 정렬하여 응답해주세요."""

    def _parse_rankings(
        self, content: str, num_docs: int
    ) -> list[dict[str, Any]]:
        """응답에서 rankings 파싱"""
        try:
            # JSON 추출 시도
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if "rankings" in data:
                    rankings: list[dict[str, Any]] = data["rankings"]
                    return rankings
        except json.JSONDecodeError:
            pass

        # 파싱 실패 시 기본 순위 반환
        logger.warning("Rankings 파싱 실패, 기본 순위 사용")
        return [{"index": i, "score": 1.0 - (i * 0.1)} for i in range(num_docs)]

    def _apply_rankings(
        self, documents: list[SearchResult], rankings: list[dict[str, Any]]
    ) -> list[SearchResult]:
        """rankings를 적용하여 결과 재구성"""
        reranked = []
        for rank in rankings:
            idx = rank.get("index", 0)
            score = rank.get("score", 0.5)

            if 0 <= idx < len(documents):
                doc = documents[idx]
                reranked.append(
                    SearchResult(
                        id=doc.id,
                        content=doc.content,
                        score=float(score),
                        metadata=doc.metadata,
                    )
                )

        # 누락된 문서 추가
        included_ids = {r.id for r in reranked}
        for doc in documents:
            if doc.id not in included_ids:
                reranked.append(doc)

        return reranked

    def supports_caching(self) -> bool:
        """캐싱 지원 여부"""
        return True

    def get_stats(self) -> dict[str, Any]:
        """통계 반환"""
        total = self._stats["total_requests"]
        success_rate = (
            self._stats["successful_requests"] / total * 100 if total > 0 else 0.0
        )

        return {
            "total_requests": self._stats["total_requests"],
            "successful_requests": self._stats["successful_requests"],
            "failed_requests": self._stats["failed_requests"],
            "success_rate": round(success_rate, 2),
            "model": self.model,
            "avg_processing_time": (
                round(self._stats["total_processing_time"] / total, 3)
                if total > 0
                else 0.0
            ),
        }
