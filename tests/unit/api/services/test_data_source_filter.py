"""data_source → 검색 메타필터 매핑 단위 테스트 (GAP G).

라우터가 판단한 data_source(structured/general/both)를 검색 메타데이터 필터로
변환한다. filter_mappings는 generic dict이며 기본 {}로 no-op(회귀 0).

핵심 요구사항:
1. filter_mappings가 비어있으면(기본) 추가 필터 없음 → 기존 동작 100% 동일.
2. 매핑이 있으면 data_source에 대응하는 필터를 기존 filters에 병합.
3. 기존 filters 키는 보존(setdefault 병합).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.services.rag_pipeline import RAGPipeline


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
    mock_modules: dict[str, Any], *, filter_mappings: dict[str, Any] | None = None
) -> RAGPipeline:
    data_source_routing: dict[str, Any] = {"enabled": True}
    if filter_mappings is not None:
        data_source_routing["filter_mappings"] = filter_mappings
    config: dict[str, Any] = {
        "rag": {"top_k": 8, "rerank_top_k": 8},
        "retrieval": {"top_k": 8, "min_score": 0.05},
        "reranking": {},
        "query_routing": {"data_source_routing": data_source_routing},
    }
    return RAGPipeline(config=config, **mock_modules)


class TestResolveDataSourceFilter:
    def test_no_data_source_returns_empty(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules, filter_mappings={"structured": {"k": "v"}})
        assert pipeline._resolve_data_source_filter(None) == {}

    def test_empty_mappings_returns_empty(self, mock_modules) -> None:
        # 기본 filter_mappings 미설정 → no-op
        pipeline = _pipeline(mock_modules)
        assert pipeline._resolve_data_source_filter("structured") == {}

    def test_unmatched_data_source_returns_empty(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules, filter_mappings={"structured": {"k": "v"}})
        assert pipeline._resolve_data_source_filter("general") == {}

    def test_matched_data_source_returns_filter(self, mock_modules) -> None:
        pipeline = _pipeline(
            mock_modules, filter_mappings={"structured": {"doc_category": "regulation"}}
        )
        assert pipeline._resolve_data_source_filter("structured") == {
            "doc_category": "regulation"
        }

    def test_returned_filter_is_copy(self, mock_modules) -> None:
        mappings = {"structured": {"doc_category": "regulation"}}
        pipeline = _pipeline(mock_modules, filter_mappings=mappings)
        result = pipeline._resolve_data_source_filter("structured")
        result["mutated"] = True
        # 원본 매핑은 변형되지 않아야 한다
        assert "mutated" not in mappings["structured"]


class TestBuildRetrievalFiltersWithDataSource:
    def test_no_data_source_no_mappings_is_noop(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        # data_source 미주입 + 매핑 없음 → 기존 동작(필터 없음)
        assert pipeline._build_retrieval_filters({}) is None

    def test_existing_filters_preserved_when_no_mapping(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        filters = pipeline._build_retrieval_filters({"filters": {"company_id": "c1"}})
        assert filters == {"company_id": "c1"}

    def test_data_source_filter_merged(self, mock_modules) -> None:
        pipeline = _pipeline(
            mock_modules, filter_mappings={"structured": {"doc_category": "regulation"}}
        )
        filters = pipeline._build_retrieval_filters(
            {"filters": {"company_id": "c1"}, "data_source": "structured"}
        )
        assert filters == {"company_id": "c1", "doc_category": "regulation"}

    def test_existing_filter_key_not_overridden(self, mock_modules) -> None:
        pipeline = _pipeline(
            mock_modules, filter_mappings={"structured": {"doc_category": "mapped"}}
        )
        # 기존 filters의 동일 키는 setdefault로 보존(매핑이 덮어쓰지 않음)
        filters = pipeline._build_retrieval_filters(
            {"filters": {"doc_category": "explicit"}, "data_source": "structured"}
        )
        assert filters == {"doc_category": "explicit"}
