"""
검색 완전 장애 예외 전파 테스트 (Phase 2.7 - 2/2)

목적:
    검색 백엔드 전면 장애(모든 쿼리 실패)는 전용 예외 SearchUnavailableError로
    전파되어야 한다. 예외를 삼키고 빈 리스트를 반환하면 상위 CircuitBreaker가
    장애를 감지하지 못해 영원히 CLOSED로 남는다.

    전파 경로 3종을 모두 검증한다:
    1. _search_and_merge (다중 쿼리 병렬 검색)
    2. search_and_rerank (단일/다중 쿼리 모두 — except가 삼키면 안 됨)
    3. search() 레거시 어댑터 (스트리밍 chat, /v1, admin이 사용하는 경로)

    단, 정상 빈 결과나 부분 실패는 degradation을 유지한다(전파 금지).

    또한 요청 수준 오류(사용자 입력 오류로 인한 ValueError/TypeError/KeyError 등)는
    백엔드 장애가 아니므로 SearchUnavailableError로 래핑하지 않고 빈 결과로
    degradation해야 한다 — 그렇지 않으면 한 클라이언트의 반복 오입력이 공유
    CircuitBreaker threshold를 채워 전체 사용자의 검색을 fallback으로 강등시킨다.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.lib.errors import ErrorCode, SearchUnavailableError
from app.modules.core.retrieval.interfaces import SearchResult
from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator
from app.modules.core.retrieval.query_expansion.interface import (
    ExpandedQuery,
    QueryComplexity,
    SearchIntent,
)


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


class FakeQueryExpansion:
    """다중 쿼리 경로를 강제하기 위한 가짜 쿼리 확장 엔진 (덕 타이핑)."""

    async def expand(self, query: str, **kwargs: Any) -> ExpandedQuery:
        # 원본 + 확장 1개 → all_queries는 2개가 되어 다중 쿼리 경로로 진입한다
        return ExpandedQuery(
            original=query,
            expansions=[f"{query} 확장"],
            complexity=QueryComplexity.MEDIUM,
            intent=SearchIntent.FACTUAL,
            metadata={},
        )


# ========================================
# 1. _search_and_merge (다중 쿼리 병렬 검색) 직접 호출
# ========================================


@pytest.mark.asyncio
async def test_all_queries_fail_propagates_exception() -> None:
    """모든 쿼리가 실패하면 전용 예외를 전파해야 한다 (CircuitBreaker 감지용)."""
    orch = RetrievalOrchestrator(retriever=FailingRetriever())
    with pytest.raises(SearchUnavailableError) as exc_info:
        await orch._search_and_merge(["q1", "q2"], top_k=5, use_rrf=True)

    # 원인 예외 체이닝과 에러 코드(SEARCH-004)를 보존해야 한다
    assert isinstance(exc_info.value.__cause__, ConnectionError)
    assert exc_info.value.error_code == ErrorCode.SEARCH_BACKEND_UNAVAILABLE.value


@pytest.mark.asyncio
async def test_partial_failure_returns_results() -> None:
    """일부만 실패하면 가능한 결과를 반환하고 예외를 전파하지 않아야 한다."""
    orch = RetrievalOrchestrator(retriever=PartialRetriever())
    results = await orch._search_and_merge(["q1", "q2"], top_k=5, use_rrf=True)
    assert isinstance(results, list)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_all_queries_cancelled_propagates_cancellation() -> None:
    """전부 취소(CancelledError)는 장애로 래핑하지 않고 취소 신호를 보존해야 한다."""
    import asyncio

    class CancelledRetriever:
        async def search(
            self, query: str, top_k: int = 10, filters: dict | None = None
        ) -> list[SearchResult]:
            raise asyncio.CancelledError()

    orch = RetrievalOrchestrator(retriever=CancelledRetriever())
    with pytest.raises(asyncio.CancelledError):
        await orch._search_and_merge(["q1", "q2"], top_k=5, use_rrf=True)


# ========================================
# 2. search_and_rerank 경유 — except가 전면 장애를 삼키면 안 됨
# ========================================


@pytest.mark.asyncio
async def test_search_and_rerank_single_query_total_failure_propagates() -> None:
    """단일 쿼리 경로에서도 retriever 실패는 '모든 쿼리 실패'와 동치이므로 전파해야 한다."""
    orch = RetrievalOrchestrator(retriever=FailingRetriever())
    with pytest.raises(SearchUnavailableError) as exc_info:
        await orch.search_and_rerank("q1", top_k=5, query_expansion_enabled=False)

    assert isinstance(exc_info.value.__cause__, ConnectionError)


@pytest.mark.asyncio
async def test_search_and_rerank_multi_query_total_failure_propagates() -> None:
    """다중 쿼리 경로의 전면 장애가 search_and_rerank의 except에 삼켜지면 안 된다."""
    orch = RetrievalOrchestrator(
        retriever=FailingRetriever(),
        query_expansion=FakeQueryExpansion(),  # type: ignore[arg-type]
    )
    with pytest.raises(SearchUnavailableError):
        await orch.search_and_rerank("q1", top_k=5, query_expansion_enabled=True)


@pytest.mark.asyncio
async def test_search_and_rerank_partial_failure_degrades() -> None:
    """부분 실패는 여전히 degradation(가능한 결과 반환)을 유지해야 한다."""
    orch = RetrievalOrchestrator(
        retriever=PartialRetriever(),
        query_expansion=FakeQueryExpansion(),  # type: ignore[arg-type]
    )
    results = await orch.search_and_rerank("q1", top_k=5, query_expansion_enabled=True)
    assert isinstance(results, list)
    assert len(results) >= 1


# ========================================
# 3. search() 레거시 어댑터 경유 (스트리밍 chat, /v1, admin 사용 경로)
# ========================================


@pytest.mark.asyncio
async def test_search_adapter_propagates_total_failure() -> None:
    """search() 어댑터 경유에서도 전면 장애가 '0건'으로 위장되면 안 된다."""
    orch = RetrievalOrchestrator(retriever=FailingRetriever())
    with pytest.raises(SearchUnavailableError):
        await orch.search("q1", {"limit": 5})


# ========================================
# 4. 요청 수준 오류 분류 — 사용자 입력 오류는 백엔드 장애로 오분류 금지
# ========================================


class RequestLevelErrorRetriever:
    """잘못된 사용자 입력(filters 등)으로 항상 요청 수준 오류를 내는 retriever."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def search(
        self, query: str, top_k: int = 10, filters: dict | None = None
    ) -> list[SearchResult]:
        raise self.exc


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        ValueError("invalid filter value"),
        TypeError("filter type mismatch"),
        KeyError("unknown filter field"),
    ],
    ids=["ValueError", "TypeError", "KeyError"],
)
async def test_single_query_request_level_error_degrades(exc: Exception) -> None:
    """단일 쿼리의 요청 수준 오류는 전파 없이 빈 결과로 degradation해야 한다.

    잘못된 filters 입력으로 인한 결정적(per-request) 오류를 SearchUnavailableError로
    래핑하면 공유 CircuitBreaker에 장애로 집계되어 전체 사용자가 영향을 받는다.
    """
    orch = RetrievalOrchestrator(retriever=RequestLevelErrorRetriever(exc))
    results = await orch.search_and_rerank(
        "q1", top_k=5, query_expansion_enabled=False
    )
    assert results == []


