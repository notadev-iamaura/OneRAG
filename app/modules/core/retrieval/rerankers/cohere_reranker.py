"""
Cohere Rerank API 기반 리랭커

Cohere의 Rerank API를 사용한 고품질 리랭킹.
100+ 언어 지원, 4096 토큰 컨텍스트.

지원 모델:
- rerank-v3.5 (최신, 권장)
- rerank-multilingual-v3.0 (기본값)
- rerank-english-v3.0 (영어 특화)

참고: https://docs.cohere.com/reference/rerank
"""

from typing import Any

import httpx

from .....lib.logger import get_logger
from ..interfaces import SearchResult

logger = get_logger(__name__)


class CohereReranker:
    """
    Cohere Rerank API 기반 리랭커

    특징:
    - HTTP API를 통한 리랭킹
    - 100+ 언어 지원 (multilingual 모델)
    - 4096 토큰 컨텍스트
    - Graceful Fallback (오류 시 원본 반환)
    """

    def __init__(
        self,
        api_key: str,
        model: str = "rerank-multilingual-v3.0",
        endpoint: str = "https://api.cohere.com/v2/rerank",
        timeout: float = 30.0,
        max_tokens_per_doc: int = 4096,
    ):
        """
        CohereReranker 초기화

        Args:
            api_key: Cohere API 키
            model: 사용할 Cohere Rerank 모델
            endpoint: Cohere API 엔드포인트 URL
            timeout: HTTP 요청 타임아웃 (초)
            max_tokens_per_doc: 문서당 최대 토큰 수
        """
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self.timeout = timeout
        self.max_tokens_per_doc = max_tokens_per_doc

        # ✅ httpx AsyncClient를 1회 생성하여 재사용 (TCP/TLS 핸드셰이크 반복 방지)
        # httpx.AsyncClient() 생성자는 동기이므로 __init__에서 생성 가능
        self._client = httpx.AsyncClient(timeout=timeout)

        # 통계 추적
        self.stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
        }

        logger.info(f"CohereReranker 초기화: model={model}, endpoint={endpoint}")

    async def initialize(self) -> None:
        """리랭커 초기화 (Cohere는 HTTP API이므로 추가 초기화 불필요)"""
        logger.debug("CohereReranker 초기화 완료 (HTTP API 사용)")

    async def close(self) -> None:
        """리소스 정리 (재사용 중인 httpx AsyncClient 종료)"""
        await self._client.aclose()
        logger.info("CohereReranker 종료 완료")

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_n: int | None = None,
    ) -> list[SearchResult]:
        """
        검색 결과 리랭킹 (Cohere Rerank API 사용)

        Args:
            query: 사용자 쿼리
            results: 원본 검색 결과
            top_n: 리랭킹 후 반환할 최대 결과 수 (None이면 전체)

        Returns:
            리랭킹된 검색 결과 (스코어가 업데이트됨)
        """
        if not results:
            logger.warning("리랭킹할 결과가 없습니다")
            return []

        self.stats["total_requests"] += 1

        # top_n이 None이면 전체 결과 수 사용
        effective_top_n = top_n if top_n is not None else len(results)

        try:
            # 문서 리스트 생성
            documents = [result.content for result in results]

            # HTTP 요청 데이터 구성 (Cohere Rerank API v2 형식)
            request_data = {
                "model": self.model,
                "query": query,
                "documents": documents,
                "top_n": min(effective_top_n, len(documents)),
                "max_tokens_per_doc": self.max_tokens_per_doc,
            }

            # HTTP 헤더 구성
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }

            logger.debug(
                f"Cohere 리랭킹 요청: query='{query[:50]}...', "
                f"documents={len(documents)}, top_n={request_data['top_n']}"
            )

            # HTTP 요청 실행 (재사용 클라이언트 사용, asyncio + httpx)
            response = await self._client.post(
                self.endpoint,
                json=request_data,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()

            rerank_response = response.json()

            # 결과 재구성 (새 SearchResult 객체 생성, 불변성 유지)
            reranked_results = []
            for rank_result in rerank_response["results"]:
                original_idx = rank_result["index"]
                original_result = results[original_idx]

                # Cohere relevance_score를 새 SearchResult에 적용
                reranked_results.append(
                    SearchResult(
                        id=original_result.id,
                        content=original_result.content,
                        score=rank_result["relevance_score"],
                        metadata=original_result.metadata,
                    )
                )

            self.stats["successful_requests"] += 1
            logger.info(
                f"Cohere 리랭킹 완료: {len(results)} -> {len(reranked_results)}개 결과 반환"
            )

            return reranked_results

        except httpx.HTTPStatusError as e:
            self.stats["failed_requests"] += 1
            logger.error(
                f"Cohere API HTTP 에러: {e.response.status_code} - {e.response.text}"
            )
            return results  # 실패 시 원본 결과 반환

        except httpx.TimeoutException:
            self.stats["failed_requests"] += 1
            logger.error(f"Cohere API 타임아웃 (timeout={self.timeout}s)")
            return results  # 실패 시 원본 결과 반환

        except Exception as e:
            self.stats["failed_requests"] += 1
            logger.error(f"Cohere 리랭킹 실패: {e}")
            return results  # 실패 시 원본 결과 반환

    def supports_caching(self) -> bool:
        """
        캐싱 지원 여부 반환 (IReranker 인터페이스 구현)

        Cohere API는 결정론적(deterministic)이므로 캐싱 가능

        Returns:
            True (캐싱 지원)
        """
        return True

    def get_stats(self) -> dict[str, Any]:
        """
        리랭커 통계 반환

        Returns:
            통계 정보 딕셔너리 (총 요청 수, 성공/실패 수, 성공률, 모델, 엔드포인트)
        """
        total = self.stats["total_requests"]
        success_rate = (
            self.stats["successful_requests"] / total * 100 if total > 0 else 0.0
        )

        return {
            "total_requests": self.stats["total_requests"],
            "successful_requests": self.stats["successful_requests"],
            "failed_requests": self.stats["failed_requests"],
            "success_rate": round(success_rate, 2),
            "model": self.model,
            "endpoint": self.endpoint,
        }
