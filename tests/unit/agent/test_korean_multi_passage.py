from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.modules.core.agent import extractive_reader
from app.modules.core.agent.factory import AgentFactory
from app.modules.core.generation.korean_reranked_passage_reader import (
    Documents,
    KoreanRerankedPassageReader,
)
from app.modules.core.generation.korean_span_reader import SpanAnswer
from app.modules.core.retrieval.interfaces import SearchResult
from app.modules.core.tools.factory import ToolFactory


def policy(tmp_path: Path) -> dict[str, Any]:
    return {
        "implementation": "ko_multi_passage",
        "model_dir": str(tmp_path / "qa"),
        "sufficiency_model_dir": str(tmp_path / "verifier"),
        "top_k": 8,
        "threshold": 2.5,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"top_k": 3},
        {"threshold": None},
        {"sufficiency_model_dir": ""},
        {"sufficiency_threshold": 1},
    ],
)
def test_requires_the_document_and_threshold_policy(
    tmp_path: Path, overrides: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        extractive_reader.ExtractiveReaderConfig(**(policy(tmp_path) | overrides))


@pytest.mark.asyncio
async def test_factory_search_reaches_eighth_passage_and_returns_clean_abstention(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    results = [
        SearchResult(
            str(i),
            f"분류 {i}의 색은 파랑.",
            0.5,
            {"document_id": f"article-{i}", "title": "문서", "chunk": i},
        )
        for i in range(8)
    ]
    retrieval = AsyncMock()
    retrieval.search.return_value = results
    cfg = {
        "retriever": retrieval,
        "mcp": {
            "enabled": True,
            "tools": {"search_weaviate": {"enabled": True}},
            "agent": {
                "require_evidence_quotes": True,
                "enable_reflection": False,
                "extractive_reader": policy(tmp_path),
            },
        },
    }

    def scores(q: str, docs: Documents) -> list[float]:
        return [7 if "어떤 색" in q and "분류 7" in d["content"] else -2 for d in docs]

    def read(q: str, docs: Documents) -> list[SpanAnswer]:
        spans = []
        for i, d in enumerate(docs):
            body = d["content"]
            start = body.index("파랑")
            spans.append(SpanAnswer(i, d["id"], "파랑", start, start + 2, body, 0, len(body), 5))
        return spans

    wrapper = KoreanRerankedPassageReader(lambda: scores, lambda: read, span_threshold=2.5)
    monkeypatch.setattr(KoreanRerankedPassageReader, "from_local", lambda *args: wrapper)
    monkeypatch.setattr(
        extractive_reader,
        "_select_passage",
        lambda *args: pytest.fail("Applied single-passage verifier"),
    )
    model = AsyncMock()
    tool = ToolFactory.create(cfg)
    await tool.initialize()
    extractive_reader._load_reader.cache_clear()
    try:
        agent = AgentFactory.create(cfg, model, tool)
        assert agent is not None
        yes = await agent.run("분류 7은 어떤 색인가?")
        no = await agent.run("분류 7의 최초 등재일은?")
    finally:
        await tool.shutdown()
        extractive_reader._load_reader.cache_clear()
    assert yes.success and yes.grounding_status == "verified_quotes" and yes.answer == "파랑"
    (src,) = yes.sources
    assert src["source_id"] == "7" and src["document_id"] == "article-7" and src["chunk"] == 7
    body = results[7].content
    assert body[src["answer_start"] : src["answer_end"]] == yes.answer
    assert body[src["quote_start"] : src["quote_end"]] == src["cited_sentences"][0]
    assert (
        no.success
        and no.grounding_status == "insufficient"
        and no.answer == "근거 부족"
        and no.sources == []
    )
    assert yes.tools_used == no.tools_used == ["search_weaviate"]
    assert [call.kwargs["top_k"] for call in retrieval.search.await_args_list] == [8, 8]
    model.generate_text.assert_not_awaited()
