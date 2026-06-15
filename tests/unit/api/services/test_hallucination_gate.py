"""환각 방지 게이트(기간 불일치 보류) 단위 테스트 (GAP C).

질문에 명시된 캘린더 연도(20xx)가 검색 문서의 연도집합과 완전 disjoint이면
최종 답변을 '확인 불가' 메시지로 교체해 다른 기간 데이터로의 단정을 막는다.

핵심 요구사항:
1. config OFF(기본)이면 no-op → generation_result 그대로 반환.
2. 캘린더 연도만 매칭(언어무관), JP fiscal(年度) 휴리스틱 없음.
3. 질문/문서에 연도 정보가 없으면 게이트 미적용(오탐 방지).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.services.rag_pipeline import RAGPipeline
from app.modules.core.generation.generator import GenerationResult
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


def _pipeline(mock_modules: dict[str, Any], *, gate_enabled: bool = True) -> RAGPipeline:
    config: dict[str, Any] = {
        "rag": {
            "top_k": 8,
            "rerank_top_k": 8,
            "hallucination_gate": {"enabled": gate_enabled},
        },
        "retrieval": {"top_k": 8, "min_score": 0.05},
        "reranking": {},
    }
    return RAGPipeline(config=config, **mock_modules)


def _doc(doc_id: str, source_file: str) -> SearchResult:
    return SearchResult(
        id=doc_id,
        content=f"내용 {doc_id}",
        score=0.5,
        metadata={"document_id": doc_id, "source_file": source_file},
    )


def _gen(answer: str = "2023년 매출은 100억입니다") -> GenerationResult:
    return GenerationResult(
        answer=answer,
        text=answer,
        tokens_used=10,
        model_used="test",
        provider="test",
        generation_time=0.1,
    )


class TestPeriodMismatch:
    def test_disjoint_years_is_mismatch(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        docs = [_doc("a", "report_2021.pdf"), _doc("b", "report_2022.pdf")]
        assert pipeline._hallucination_gate_period_mismatch("2023년 매출", docs) is True

    def test_overlapping_year_not_mismatch(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        docs = [_doc("a", "report_2023.pdf"), _doc("b", "report_2021.pdf")]
        assert pipeline._hallucination_gate_period_mismatch("2023년 매출", docs) is False

    def test_no_query_year_not_mismatch(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        docs = [_doc("a", "report_2021.pdf")]
        assert pipeline._hallucination_gate_period_mismatch("매출 알려줘", docs) is False

    def test_no_doc_year_not_mismatch(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        docs = [_doc("a", "report.pdf")]
        assert pipeline._hallucination_gate_period_mismatch("2023년 매출", docs) is False


class TestApplyHallucinationGate:
    def test_disabled_is_noop(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules, gate_enabled=False)
        docs = [_doc("a", "report_2021.pdf")]
        original = _gen()
        out = pipeline._apply_hallucination_gate("2023년 매출", original, docs, {})
        assert out is original
        assert out.answer == original.answer

    def test_mismatch_replaces_answer(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        docs = [_doc("a", "report_2021.pdf")]
        original = _gen()
        out = pipeline._apply_hallucination_gate("2023년 매출", original, docs, {})
        # 답변이 '확인 불가' 메시지로 교체된다(원본과 달라짐)
        assert out.answer != original.answer
        assert out.answer.strip()

    def test_no_mismatch_keeps_answer(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        docs = [_doc("a", "report_2023.pdf")]
        original = _gen()
        out = pipeline._apply_hallucination_gate("2023년 매출", original, docs, {})
        assert out.answer == original.answer

    def test_require_period_match_false_is_noop(self, mock_modules) -> None:
        config: dict[str, Any] = {
            "rag": {
                "hallucination_gate": {"enabled": True, "require_period_match": False},
            },
            "retrieval": {},
            "reranking": {},
        }
        pipeline = RAGPipeline(config=config, **mock_modules)
        docs = [_doc("a", "report_2021.pdf")]
        original = _gen()
        out = pipeline._apply_hallucination_gate("2023년 매출", original, docs, {})
        assert out.answer == original.answer
