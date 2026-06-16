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


class TestHallucinationGateMessageExternalization:
    """보류 메시지 외부화 회귀/오버라이드 (사용자노출 문자열 config화)."""

    def test_default_message_is_builtin_korean(self, mock_modules) -> None:
        """(a) 미설정 시 코드 내장 한국어 기본 메시지 사용 (회귀 0)"""
        from app.api.services.rag_pipeline import HALLUCINATION_GATE_NO_ANSWER_MESSAGE

        pipeline = _pipeline(mock_modules)
        assert (
            pipeline.hallucination_gate_no_answer_message
            == HALLUCINATION_GATE_NO_ANSWER_MESSAGE
        )
        # 불일치 시 교체되는 답변 = 코드 기본 메시지
        docs = [_doc("a", "report_2021.pdf")]
        out = pipeline._apply_hallucination_gate("2023년 매출", _gen(), docs, {})
        assert out.answer == HALLUCINATION_GATE_NO_ANSWER_MESSAGE

    def test_override_message(self, mock_modules) -> None:
        """(b) config 오버라이드 시 보류 메시지 교체 (데드 키 아님)"""
        config: dict[str, Any] = {
            "rag": {
                "hallucination_gate": {
                    "enabled": True,
                    "no_answer_message": "No data for the requested period.",
                },
            },
            "retrieval": {},
            "reranking": {},
        }
        pipeline = RAGPipeline(config=config, **mock_modules)
        assert (
            pipeline.hallucination_gate_no_answer_message
            == "No data for the requested period."
        )
        docs = [_doc("a", "report_2021.pdf")]
        out = pipeline._apply_hallucination_gate("2023년 매출", _gen(), docs, {})
        assert out.answer == "No data for the requested period."


class TestGenerationFallbackMessageExternalization:
    """생성 모듈 부재 폴백 메시지 외부화 회귀/오버라이드."""

    def test_default_message_is_builtin_korean(self, mock_modules) -> None:
        """(a) 미설정 시 코드 내장 한국어 기본값 (회귀 0)"""
        from app.api.services.rag_pipeline import GENERATION_MODULE_MISSING_MESSAGE

        pipeline = _pipeline(mock_modules)
        assert (
            pipeline.generation_module_missing_message
            == GENERATION_MODULE_MISSING_MESSAGE
        )
        assert (
            pipeline.generation_module_missing_message
            == "죄송합니다. 답변을 생성할 수 없습니다."
        )

    def test_override_message(self, mock_modules) -> None:
        """(b) config 오버라이드 시 폴백 메시지 교체 (데드 키 아님)"""
        config: dict[str, Any] = {
            "rag": {
                "generation_fallback": {
                    "module_missing_message": "Answer generation is unavailable.",
                },
            },
            "retrieval": {},
            "reranking": {},
        }
        pipeline = RAGPipeline(config=config, **mock_modules)
        assert (
            pipeline.generation_module_missing_message
            == "Answer generation is unavailable."
        )
