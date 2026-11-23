"""Offline regression for Chroma ingestion, scoped lexical search and two-hop agents."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("chromadb")
pytest.importorskip("rank_bm25")

from app.core.di_container import create_mcp_server_instance
from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore
from app.modules.core.agent.factory import AgentFactory
from app.modules.core.retrieval.bm25_engine import BM25Index, HybridMerger
from app.modules.core.retrieval.bm25_engine.tokenizer import WhitespaceTokenizer
from app.modules.core.retrieval.retrievers.chroma_retriever import ChromaRetriever


def retriever(path):
    return ChromaRetriever(
        embedder=SimpleNamespace(embed_query=lambda _: [1.0, 0.0]),
        store=ChromaVectorStore(persist_directory=str(path)),
        bm25_index=BM25Index(WhitespaceTokenizer()),
        hybrid_merger=HybridMerger(alpha=0.25),
    )


def chunk(doc_id, text, vector, group):
    return {
        "id": f"{doc_id}-0",
        "content": text,
        "embedding": vector,
        "metadata": {"document_id": doc_id, "source_file": f"{doc_id}.txt", "group": group},
    }


@pytest.mark.asyncio
async def test_chroma_rank_survives_reload_replacement_deletion_and_filters(tmp_path):
    writer = retriever(tmp_path)
    docs = [
        chunk("contract", "contract needle", [0.0, 1.0], "A"),
        chunk("delivery", "delivery deadline", [1.0, 0.0], "B"),
    ]
    assert (await writer.add_documents(docs))["success_count"] == 2
    reader = retriever(tmp_path)
    reader.store.fetch_objects = AsyncMock(wraps=reader.store.fetch_objects)
    assert (await reader.search("needle", top_k=1))[0].id == "contract-0"
    await reader.search("needle", top_k=1)
    if reader.store.read_revision() is not None:
        assert reader.store.fetch_objects.await_count == 1
    scoped = await asyncio.gather(
        *[
            reader.search("needle", top_k=1, filters={"group": group})
            for group in ("A", "B", "A", "B")
        ]
    )
    assert [hits[0].metadata["group"] for hits in scoped] == ["A", "B", "A", "B"]
    assert await reader.search("needle", filters={"id": "contract-0", "group": "B"}) == []
    assert (await reader.search("needle", filters={"ids": ["delivery-0"]}))[0].id == "delivery-0"
    await writer.add_documents([chunk("contract", "new revision", [0.0, 1.0], "A")])
    assert (await reader.search("needle", top_k=1))[0].id == "delivery-0"
    assert (await reader.search("revision", top_k=1))[0].id == "contract-0"
    assert await writer.delete_document("contract")
    assert [d.id for d in await reader.search("revision")] == ["delivery-0"]


@pytest.mark.asyncio
async def test_agent_uses_discovered_document_id_to_open_second_source(tmp_path):
    search = retriever(tmp_path)
    await search.add_documents(
        [
            chunk("contract", "계약서 납품서 ID PO-8842", [1.0, 0.0], "A"),
            chunk("PO-8842", "확정 납기 12월 18일", [0.0, 1.0], "A"),
        ]
    )
    config = {"mcp": {"enabled": True, "agent": {"enable_reflection": False}}}
    tools = await create_mcp_server_instance(config, retriever=search)
    calls = []

    class ScriptedModel:
        async def generate_text(self, prompt, system_prompt):
            calls.append(prompt)
            if len(calls) == 1:
                assert "계약 일정" in prompt
                tool, args = "search_weaviate", {"query": "계약서", "top_k": 1}
            elif len(calls) == 2:
                assert "PO-8842" in prompt and "12월 18일" not in prompt
                tool, args = "get_document_by_id", {"document_id": "PO-8842"}
            else:
                assert "확정 납기 12월 18일" in prompt
                return "납품서의 확정 납기는 12월 18일입니다."
            return json.dumps(
                {
                    "tool_calls": [{"tool_name": tool, "arguments": args}],
                    "should_continue": len(calls) == 1,
                }
            )

    agent = AgentFactory.create(config, SimpleNamespace(get_client=ScriptedModel), tools)
    assert agent is not None
    result = await agent.run("그 납기는 언제인가요?", session_context="계약 일정")
    assert result.stop_reason == "completed" and result.steps_taken == 2
    assert "12월 18일" in result.answer
    assert {s["document_id"] for s in result.sources} == {"contract", "PO-8842"}


@pytest.mark.asyncio
async def test_grounded_followup_selects_only_returned_sentences(tmp_path):
    store = retriever(tmp_path)
    await store.add_documents(
        [
            chunk("contract", "Shipment code BX324.", [1, 0], "A"),
            chunk("memo", "Other agreement.", [1, 0], "A"),
            chunk("delivery", "BX324 arrives Friday.", [0, 1], "A"),
        ]
    )
    config = {
        "mcp": {
            "enabled": True,
            "agent": {"require_evidence_quotes": True, "enable_reflection": False},
        }
    }
    tools = await create_mcp_server_instance(config, retriever=store)
    # One source on the initial read, both on the follow-up.
    original = store.search

    async def search(query, **kwargs):
        return await original(
            query, top_k=1, filters={"document_id": "delivery" if "BX324" in query else "contract"}
        )

    store.search = search
    model = SimpleNamespace(
        generate_text=AsyncMock(
            side_effect=[
                "INSUFFICIENT\nSEARCH: BX324",
                "Friday\n[S1.1] [S2.1]",
            ]
        )
    )
    agent = AgentFactory.create(config, model, tools)
    result = await agent.run("When will the shipment arrive?")
    assert result.success and result.grounding_status == "verified_quotes"
    assert result.steps_taken == 2 and result.answer == "Friday"
    assert {s["content_preview"] for s in result.sources} == {
        "Shipment code BX324.",
        "BX324 arrives Friday.",
    }
    assert model.generate_text.await_count == 2


@pytest.mark.asyncio
async def test_agent_deadline_includes_generation(tmp_path):
    store = retriever(tmp_path)
    await store.add_documents([chunk("a", "evidence", [1, 0], "A")])
    config = {
        "mcp": {"enabled": True, "agent": {"require_evidence_quotes": True, "timeout_seconds": 0.2}}
    }
    server = await create_mcp_server_instance(config, retriever=store)

    async def stalled(**kwargs):
        await asyncio.sleep(10)

    agent = AgentFactory.create(config, SimpleNamespace(generate_text=stalled), server)
    assert (await agent.run("evidence")).stop_reason == "timeout"


@pytest.mark.asyncio
async def test_invalid_citation_does_not_report_a_successful_agent(tmp_path):
    store = retriever(tmp_path)
    await store.add_documents([chunk("a", "Delivery is Friday.", [1, 0], "A")])
    config = {"mcp": {"enabled": True, "agent": {"require_evidence_quotes": True}}}
    server = await create_mcp_server_instance(config, retriever=store)
    client = SimpleNamespace(generate_text=AsyncMock(return_value="Friday\n[S1.99]"))
    result = await AgentFactory.create(config, client, server).run("Which day?")
    assert not result.success and result.stop_reason == "error"
    assert result.grounding_status == "invalid_citation" and result.sources == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_calls", "response", "reason", "limits"),
    [
        (5, "INSUFFICIENT", "no_new_evidence", [8]),
        (2, "INSUFFICIENT\nSEARCH: clue a\nSEARCH: clue b", "no_new_evidence", [8, 3]),
        (1, "INSUFFICIENT\nSEARCH: clue a", "max_iterations", [8]),
    ],
)
async def test_document_search_respects_call_budget_and_stops_on_duplicate_evidence(
    tmp_path, max_calls, response, reason, limits
):
    store = retriever(tmp_path)
    await store.add_documents([chunk("one", "Only one document.", [1, 0], "A")])
    store.search = AsyncMock(wraps=store.search)
    config = {
        "mcp": {
            "enabled": True,
            "agent": {
                "require_evidence_quotes": True,
                "max_tool_calls": max_calls,
            },
        }
    }
    server = await create_mcp_server_instance(config, retriever=store)
    model = SimpleNamespace(generate_text=AsyncMock(return_value=response))
    agent = AgentFactory.create(config, model, server)
    result = await agent.run("Which document?")
    assert [c.kwargs["top_k"] for c in store.search.await_args_list] == limits
    assert result.stop_reason == reason
    assert result.grounding_status == "insufficient" and not result.sources
    model.generate_text.assert_awaited_once()
