"""
검색 완전 장애 예외 전파 테스트 (Phase 2.7 - 2/2)

목적:
    _search_and_merge가 모든 쿼리 실패(완전 장애) 시 예외를 전파해야 한다.
    예외를 삼키고 빈 리스트를 반환하면 상위 CircuitBreaker가 장애를 감지하지
    못해 영원히 CLOSED로 남는다. 단, 정상 빈 결과나 부분 실패는 전파하지 않는다.
"""

from __future__ import annotations

import pytest

from app.modules.core.retrieval.interfaces import SearchResult
from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator


class FailingRetriever:
    """모든 검색이 연결 장애로 실패하는 retriever."""

    async def search(
        self, query: str, top_k: int = 10, filters: dict | None = None
    ) -> list[SearchResult]:
        raise ConnectionError("backend down")


class PartialRetriever:
    """첫 호출만 실패하고 이후는 성공하는 retriever."""

    def __init__(self) -> None:
        self.count = 0

    async def search(
        self, query: str, top_k: int = 10, filters: dict | None = None
    ) -> list[SearchResult]:
        self.count += 1
        if self.count == 1:
            raise ConnectionError("transient fail")
        return [SearchResult(id="1", content="문서", score=0.9, metadata={})]


@pytest.mark.asyncio
async def test_all_queries_fail_propagates_exception() -> None:
    """모든 쿼리가 실패하면 예외를 전파해야 한다 (CircuitBreaker 감지용)."""
    orch = RetrievalOrchestrator(retriever=FailingRetriever())
    with pytest.raises(ConnectionError):
        await orch._search_and_merge(["q1", "q2"], top_k=5, use_rrf=True)


@pytest.mark.asyncio
async def test_partial_failure_returns_results() -> None:
    """일부만 실패하면 가능한 결과를 반환하고 예외를 전파하지 않아야 한다."""
    orch = RetrievalOrchestrator(retriever=PartialRetriever())
    results = await orch._search_and_merge(["q1", "q2"], top_k=5, use_rrf=True)
    assert isinstance(results, list)
    assert len(results) >= 1
