"""정확 식별자(exact-identifier) 검색 보강 + 리랭크 안정화 단위 테스트 (GAP A).

원본에서 차용하되 특정 언어 전용 휴리스틱은 제거하고, 언어무관
generic 식별자(GP-1200X/ERR-404/RTX-4090 등)와 라틴 구문 보강만 채택한다.

핵심 요구사항:
1. config OFF(기본)이면 모든 보강이 no-op → 기존 동작 100% 동일.
2. _exact_identifier_terms: 대문자-숫자-하이픈 토큰을 NFKC 정규화 후 추출.
3. _augment_search_queries_with_exact_terms: 식별자(1.25)/라틴(1.1) 가중치 추가 주입.
4. _retrieval_candidate_limit: candidate pool 확장(×3, +10, max 40).
5. _stabilize_reranked_results_with_exact_signals: 정확매칭 문서 상위 안정화.
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
    mock_modules: dict[str, Any], *, exact_enabled: bool = True
) -> RAGPipeline:
    config: dict[str, Any] = {
        "rag": {
            "top_k": 8,
            "rerank_top_k": 8,
            "exact_identifier": {"enabled": exact_enabled},
        },
        "retrieval": {"top_k": 8, "min_score": 0.05},
        "reranking": {},
    }
    return RAGPipeline(config=config, **mock_modules)


def _doc(doc_id: str, content: str, score: float = 0.5) -> SearchResult:
    return SearchResult(
        id=doc_id,
        content=content,
        score=score,
        metadata={"document_id": doc_id, "source_file": f"{doc_id}.pdf"},
    )


class TestExactIdentifierTerms:
    def test_extracts_uppercase_digit_hyphen_tokens(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        terms = pipeline._exact_identifier_terms("GP-1200X 모델과 RTX-4090 비교")
        assert "GP-1200X" in terms
        assert "RTX-4090" in terms

    def test_no_identifier_returns_empty(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        assert pipeline._exact_identifier_terms("일반적인 질문입니다") == []

    def test_nfkc_fullwidth_normalization(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        # 전각 문자 ＥＲＲ－４０４ → NFKC 정규화 후 ERR-404로 추출
        terms = pipeline._exact_identifier_terms("ＥＲＲ－４０４ 오류")
        assert any(t.replace("-", "").upper().startswith("ERR") for t in terms)

    def test_dedup_identifiers(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        terms = pipeline._exact_identifier_terms("ERR-404 ERR-404 ERR-404")
        assert terms == ["ERR-404"]


class TestLatinPhraseTerms:
    def test_extracts_multiword_latin_phrase(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        terms = pipeline._latin_phrase_terms("질문: error handling 정책은?")
        assert "error handling" in terms

    def test_short_phrase_skipped(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        # 4자 미만 구문은 제외
        assert pipeline._latin_phrase_terms("a b") == []


class TestAugmentSearchQueries:
    def test_disabled_is_noop(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules, exact_enabled=False)
        queries = ["GP-1200X 사양"]
        weights = [1.0]
        out_q, out_w = pipeline._augment_search_queries_with_exact_terms(
            "GP-1200X 사양", queries, weights
        )
        assert out_q == queries
        assert out_w == weights

    def test_enabled_injects_identifier_with_weight(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        queries = ["GP-1200X 사양 알려줘"]
        weights = [1.0]
        out_q, out_w = pipeline._augment_search_queries_with_exact_terms(
            "GP-1200X 사양 알려줘", queries, weights
        )
        assert "GP-1200X" in out_q
        idx = out_q.index("GP-1200X")
        assert out_w[idx] == pytest.approx(1.25)

    def test_enabled_injects_latin_phrase_with_weight(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        queries = ["error handling 정책"]
        weights = [1.0]
        out_q, out_w = pipeline._augment_search_queries_with_exact_terms(
            "error handling 정책", queries, weights
        )
        assert "error handling" in out_q
        idx = out_q.index("error handling")
        assert out_w[idx] == pytest.approx(1.1)

    def test_dedup_existing_query(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        # 이미 같은 정규화 키가 있으면 중복 추가하지 않는다
        queries = ["GP-1200X"]
        weights = [1.0]
        out_q, _ = pipeline._augment_search_queries_with_exact_terms(
            "GP-1200X", queries, weights
        )
        assert out_q.count("GP-1200X") == 1


class TestRetrievalCandidateLimit:
    def test_multiplier_and_min_extra(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        # requested=8 → max(8*3=24, 8+10=18) = 24, max 40 이하
        assert pipeline._retrieval_candidate_limit(8) == 24

    def test_min_extra_dominates_small_limit(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        # requested=2 → max(6, 12) = 12
        assert pipeline._retrieval_candidate_limit(2) == 12

    def test_capped_at_max(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        # requested=20 → max(60, 30)=60 → cap 40
        assert pipeline._retrieval_candidate_limit(20) == 40

    def test_already_above_max_unchanged(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        assert pipeline._retrieval_candidate_limit(50) == 50

    def test_disabled_returns_requested(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules, exact_enabled=False)
        # 기능 OFF면 확장 없이 요청 한도 그대로 반환(no-op)
        assert pipeline._retrieval_candidate_limit(8) == 8


class TestStabilizeReranked:
    def test_disabled_is_noop(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules, exact_enabled=False)
        docs = [
            _doc("a", "관련 없는 내용"),
            _doc("b", "GP-1200X 사양이 여기 있습니다"),
        ]
        out = pipeline._stabilize_reranked_results_with_exact_signals(
            "GP-1200X 사양", docs
        )
        assert [d.id for d in out] == ["a", "b"]

    def test_no_secondary_signal_is_noop(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        docs = [_doc("a", "내용 a"), _doc("b", "내용 b")]
        out = pipeline._stabilize_reranked_results_with_exact_signals(
            "일반 질문", docs
        )
        assert [d.id for d in out] == ["a", "b"]

    def test_exact_match_promoted_to_top(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        docs = [
            _doc("a", "관련 없는 내용"),
            _doc("b", "GP-1200X 모델의 상세 사양"),
        ]
        out = pipeline._stabilize_reranked_results_with_exact_signals(
            "GP-1200X 사양", docs
        )
        assert out[0].id == "b"

    def test_fewer_than_two_unchanged(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        docs = [_doc("a", "GP-1200X")]
        out = pipeline._stabilize_reranked_results_with_exact_signals(
            "GP-1200X", docs
        )
        assert [d.id for d in out] == ["a"]


class TestRescueExactIdentifierCandidates:
    @pytest.mark.asyncio
    async def test_disabled_returns_results(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules, exact_enabled=False)
        results = [_doc("a", "내용")]
        retrieval_module = MagicMock()
        retrieval_module.search = AsyncMock(return_value=[])
        out = await pipeline._rescue_exact_identifier_candidates(
            retrieval_module, "GP-1200X", results, None, 8
        )
        assert out == results
        retrieval_module.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_merges_matching_rescued_candidates(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        existing = [_doc("a", "관련 없는 내용")]
        rescued = [_doc("z", "GP-1200X 정확 매칭 문서")]
        retrieval_module = MagicMock()
        retrieval_module.search = AsyncMock(return_value=rescued)
        out = await pipeline._rescue_exact_identifier_candidates(
            retrieval_module, "GP-1200X 사양", existing, None, 8
        )
        ids = [d.id for d in out]
        assert "z" in ids
        assert "a" in ids
        # 매칭 후보가 앞쪽으로 병합된다
        assert ids[0] == "z"

    @pytest.mark.asyncio
    async def test_no_identifier_returns_results(self, mock_modules) -> None:
        pipeline = _pipeline(mock_modules)
        results = [_doc("a", "내용")]
        retrieval_module = MagicMock()
        retrieval_module.search = AsyncMock(return_value=[])
        out = await pipeline._rescue_exact_identifier_candidates(
            retrieval_module, "일반 질문", results, None, 8
        )
        assert out == results
        retrieval_module.search.assert_not_called()
