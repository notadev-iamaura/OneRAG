"""search(query, options) 어댑터 + GraphRAG 하이브리드 경로 filters 보강 테스트 (#39)

두 하위 경로에서 filters가 조용히 사라지던 결함을 검증한다.
1. Fallback 어댑터 경로: search(query, options)가 options.filters를 추출해
   retriever.search에 전달하는지.
2. GraphRAG 하이브리드 경로: _hybrid_strategy.search가 filters kwarg를 받는지
   (vector_graph_search가 **kwargs→retriever.search로 전파해 실제 소비됨).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.core.retrieval.interfaces import IRetriever, SearchResult
from app.modules.core.retrieval.orchestrator import RetrievalOrchestrator


def _make_retriever() -> MagicMock:
    retriever = MagicMock(spec=IRetriever)
    retriever.search = AsyncMock(return_value=[])
    retriever.health_check = AsyncMock(return_value=True)
    return retriever


@pytest.mark.asyncio
async def test_adapter_search_passes_filters_to_retriever() -> None:
    """search 어댑터가 options.filters를 retriever.search에 전달한다."""
    retriever = _make_retriever()
    orchestrator = RetrievalOrchestrator(retriever=retriever, config={})

    await orchestrator.search(
        "질의", {"limit": 5, "filters": {"file_type": "pdf"}}
    )

    # retriever.search가 filters={'file_type':'pdf'}로 호출되어야 한다
    assert retriever.search.await_count >= 1
    called_filters = retriever.search.await_args_list[0].args
    # search(query, top_k, filters) 위치 인자 또는 kwargs로 전달될 수 있다
    call = retriever.search.await_args_list[0]
    passed = call.kwargs.get("filters")
    if passed is None and len(called_filters) >= 3:
        passed = called_filters[2]
    assert passed == {"file_type": "pdf"}


@pytest.mark.asyncio
async def test_adapter_search_empty_filters_treated_as_none() -> None:
    """빈 filters dict는 None으로 처리돼 무필터 검색이 회귀하지 않는다."""
    retriever = _make_retriever()
    orchestrator = RetrievalOrchestrator(retriever=retriever, config={})

    await orchestrator.search("질의", {"limit": 5, "filters": {}})

    call = retriever.search.await_args_list[0]
    passed = call.kwargs.get("filters")
    if passed is None and len(call.args) >= 3:
        passed = call.args[2]
    assert passed is None


@pytest.mark.asyncio
async def test_hybrid_path_passes_filters_to_strategy() -> None:
    """GraphRAG 하이브리드 경로가 _hybrid_strategy.search에 filters를 전달한다."""
    retriever = _make_retriever()

    hybrid_result = MagicMock()
    hybrid_result.documents = [
        SearchResult(id="1", content="c", score=0.9, metadata={})
    ]
    hybrid_result.vector_count = 1
    hybrid_result.graph_count = 0

    hybrid_strategy = MagicMock()
    hybrid_strategy.search = AsyncMock(return_value=hybrid_result)

    orchestrator = RetrievalOrchestrator(
        retriever=retriever,
        hybrid_strategy=hybrid_strategy,
        config={},
    )

    await orchestrator.search_and_rerank(
        query="질의",
        top_k=5,
        use_graph=True,
        rerank_enabled=False,
        query_expansion_enabled=False,
        filters={"file_type": "pdf"},
    )

    hybrid_strategy.search.assert_awaited_once()
    kwargs = hybrid_strategy.search.await_args.kwargs
    assert kwargs.get("filters") == {"file_type": "pdf"}
