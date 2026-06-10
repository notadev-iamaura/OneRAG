"""
Jina ColBERT v2 Reranker - 토큰 수준 Late Interaction 리랭킹

Jina ColBERT v2 API를 사용한 고품질 리랭킹.
ColBERT의 Late Interaction 방식은 쿼리와 문서의 토큰별 유사도를 계산하여
더 정교한 관련성 점수를 제공합니다.

특징:
- 토큰 수준 Late Interaction으로 정교한 관련성 평가
- 기존 Jina Reranker보다 높은 정확도
- Graceful Fallback (오류 시 원본 반환)
- 결정론적 결과로 캐싱 지원

구현일: 2025-12-31
"""

from dataclasses import dataclass
from typing import Any

import httpx

from .....lib.logger import get_logger
from ..interfaces import SearchResult

logger = get_logger(__name__)


# ========================================
# 설정 스키마
# ========================================


@dataclass
class ColBERTRerankerConfig:
    """
    ColBERT 리랭커 설정

    Attributes:
        enabled: 리랭커 활성화 여부
        api_key: Jina AI API 키
        model: 사용할 ColBERT 모델 (jina-colbert-v2 권장)
        endpoint: API 엔드포인트 URL
        timeout: HTTP 요청 타임아웃 (초)
        max_documents: 리랭킹할 최대 문서 수
    """

    enabled: bool = True
    api_key: str = ""
    model: str = "jina-colbert-v2"
    endpoint: str = "https://api.jina.ai/v1/rerank"
    timeout: int = 10
    max_documents: int = 20

    def __post_init__(self) -> None:
        """설정값 검증"""
        if self.enabled and not self.api_key:
            raise ValueError("api_key is required when enabled is True")
        if self.timeout <= 0:
            raise ValueError(f"timeout must be positive, got {self.timeout}")
        if self.max_documents <= 0:
            raise ValueError(f"max_documents must be positive, got {self.max_documents}")


# ========================================
# ColBERT 리랭커
# ========================================


class JinaColBERTReranker:
    """
    Jina ColBERT v2 API 기반 리랭커

    특징:
    - HTTP API를 통한 ColBERT 리랭킹
    - 토큰 수준 Late Interaction으로 높은 정확도
    - Graceful Fallback (오류 시 원본 반환)
    - 결정론적 결과로 캐싱 지원
    """

    def __init__(self, config: ColBERTRerankerConfig):
        """
        Args:
            config: ColBERT 리랭커 설정
        """
        self.config = config
        self.name = "colbert"
        self.enabled = config.enabled

        # ✅ httpx AsyncClient를 1회 생성하여 재사용 (TCP/TLS 핸드셰이크 반복 방지)
        # httpx.AsyncClient() 생성자는 동기이므로 __init__에서 생성 가능
        self._client = httpx.AsyncClient(timeout=config.timeout)

        # 통계
        self._stats = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
        }

        if config.enabled:
            logger.info(
                f"JinaColBERTReranker 초기화: model={config.model}, "
                f"timeout={config.timeout}s, max_documents={config.max_documents}"
            )

    async def close(self) -> None:
        """리소스 정리 (재사용 중인 httpx AsyncClient 종료)"""
        await self._client.aclose()
        logger.info("JinaColBERTReranker 종료 완료")

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_n: int | None = None,
    ) -> list[SearchResult]:
        """
        검색 결과 리랭킹 (Jina ColBERT v2 API 사용)

        Args:
            query: 사용자 쿼리
            results: 원본 검색 결과
            top_n: 반환할 상위 N개 결과 (None이면 전체)

        Returns:
            리랭킹된 검색 결과 (점수 내림차순)
        """
        # 비활성화 상태면 원본 반환
        if not self.config.enabled:
            return results

        # 빈 결과 처리
        if not results:
            return []

        # 단일 결과는 API 호출 스킵 (최적화)
        if len(results) == 1:
            return results

        self._stats["total_calls"] += 1

        try:
            # API 요청
            reranked = await self._call_api(query, results)

            # top_n 적용
            if top_n is not None:
                reranked = reranked[:top_n]

            self._stats["successful_calls"] += 1
            logger.info(
                f"ColBERT 리랭킹 완료: {len(results)} -> {len(reranked)}개"
            )
            return reranked

        except Exception as e:
            self._stats["failed_calls"] += 1
            logger.warning(f"ColBERT 리랭킹 실패, 원본 반환: {e}")
            return results

    async def _call_api(
        self,
        query: str,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """
        Jina ColBERT API 호출

        Args:
            query: 검색 쿼리
            results: 리랭킹할 검색 결과

        Returns:
            리랭킹된 결과 (점수 순)

        Raises:
            Exception: API 호출 실패 시
        """
        # 문서 리스트 생성 (max_documents 제한)
        documents = [r.content for r in results[: self.config.max_documents]]

        # API 요청 데이터
        request_data = {
            "model": self.config.model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        }

        # HTTP 헤더
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }

        logger.debug(
            f"ColBERT API 요청: query='{query[:50]}...', "
            f"documents={len(documents)}"
        )

        # HTTP 요청 실행 (재사용 클라이언트 사용)
        response = await self._client.post(
            self.config.endpoint,
            json=request_data,
            headers=headers,
            timeout=self.config.timeout,
        )

        # 응답 상태 확인
        if response.status_code != 200:
            raise Exception(
                f"API error: {response.status_code} - {response.text}"
            )

        # JSON 파싱
        response_data = response.json()

        # 결과 재구성
        reranked_results: list[SearchResult] = []
        for rank_result in response_data.get("results", []):
            idx = rank_result["index"]
            score = rank_result["relevance_score"]

            # 인덱스 범위 체크
            if 0 <= idx < len(results):
                original = results[idx]
                # 새 점수로 SearchResult 생성
                reranked_results.append(
                    SearchResult(
                        id=original.id,
                        content=original.content,
                        score=score,
                        metadata=original.metadata,
                    )
                )

        # 점수 내림차순 정렬
        reranked_results.sort(key=lambda x: x.score, reverse=True)

        return reranked_results

    def supports_caching(self) -> bool:
        """
        캐싱 지원 여부 반환

        ColBERT는 결정론적(deterministic)이므로 캐싱 가능.

        Returns:
            True (캐싱 지원)
        """
        return True

    def get_stats(self) -> dict[str, Any]:
        """
        리랭커 통계 반환

        Returns:
            호출 통계 딕셔너리
        """
        total = self._stats["total_calls"]
        success_rate = (
            self._stats["successful_calls"] / total * 100 if total > 0 else 0.0
        )

        return {
            "total_calls": self._stats["total_calls"],
            "successful_calls": self._stats["successful_calls"],
            "failed_calls": self._stats["failed_calls"],
            "success_rate": round(success_rate, 2),
            "model": self.config.model,
            "enabled": self.config.enabled,
        }
