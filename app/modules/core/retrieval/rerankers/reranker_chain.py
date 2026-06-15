"""
RerankerChain - 다중 리랭커 순차 실행 체인

여러 리랭커를 순차적으로 실행하여 검색 결과의 관련성을 점진적으로 개선합니다.
예: RRF → ColBERT → LLM Reranker

특징:
- 순차 실행 (파이프라인 패턴)
- 중간 리랭커 실패 시 계속 진행 옵션
- 개별 리랭커 활성화/비활성화
- 리랭커별 통계 추적

구현일: 2025-12-31
"""

from dataclasses import dataclass
from typing import Any, Protocol

from .....lib.logger import get_logger
from ..interfaces import SearchResult

logger = get_logger(__name__)


# ========================================
# 리랭커 인터페이스 (체인 내부용)
# ========================================


class ChainableReranker(Protocol):
    """체인에서 사용 가능한 리랭커 프로토콜"""

    name: str
    enabled: bool

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_n: int | None = None,
    ) -> list[SearchResult]:
        """검색 결과 리랭킹"""
        ...

    def supports_caching(self) -> bool:
        """캐싱 지원 여부"""
        ...


# ========================================
# 설정 스키마
# ========================================


@dataclass
class RerankerChainConfig:
    """
    리랭커 체인 설정

    Attributes:
        enabled: 체인 활성화 여부
        continue_on_error: 리랭커 오류 시 계속 진행 여부
        log_intermediate_results: 중간 결과 로깅 여부
    """

    enabled: bool = True
    continue_on_error: bool = True
    log_intermediate_results: bool = False


# ========================================
# 리랭커 체인
# ========================================


