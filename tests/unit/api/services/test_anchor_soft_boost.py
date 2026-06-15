"""멀티턴 anchor soft boost 단위 테스트 (GAP B).

직전 대화에서 인용된 문서(anchor)를 후속 질문 리랭킹 후처리에서 hard-filter 없이
약하게(boost_multiplier) 우대한다. anchor 미일치 문서끼리의 상대순서는 100% 보존한다.

핵심 요구사항:
1. config OFF(기본)이면 모든 동작이 no-op → 기존 순서 100% 동일.
2. _conversation_pairs_from_history: user/assistant 쌍 추출.
3. _extract_anchor_sources: 자립 질문이면 폐기(no-op), 후속 질문이면 직전 sources 추출.
4. _apply_anchor_soft_boost: anchor만 bubble-up, 비-anchor 상대순서 불변.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.services.rag_pipeline import RAGPipeline
from app.modules.core.retrieval.interfaces import SearchResult


@pytest.fixture
def mock_modules() -> dict[str, Any]:
    return {
        "query_router": MagicMock(enabled=False),
        "query_expansion": None,
        "retrieval_module": AsyncMock(),
        "generation_module": AsyncMock(),
        "session_module": None,
        "self_rag_module": None,
        "extract_topic_func": lambda x: x[:10],
        "circuit_breaker_factory": MagicMock(),
        "cost_tracker": MagicMock(),
        "performance_metrics": MagicMock(),
        "sql_search_service": None,
        "agent_orchestrator": None,
    }


def _pipeline(
    mock_modules: dict[str, Any],
    *,
    anchor_enabled: bool = True,
    boost_multiplier: float | None = None,
    session_module: Any | None = None,
) -> RAGPipeline:
    anchor_cfg: dict[str, Any] = {"enabled": anchor_enabled}
    if boost_multiplier is not None:
        anchor_cfg["boost_multiplier"] = boost_multiplier
    config: dict[str, Any] = {
        "rag": {"top_k": 8, "rerank_top_k": 8, "multiturn_anchor": anchor_cfg},
        "retrieval": {"top_k": 8, "min_score": 0.05},
        "reranking": {},
    }
    modules = dict(mock_modules)
    if session_module is not None:
        modules["session_module"] = session_module
    return RAGPipeline(config=config, **modules)


def _doc(doc_id: str, score: float, *, source_file: str | None = None) -> SearchResult:
    metadata: dict[str, Any] = {"document_id": doc_id}
    if source_file is not None:
        metadata["source_file"] = source_file
    return SearchResult(id=doc_id, content=f"내용 {doc_id}", score=score, metadata=metadata)


class TestBoostMultiplierClamp:
    def test_default_multiplier(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        assert pipeline.multiturn_anchor_boost_multiplier == pytest.approx(1.05)

    def test_above_cap_resets_to_default(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules, boost_multiplier=2.0)
        assert pipeline.multiturn_anchor_boost_multiplier == pytest.approx(1.05)

    def test_at_or_below_one_resets_to_default(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules, boost_multiplier=1.0)
        assert pipeline.multiturn_anchor_boost_multiplier == pytest.approx(1.05)

    def test_within_range_kept(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules, boost_multiplier=1.08)
        assert pipeline.multiturn_anchor_boost_multiplier == pytest.approx(1.08)


class TestConversationPairs:
    def test_extracts_user_assistant_pairs(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        history = {
            "messages": [
                {"type": "user", "content": "질문1"},
                {"type": "assistant", "content": "답변1"},
                {"type": "user", "content": "질문2"},
                {"type": "assistant", "content": "답변2"},
            ]
        }
        pairs = pipeline._conversation_pairs_from_history(history)
        assert pairs == [
            {"user": "질문1", "assistant": "답변1"},
            {"user": "질문2", "assistant": "답변2"},
        ]

    def test_empty_history(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        assert pipeline._conversation_pairs_from_history({}) == []


class TestApplyAnchorSoftBoost:
    def test_disabled_is_noop(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules, anchor_enabled=False)
        docs = [_doc("a", 0.9), _doc("b", 0.5), _doc("c", 0.4)]
        anchors = [{"document": None, "document_id": "c"}]
        out = pipeline._apply_anchor_soft_boost(anchors, docs)
        assert [d.id for d in out] == ["a", "b", "c"]

    def test_no_anchors_is_noop(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        docs = [_doc("a", 0.9), _doc("b", 0.5)]
        out = pipeline._apply_anchor_soft_boost([], docs)
        assert [d.id for d in out] == ["a", "b"]

    def test_no_matching_anchor_is_noop(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        docs = [_doc("a", 0.9), _doc("b", 0.5)]
        anchors = [{"document": None, "document_id": "zzz"}]
        out = pipeline._apply_anchor_soft_boost(anchors, docs)
        assert [d.id for d in out] == ["a", "b"]

    def test_anchor_bubbles_up_small_gap(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        # b(0.50)이 anchor. a(0.51)와의 격차가 작아 boost(×1.05=0.525)로 추월.
        docs = [_doc("a", 0.51), _doc("b", 0.50), _doc("c", 0.40)]
        anchors = [{"document": None, "document_id": "b"}]
        out = pipeline._apply_anchor_soft_boost(anchors, docs)
        assert out[0].id == "b"
        assert out[1].id == "a"

    def test_anchor_large_gap_not_promoted(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        # b(0.50) anchor, a(0.90) 격차가 큼. boost(0.525)로도 a를 못 넘는다.
        docs = [_doc("a", 0.90), _doc("b", 0.50), _doc("c", 0.40)]
        anchors = [{"document": None, "document_id": "b"}]
        out = pipeline._apply_anchor_soft_boost(anchors, docs)
        assert [d.id for d in out] == ["a", "b", "c"]

    def test_non_anchor_relative_order_preserved(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        # fusion이 만든 비점수내림차순 순서를 anchor 부스트가 깨면 안 된다.
        # 비-anchor a,c,d의 상대순서(a→c→d)는 anchor b가 끼어들어도 보존.
        docs = [
            _doc("a", 0.40),
            _doc("c", 0.80),
            _doc("b", 0.42),
            _doc("d", 0.30),
        ]
        anchors = [{"document": None, "document_id": "b"}]
        out = pipeline._apply_anchor_soft_boost(anchors, docs)
        non_anchor = [d.id for d in out if d.id != "b"]
        assert non_anchor == ["a", "c", "d"]

    def test_match_by_source_file(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        docs = [
            _doc("a", 0.51, source_file="x.pdf"),
            _doc("b", 0.50, source_file="anchor.pdf"),
        ]
        anchors = [{"document": "anchor.pdf", "document_id": None}]
        out = pipeline._apply_anchor_soft_boost(anchors, docs)
        assert out[0].metadata["source_file"] == "anchor.pdf"


class TestExtractAnchorSources:
    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, mock_modules) -> None:
        session = AsyncMock()
        pipeline = _pipeline(mock_modules, anchor_enabled=False, session_module=session)
        out = await pipeline._extract_anchor_sources("그건 어때?", "sid")
        assert out == []
        session.get_chat_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_standalone_question_discards_anchor(self, mock_modules) -> None:
        session = AsyncMock()
        pipeline = _pipeline(mock_modules, session_module=session)
        # 자립적(충분히 길고 구체적)인 질문이면 anchor를 폐기한다(주제 전환 가능성).
        out = await pipeline._extract_anchor_sources(
            "청년 내일채움공제 프로그램의 신청 자격과 지원 금액을 자세히 알려주세요", "sid"
        )
        assert out == []

    @pytest.mark.asyncio
    async def test_followup_extracts_last_sources(self, mock_modules) -> None:
        session = AsyncMock()
        session.get_chat_history = AsyncMock(
            return_value={
                "messages": [
                    {"type": "user", "content": "지원금 얼마야"},
                    {
                        "type": "assistant",
                        "content": "...",
                        "sources": [
                            {"document": "doc1.pdf", "document_id": "d1"},
                            {"document": "doc2.pdf", "document_id": "d2"},
                        ],
                    },
                ]
            }
        )
        pipeline = _pipeline(mock_modules, session_module=session)
        out = await pipeline._extract_anchor_sources("그건 얼마야?", "sid")
        ids = {a["document_id"] for a in out}
        assert ids == {"d1", "d2"}

    @pytest.mark.asyncio
    async def test_injected_history_avoids_relookup(self, mock_modules) -> None:
        session = AsyncMock()
        pipeline = _pipeline(mock_modules, session_module=session)
        history = {
            "messages": [
                {"type": "user", "content": "지원금"},
                {
                    "type": "assistant",
                    "content": "...",
                    "sources": [{"document": "doc1.pdf", "document_id": "d1"}],
                },
            ]
        }
        out = await pipeline._extract_anchor_sources(
            "그건 얼마야?", "sid", chat_history=history
        )
        assert out == [{"document": "doc1.pdf", "document_id": "d1"}]
        session.get_chat_history.assert_not_called()
