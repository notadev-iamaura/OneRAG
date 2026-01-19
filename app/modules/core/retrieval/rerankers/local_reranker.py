"""
로컬 CrossEncoder 기반 리랭커

sentence-transformers의 CrossEncoder를 사용한 로컬 리랭킹.
API 키 불필요, 오프라인 사용 가능.

선택적 의존성: uv sync --extra local-reranker

지원 모델:
- cross-encoder/ms-marco-MiniLM-L-12-v2 (기본값, 130MB, 정확)
- cross-encoder/ms-marco-MiniLM-L-6-v2 (90MB, 빠름)

참고: https://www.sbert.net/docs/pretrained-models/ce-msmarco.html
"""

from typing import Any

import numpy as np
import torch

from .....lib.logger import get_logger
from ..interfaces import SearchResult

logger = get_logger(__name__)


# 선택적 의존성 체크
try:
    from sentence_transformers import CrossEncoder

    HAS_CROSS_ENCODER = True
except ImportError:
    HAS_CROSS_ENCODER = False
    CrossEncoder = None  # type: ignore


class LocalReranker:
    """
    로컬 CrossEncoder 기반 리랭커

    특징:
    - API 키 불필요 (로컬 실행)
    - 오프라인 사용 가능
    - 빠른 추론 속도 (MiniLM 모델)
    - Graceful Fallback (오류 시 원본 반환)

    주의:
    - 선택적 의존성: uv sync --extra local-reranker 필요
    - 첫 실행 시 모델 다운로드 (~90MB)
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-12-v2",
        device: str | None = None,
        batch_size: int = 32,
    ):
        """
        Args:
            model_name: 사용할 CrossEncoder 모델명
            device: 실행 디바이스 (None이면 자동 감지)
            batch_size: 배치 처리 크기

        Raises:
            ImportError: sentence-transformers가 설치되지 않은 경우
        """
        if not HAS_CROSS_ENCODER:
            raise ImportError(
                "LocalReranker를 사용하려면 sentence-transformers가 필요합니다. "
                "설치: uv sync --extra local-reranker"
            )

        self.model_name = model_name
        self.batch_size = batch_size

        # 디바이스 설정
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device

        # 모델은 initialize()에서 로드
        self._model = None

        # 통계
        self.stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
        }

        logger.info(f"LocalReranker 초기화: model={model_name}, device={device}")

    async def initialize(self) -> None:
        """리랭커 초기화 (모델 로드)"""
        if self._model is None:
            logger.info(f"LocalReranker 모델 로드 중: {self.model_name}")
            self._model = CrossEncoder(
                self.model_name,
                max_length=512,
                device=self.device,
            )
            logger.info("LocalReranker 모델 로드 완료")

    async def close(self) -> None:
        """리소스 정리"""
        self._model = None
        logger.info("LocalReranker 리소스 정리 완료")

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_n: int | None = None,
    ) -> list[SearchResult]:
        """
        검색 결과 리랭킹 (로컬 CrossEncoder 사용)

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

        # 모델이 로드되지 않았으면 로드
        if self._model is None:
            await self.initialize()

        # mypy 타입 보장 (initialize 후 _model은 반드시 존재)
        assert self._model is not None

        self.stats["total_requests"] += 1

        try:
            # 쿼리-문서 쌍 생성
            pairs = [(query, result.content) for result in results]

            # CrossEncoder 추론 (동기 함수이므로 직접 호출)
            # 원시 logit 점수 획득 (activation 없이)
            raw_scores = self._model.predict(
                pairs,
                batch_size=self.batch_size,
            )

            # NumPy Sigmoid 적용 (0-1 범위 정규화)
            # sigmoid(x) = 1 / (1 + exp(-x))
            scores = 1 / (1 + np.exp(-np.asarray(raw_scores)))

            # 결과 재구성 (점수 업데이트)
            reranked = []
            for result, score in zip(results, scores, strict=True):
                reranked.append(
                    SearchResult(
                        id=result.id,
                        content=result.content,
                        score=float(score),
                        metadata=result.metadata,
                    )
                )

            # 점수 내림차순 정렬
            reranked.sort(key=lambda x: x.score, reverse=True)

            # top_n 적용
            if top_n is not None:
                reranked = reranked[:top_n]

            self.stats["successful_requests"] += 1
            logger.info(
                f"Local 리랭킹 완료: {len(results)} -> {len(reranked)}개 결과 반환"
            )

            return reranked

        except Exception as e:
            self.stats["failed_requests"] += 1
            logger.error(f"Local 리랭킹 실패: {e}")
            return results  # 실패 시 원본 결과 반환

    def supports_caching(self) -> bool:
        """
        캐싱 지원 여부 반환

        CrossEncoder는 결정론적(deterministic)이므로 캐싱 가능

        Returns:
            True (캐싱 지원)
        """
        return True

    def get_stats(self) -> dict[str, Any]:
        """리랭커 통계 반환"""
        total = self.stats["total_requests"]
        success_rate = (
            self.stats["successful_requests"] / total * 100 if total > 0 else 0.0
        )

        return {
            "total_requests": self.stats["total_requests"],
            "successful_requests": self.stats["successful_requests"],
            "failed_requests": self.stats["failed_requests"],
            "success_rate": round(success_rate, 2),
            "model_name": self.model_name,
            "device": self.device,
        }