class RerankerChain:
    """
    다중 리랭커 순차 실행 체인

    특징:
    - 리랭커들을 순차적으로 실행
    - 이전 리랭커의 결과가 다음 리랭커의 입력
    - 실패 시 원본 전달 또는 중단 (설정 가능)
    - 개별 리랭커 동적 추가/제거 지원
    """

    def __init__(
        self,
        rerankers: list[ChainableReranker],
        config: RerankerChainConfig,
    ):
        """
        Args:
            rerankers: 순차 실행할 리랭커 리스트
            config: 체인 설정
        """
        self.rerankers = list(rerankers)
        self.config = config

        # 통계
        self._stats = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
        }

        # 리랭커별 통계
        self._per_reranker_stats: dict[str, dict[str, int]] = {}
        for reranker in rerankers:
            self._per_reranker_stats[reranker.name] = {
                "calls": 0,
                "successes": 0,
                "failures": 0,
            }

        reranker_names = [r.name for r in rerankers]
        logger.info(
            f"RerankerChain 초기화: rerankers={reranker_names}, "
            f"continue_on_error={config.continue_on_error}"
        )

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_n: int | None = None,
    ) -> list[SearchResult]:
        """
        체인 실행: 모든 리랭커를 순차적으로 적용

        Args:
            query: 검색 쿼리
            results: 초기 검색 결과
            top_n: 최종 반환할 결과 수 (None이면 전체)

        Returns:
            모든 리랭커가 적용된 최종 결과
        """
        # 비활성화 상태면 원본 반환
        if not self.config.enabled:
            return results

        # 빈 입력 처리
        if not results:
            return []

        self._stats["total_calls"] += 1
        current_results = results
        any_success = False

        # 각 리랭커 순차 실행
        for reranker in self.rerankers:
            # 비활성화된 리랭커 스킵
            if not reranker.enabled:
                logger.debug(f"리랭커 스킵 (비활성화): {reranker.name}")
                continue

            # 리랭커별 통계 초기화 (처음 보는 리랭커)
            if reranker.name not in self._per_reranker_stats:
                self._per_reranker_stats[reranker.name] = {
                    "calls": 0,
                    "successes": 0,
                    "failures": 0,
                }

            self._per_reranker_stats[reranker.name]["calls"] += 1

            try:
                if self.config.log_intermediate_results:
                    logger.debug(
                        f"[{reranker.name}] 입력: {len(current_results)}개 결과"
                    )

                # 리랭커 실행 (top_n은 체인 끝에서만 적용)
                new_results = await reranker.rerank(
                    query=query,
                    results=current_results,
                    top_n=None,  # 중간 리랭커는 전체 전달
                )

                current_results = new_results
                self._per_reranker_stats[reranker.name]["successes"] += 1
                any_success = True

                if self.config.log_intermediate_results:
                    logger.debug(
                        f"[{reranker.name}] 출력: {len(current_results)}개 결과"
                    )

            except Exception as e:
                self._per_reranker_stats[reranker.name]["failures"] += 1
                logger.warning(f"[{reranker.name}] 리랭킹 실패: {e}")

                if not self.config.continue_on_error:
                    # 에러 시 중단하고 현재까지의 결과 반환
                    logger.info("continue_on_error=False, 체인 중단")
                    break
                # continue_on_error=True면 현재 결과 유지하고 계속

        # 최종 결과 처리
        if any_success:
            self._stats["successful_calls"] += 1
        else:
            self._stats["failed_calls"] += 1

        # top_n 적용 (체인 끝에서)
        if top_n is not None:
            current_results = current_results[:top_n]

        logger.info(
            f"RerankerChain 완료: {len(results)} -> {len(current_results)}개"
        )

        return current_results

    async def initialize(self) -> None:
        """체인 내 각 리랭커의 initialize를 위임 호출(워밍업).

        orchestrator는 reranker에 initialize가 있으면 위임하는데, 체인 자체에
        이 메서드가 없으면 내부 리랭커(예: CrossEncoder 모델 로드)의 워밍업이
        통째로 스킵돼 첫 쿼리에서 수십 초 지연이 발생한다. 개별 리랭커 실패는
        경고만 남기고 계속 진행한다(rerank 시점에 lazy 재시도되므로 안전).
        """
        for reranker in self.rerankers:
            init = getattr(reranker, "initialize", None)
            if not callable(init):
                continue
            try:
                await init()
            except Exception as e:
                logger.warning(f"[{reranker.name}] 리랭커 초기화 실패(워밍업 생략): {e}")

    async def close(self) -> None:
        """initialize와 대칭으로 close 가능한 리랭커의 자원을 정리한다.

        체인에 close가 없으면 orchestrator 종료 시 내부 리랭커가 보유한 자원
        (예: httpx 클라이언트, 모델 참조)이 누수된다. 개별 정리 실패는 경고만
        남기고 계속 진행해 한 리랭커의 실패가 다른 리랭커 정리를 막지 않는다.
        """
        for reranker in self.rerankers:
            close = getattr(reranker, "close", None)
            if not callable(close):
                continue
            try:
                await close()
            except Exception as e:
                logger.warning(f"[{reranker.name}] 리랭커 정리 실패: {e}")

    def supports_caching(self) -> bool:
        """
        캐싱 지원 여부 반환

        모든 리랭커가 캐싱을 지원해야 체인도 캐싱 지원.

        Returns:
            모든 리랭커가 캐싱 지원하면 True
        """
        if not self.rerankers:
            return True

        return all(r.supports_caching() for r in self.rerankers)

    def get_stats(self) -> dict[str, Any]:
        """
        체인 통계 반환

        Returns:
            전체 및 리랭커별 통계
        """
        return {
            "total_calls": self._stats["total_calls"],
            "successful_calls": self._stats["successful_calls"],
            "failed_calls": self._stats["failed_calls"],
            "rerankers_count": len(self.rerankers),
            "reranker_names": [r.name for r in self.rerankers],
            "per_reranker_stats": self._per_reranker_stats,
            "config": {
                "enabled": self.config.enabled,
                "continue_on_error": self.config.continue_on_error,
            },
        }

    # ========================================
    # 동적 리랭커 관리
    # ========================================

    def add_reranker(self, reranker: ChainableReranker) -> None:
        """
        리랭커 동적 추가

        Args:
            reranker: 추가할 리랭커
        """
        self.rerankers.append(reranker)
        self._per_reranker_stats[reranker.name] = {
            "calls": 0,
            "successes": 0,
            "failures": 0,
        }
        logger.info(f"리랭커 추가: {reranker.name}")

    def remove_reranker(self, name: str) -> bool:
        """
        리랭커 동적 제거

        Args:
            name: 제거할 리랭커 이름

        Returns:
            제거 성공 여부
        """
        for i, reranker in enumerate(self.rerankers):
            if reranker.name == name:
                self.rerankers.pop(i)
                logger.info(f"리랭커 제거: {name}")
                return True
        return False

    def get_reranker(self, name: str) -> ChainableReranker | None:
        """
        이름으로 리랭커 조회

        Args:
            name: 리랭커 이름

        Returns:
            리랭커 (없으면 None)
        """
        for reranker in self.rerankers:
            if reranker.name == name:
                return reranker
        return None
