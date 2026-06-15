"""리랭크 fusion guardrail 테스트 (#33)

리랭커가 lexical/hybrid 상위 신호(원본 점수)를 죽여 정확 토큰 문서를 하위로
미는 것을 막기 위해, 리랭커 top1을 보존하면서 원본 신호 상위 후보를 재삽입한다.

핵심 요구사항:
1. enabled=false(기본)면 no-op(하위 호환).
2. 3건 미만이면 그대로 반환.
3. enabled=true면 리랭커 top1을 보존하고 original_score 높은 하위 후보를 승격.
4. identity 중복은 제거된다.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.api.services.rag_pipeline import RAGPipeline
from app.modules.core.retrieval.interfaces import SearchResult


@pytest.fixture
def mock_config() -> dict[str, Any]:
    return {"generation": {}, "rag": {}, "retrieval": {}, "reranking": {}}


@pytest.fixture
def mock_modules() -> dict[str, Any]:
    from unittest.mock import AsyncMock, MagicMock

    return {
        "query_router": MagicMock(enabled=False),
        "query_expansion": None,
        "retrieval_module": AsyncMock(),
        "generation_module": AsyncMock(),
        "session_module": AsyncMock(),
        "self_rag_module": None,
        "extract_topic_func": lambda x: x[:10],
        "circuit_breaker_factory": MagicMock(),
        "cost_tracker": MagicMock(),
        "performance_metrics": MagicMock(),
        "sql_search_service": None,
        "agent_orchestrator": None,
    }


def _doc(doc_id: str, original_score: float) -> SearchResult:
    """original_score 신호를 가진 SearchResult 생성."""
    return SearchResult(
        id=doc_id,
        content=f"내용 {doc_id}",
        score=0.5,
        metadata={"document_id": doc_id, "original_score": original_score},
    )


def _ids(docs: list[Any]) -> list[str]:
    return [d.id for d in docs]


def _pipeline(mock_config: dict[str, Any], mock_modules: dict[str, Any]) -> RAGPipeline:
    return RAGPipeline(config=mock_config, **mock_modules)


def test_fusion_disabled_is_noop(mock_config, mock_modules) -> None:
    """enabled=false(기본)면 원본 순서를 그대로 반환한다."""
    pipeline = _pipeline(mock_config, mock_modules)
    docs = [_doc("a", 0.1), _doc("b", 0.9), _doc("c", 0.8), _doc("d", 0.7)]
    reranking_config: dict[str, Any] = {"fusion": {"enabled": False}}

    fused = pipeline._fuse_reranked_results_with_original_signals(
        docs, reranking_config, {}
    )

    assert _ids(fused) == _ids(docs)


def test_fusion_fewer_than_three_returns_as_is(mock_config, mock_modules) -> None:
    """3건 미만이면 fusion을 적용하지 않는다."""
    pipeline = _pipeline(mock_config, mock_modules)
    docs = [_doc("a", 0.1), _doc("b", 0.9)]
    reranking_config: dict[str, Any] = {"fusion": {"enabled": True}}

    fused = pipeline._fuse_reranked_results_with_original_signals(
        docs, reranking_config, {}
    )

    assert _ids(fused) == _ids(docs)


def test_fusion_preserves_top1_and_promotes_high_original(mock_config, mock_modules) -> None:
    """top1 보존 + original_score 높은 하위 후보가 상위로 승격된다."""
    pipeline = _pipeline(mock_config, mock_modules)
    # 리랭커 순서: a(top1, 원본낮음) > b(원본 0.3) > c(원본 0.95 최고) > d(원본 0.4)
    docs = [_doc("a", 0.1), _doc("b", 0.3), _doc("c", 0.95), _doc("d", 0.4)]
    reranking_config: dict[str, Any] = {
        "fusion": {
            "enabled": True,
            "strategy": "rerank_top1_original_top3",
            "preserve_rerank_top_k": 1,
            "original_top_k": 1,
        }
    }

    fused = pipeline._fuse_reranked_results_with_original_signals(
        docs, reranking_config, {}
    )

    # top1(a)은 보존되어야 한다
    assert fused[0].id == "a"
    # original_score 최고인 c가 2위로 승격되어야 한다
    assert fused[1].id == "c"
    # 중복 없이 전체 문서가 유지된다
    assert set(_ids(fused)) == {"a", "b", "c", "d"}
    assert len(fused) == len(docs)


def test_fusion_dedups_identity(mock_config, mock_modules) -> None:
    """fusion 결과에 identity 중복이 없어야 한다."""
    pipeline = _pipeline(mock_config, mock_modules)
    docs = [_doc("a", 0.1), _doc("b", 0.3), _doc("c", 0.95), _doc("d", 0.4)]
    reranking_config: dict[str, Any] = {
        "fusion": {"enabled": True, "preserve_rerank_top_k": 1, "original_top_k": 3}
    }

    fused = pipeline._fuse_reranked_results_with_original_signals(
        docs, reranking_config, {}
    )

    ids = _ids(fused)
    assert len(ids) == len(set(ids))
