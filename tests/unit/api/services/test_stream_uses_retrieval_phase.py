"""스트리밍 경로가 비스트리밍과 같은 검색 국면(run_retrieval_phase)을 쓰는지 검증.

예전 stream_rag_pipeline 은 retrieval_module.search 를 직접 호출해 세션 컨텍스트 반영,
정확 식별자/문서명 구출, 리랭크 융합·안정화, 앵커 부스트가 빠졌다. 이제는 RAGPipeline 의
공유 메서드를 호출하고, 그 결과(context_documents)를 생성 단계에 넘겨야 한다.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.services.rag_pipeline import (
    PreparedContext,
    RAGPipeline,
    RerankResults,
    RetrievalPhase,
    RetrievalResults,
    RouteDecision,
)


def _phase(docs: list) -> RetrievalPhase:
    prepared = PreparedContext(
        original_query="q",
        session_context="이전 대화 요약",
        expanded_query="q",
        expanded_queries=["q"],
        query_weights=None,
    )
    return RetrievalPhase(
        prepared_context=prepared,
        retrieval_results=RetrievalResults(documents=docs, count=len(docs)),
        sql_search_result=None,
        rerank_results=RerankResults(documents=docs, count=len(docs), reranked=True),
        context_documents=docs,
    )


@pytest.fixture
def service(monkeypatch):
    from app.api.services.chat_service import ChatService

    monkeypatch.setattr(
        RAGPipeline, "route_query",
        AsyncMock(return_value=RouteDecision(should_continue=True, metadata={})),
    )
    session = MagicMock()
    session.get_session = AsyncMock(return_value={"is_valid": True})
    session.get_context_string = AsyncMock(return_value="")
    retrieval = MagicMock()
    retrieval.search = AsyncMock(return_value=[])

    async def stream_answer(**kwargs):
        yield "답변"

    generation = MagicMock()
    generation.stream_answer = stream_answer
    svc = ChatService({"session": session, "retrieval": retrieval, "generation": generation}, {})
    svc.add_conversation_to_session = AsyncMock()
    return svc, retrieval


@pytest.mark.asyncio
async def test_stream_calls_shared_retrieval_phase(service):
    svc, retrieval = service
    doc = SimpleNamespace(content="본문", metadata={"source": "a.pdf"}, score=0.9, id="d1")
    svc.rag_pipeline.run_retrieval_phase = AsyncMock(return_value=_phase([doc]))

    events = [e async for e in svc.stream_rag_pipeline("질문", "sess")]

    svc.rag_pipeline.run_retrieval_phase.assert_awaited_once()
    args, kwargs = svc.rag_pipeline.run_retrieval_phase.await_args
    assert args[0] == "질문" and args[1] == "sess"
    assert "budget" in kwargs and callable(kwargs["budget"])
    # 공유 국면을 썼으므로 search 를 직접 호출하지 않는다
    retrieval.search.assert_not_awaited()
    metadata = next(e for e in events if e["event"] == "metadata")
    assert metadata["data"]["search_results"] == 1
    assert metadata["data"]["reranking_applied"] is True
    assert any(e["event"] == "chunk" and e["data"] == "답변" for e in events)


@pytest.mark.asyncio
async def test_stream_survives_retrieval_phase_failure(service):
    svc, _ = service
    svc.rag_pipeline.run_retrieval_phase = AsyncMock(side_effect=RuntimeError("검색 장애"))

    events = [e async for e in svc.stream_rag_pipeline("질문", "sess")]

    types = [e["event"] for e in events]
    assert "error" not in types
    assert types[0] == "metadata" and types[-1] == "done"
    assert events[0]["data"]["search_results"] == 0


@pytest.mark.asyncio
async def test_done_event_carries_hallucination_gate_signal(service):
    svc, _ = service
    doc = SimpleNamespace(content="2022년 매출", metadata={"source": "a.pdf"}, score=0.9, id="d1")
    svc.rag_pipeline.run_retrieval_phase = AsyncMock(return_value=_phase([doc]))
    svc.rag_pipeline.hallucination_gate_enabled = True
    svc.rag_pipeline.hallucination_gate_require_period_match = True
    svc.rag_pipeline._hallucination_gate_period_mismatch = MagicMock(return_value=True)

    events = [e async for e in svc.stream_rag_pipeline("2024년 매출은?", "sess")]

    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["hallucination_gate"] == "period_mismatch"


@pytest.mark.asyncio
async def test_stream_passes_routing_data_source_to_retrieval(service, monkeypatch):
    """라우팅이 정한 data_source 가 스트리밍 검색 옵션에도 반영되어야 한다(비스트리밍과 동일)."""
    svc, _ = service
    monkeypatch.setattr(
        RAGPipeline, "route_query",
        AsyncMock(return_value=RouteDecision(should_continue=True, metadata={"data_source": "faq"})),
    )
    svc.rag_pipeline.run_retrieval_phase = AsyncMock(return_value=_phase([]))

    _ = [e async for e in svc.stream_rag_pipeline("질문", "sess", {"limit": 3})]

    args, _kwargs = svc.rag_pipeline.run_retrieval_phase.await_args
    assert args[2]["data_source"] == "faq"
    assert args[2]["limit"] == 3