@pytest.mark.asyncio
async def test_single_query_infra_error_still_propagates() -> None:
    """단일 쿼리의 인프라성 오류(ConnectionError)는 여전히 전파해야 한다.

    분류 도입이 기존 장애 전파(CircuitBreaker 감지)를 약화시키면 안 된다.
    """
    orch = RetrievalOrchestrator(retriever=FailingRetriever())
    with pytest.raises(SearchUnavailableError) as exc_info:
        await orch.search_and_rerank("q1", top_k=5, query_expansion_enabled=False)
    assert isinstance(exc_info.value.__cause__, ConnectionError)


@pytest.mark.asyncio
async def test_multi_query_all_request_level_errors_degrade() -> None:
    """멀티 쿼리 전부가 요청 수준 오류로 실패해도 빈 결과로 degradation해야 한다.

    같은 잘못된 filters가 모든 확장 쿼리에 적용되므로 전 쿼리 실패는 자연스러운
    결과다 — 백엔드 장애가 아니므로 SearchUnavailableError 전파 금지.
    """
    orch = RetrievalOrchestrator(
        retriever=RequestLevelErrorRetriever(ValueError("invalid filter value"))
    )
    results = await orch._search_and_merge(["q1", "q2"], top_k=5, use_rrf=True)
    assert results == []


@pytest.mark.asyncio
async def test_multi_query_request_level_errors_degrade_via_search_and_rerank() -> None:
    """search_and_rerank 경유 멀티 쿼리 경로에서도 요청 수준 오류는 degradation."""
    orch = RetrievalOrchestrator(
        retriever=RequestLevelErrorRetriever(ValueError("invalid filter value")),
        query_expansion=FakeQueryExpansion(),  # type: ignore[arg-type]
    )
    results = await orch.search_and_rerank("q1", top_k=5, query_expansion_enabled=True)
    assert results == []
