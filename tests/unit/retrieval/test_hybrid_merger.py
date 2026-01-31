"""
HybridMerger 단위 테스트

Dense 벡터 검색과 BM25 키워드 검색 결과의
RRF(Reciprocal Rank Fusion) 병합 로직을 검증합니다.

테스트 항목:
  - Dense 전용 병합
  - BM25 전용 병합
  - 하이브리드 중복 문서 점수 합산
  - BM25 metadata 미포함 시 빈 dict 처리
  - 빈 결과 처리
  - 유효하지 않은 alpha 예외 처리
"""

from __future__ import annotations

import pytest

from app.modules.core.retrieval.bm25_engine.hybrid_merger import HybridMerger
from app.modules.core.retrieval.interfaces import SearchResult


# ── Dense 전용 병합 테스트 ──────────────────────────────────
class TestDenseOnly:
    """Dense 결과만 전달했을 때 정상 병합되는지 검증"""

    def test_dense_only_returns_search_results(self) -> None:
        """Dense 결과만 있으면 해당 결과가 그대로 반환된다."""
        merger = HybridMerger(alpha=1.0)
        dense = [
            SearchResult(id="d1", content="문서1", score=0.9, metadata={"src": "a"}),
            SearchResult(id="d2", content="문서2", score=0.8, metadata={"src": "b"}),
        ]

        result = merger.merge(dense_results=dense, bm25_results=[], top_k=10)

        assert len(result) == 2
        assert result[0].id == "d1"
        assert result[0].content == "문서1"
        assert result[0].metadata == {"src": "a"}
        # 첫 번째 문서의 RRF 점수가 두 번째보다 높아야 한다
        assert result[0].score > result[1].score


# ── BM25 전용 병합 테스트 ──────────────────────────────────
class TestBM25Only:
    """BM25 결과만 전달했을 때 정상 병합되는지 검증"""

    def test_bm25_only_returns_search_results(self) -> None:
        """BM25 결과만 있으면 해당 결과가 SearchResult로 변환된다."""
        merger = HybridMerger(alpha=0.0)
        bm25 = [
            {"id": "b1", "content": "키워드문서1", "metadata": {"lang": "ko"}},
            {"id": "b2", "content": "키워드문서2", "metadata": {"lang": "en"}},
        ]

        result = merger.merge(dense_results=[], bm25_results=bm25, top_k=10)

        assert len(result) == 2
        assert result[0].id == "b1"
        assert result[0].content == "키워드문서1"
        assert result[0].metadata == {"lang": "ko"}


# ── 하이브리드 중복 문서 점수 합산 테스트 ─────────────────
class TestHybridDuplicate:
    """Dense와 BM25 양쪽에 동일 문서가 있을 때 점수가 합산되는지 검증"""

    def test_duplicate_doc_score_is_summed(self) -> None:
        """동일 문서 ID는 RRF 점수가 합산되어 상위에 랭크된다."""
        merger = HybridMerger(alpha=0.5)

        # "common"이 양쪽 모두 존재
        dense = [
            SearchResult(id="common", content="공통문서", score=0.9, metadata={}),
            SearchResult(id="dense_only", content="벡터전용", score=0.8, metadata={}),
        ]
        bm25 = [
            {"id": "bm25_only", "content": "키워드전용", "metadata": {}},
            {"id": "common", "content": "공통문서", "metadata": {}},
        ]

        result = merger.merge(dense_results=dense, bm25_results=bm25, top_k=10)

        # "common"은 양쪽 점수 합산이므로 최상위여야 한다
        assert result[0].id == "common"
        assert len(result) == 3


# ── BM25 metadata 없을 때 빈 dict 테스트 ─────────────────
class TestBM25NoMetadata:
    """BM25 결과에 metadata 키가 없을 때 빈 dict로 처리되는지 검증"""

    def test_missing_metadata_defaults_to_empty_dict(self) -> None:
        """metadata 키가 없는 BM25 결과는 빈 dict를 metadata로 사용한다."""
        merger = HybridMerger(alpha=0.0)
        bm25 = [
            {"id": "no_meta", "content": "메타없는문서"},
        ]

        result = merger.merge(dense_results=[], bm25_results=bm25, top_k=10)

        assert len(result) == 1
        assert result[0].metadata == {}


# ── 빈 결과 테스트 ────────────────────────────────────────
class TestEmptyResults:
    """양쪽 모두 빈 리스트일 때 빈 결과를 반환하는지 검증"""

    def test_empty_inputs_return_empty_list(self) -> None:
        """Dense, BM25 모두 비어있으면 빈 리스트를 반환한다."""
        merger = HybridMerger(alpha=0.6)

        result = merger.merge(dense_results=[], bm25_results=[], top_k=10)

        assert result == []


# ── 유효하지 않은 alpha 예외 테스트 ───────────────────────
class TestInvalidAlpha:
    """alpha 범위(0.0~1.0) 벗어나면 ValueError가 발생하는지 검증"""

    def test_alpha_too_high_raises_value_error(self) -> None:
        """alpha > 1.0이면 ValueError가 발생한다."""
        with pytest.raises(ValueError, match="alpha"):
            HybridMerger(alpha=1.5)

    def test_alpha_too_low_raises_value_error(self) -> None:
        """alpha < 0.0이면 ValueError가 발생한다."""
        with pytest.raises(ValueError, match="alpha"):
            HybridMerger(alpha=-0.1)
