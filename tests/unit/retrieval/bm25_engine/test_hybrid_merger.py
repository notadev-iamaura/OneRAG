"""
HybridMerger 단위 테스트

Dense 벡터 검색 결과와 BM25 키워드 검색 결과를
RRF(Reciprocal Rank Fusion)로 병합하는 모듈.

테스트 범위:
1. RRF 병합 기본 동작
2. alpha 가중치 조절
3. 중복 문서 처리
4. 한쪽만 결과가 있는 경우
5. 빈 결과 처리
"""


from app.modules.core.retrieval.interfaces import SearchResult


class TestHybridMergerBasic:
    """HybridMerger 기본 병합 테스트"""

    def test_merge_both_sources(self) -> None:
        from app.modules.core.retrieval.bm25_engine.hybrid_merger import HybridMerger

        merger = HybridMerger(alpha=0.6)

        dense_results = [
            SearchResult(id="doc-1", content="문서1", score=0.95, metadata={}),
            SearchResult(id="doc-2", content="문서2", score=0.85, metadata={}),
            SearchResult(id="doc-3", content="문서3", score=0.75, metadata={}),
        ]

        bm25_results = [
            {"id": "doc-2", "content": "문서2", "score": 0.90, "metadata": {}},
            {"id": "doc-4", "content": "문서4", "score": 0.80, "metadata": {}},
            {"id": "doc-1", "content": "문서1", "score": 0.70, "metadata": {}},
        ]

        merged = merger.merge(
            dense_results=dense_results,
            bm25_results=bm25_results,
            top_k=5,
        )

        result_ids = [r.id for r in merged]
        assert len(merged) <= 5
        assert len(result_ids) == len(set(result_ids))
        assert "doc-2" in result_ids[:2]

    def test_merge_returns_search_result_type(self) -> None:
        from app.modules.core.retrieval.bm25_engine.hybrid_merger import HybridMerger

        merger = HybridMerger()

        dense_results = [
            SearchResult(id="doc-1", content="문서1", score=0.9, metadata={"src": "dense"}),
        ]
        bm25_results = [
            {"id": "doc-2", "content": "문서2", "score": 0.8, "metadata": {"src": "bm25"}},
        ]

        merged = merger.merge(dense_results=dense_results, bm25_results=bm25_results, top_k=5)

        assert all(isinstance(r, SearchResult) for r in merged)


class TestHybridMergerAlpha:
    """HybridMerger alpha 가중치 테스트"""

    def test_alpha_1_favors_dense(self) -> None:
        from app.modules.core.retrieval.bm25_engine.hybrid_merger import HybridMerger

        merger = HybridMerger(alpha=1.0)

        dense_results = [
            SearchResult(id="dense-top", content="Dense 최상위", score=0.99, metadata={}),
        ]
        bm25_results = [
            {"id": "bm25-top", "content": "BM25 최상위", "score": 0.99, "metadata": {}},
        ]

        merged = merger.merge(dense_results=dense_results, bm25_results=bm25_results, top_k=2)

        assert merged[0].id == "dense-top"

    def test_alpha_0_favors_bm25(self) -> None:
        from app.modules.core.retrieval.bm25_engine.hybrid_merger import HybridMerger

        merger = HybridMerger(alpha=0.0)

        dense_results = [
            SearchResult(id="dense-top", content="Dense 최상위", score=0.99, metadata={}),
        ]
        bm25_results = [
            {"id": "bm25-top", "content": "BM25 최상위", "score": 0.99, "metadata": {}},
        ]

        merged = merger.merge(dense_results=dense_results, bm25_results=bm25_results, top_k=2)

        assert merged[0].id == "bm25-top"


class TestHybridMergerEdgeCases:
    """HybridMerger 엣지 케이스 테스트"""

    def test_merge_only_dense(self) -> None:
        from app.modules.core.retrieval.bm25_engine.hybrid_merger import HybridMerger

        merger = HybridMerger()
        dense_results = [
            SearchResult(id="doc-1", content="문서1", score=0.9, metadata={}),
        ]
        merged = merger.merge(dense_results=dense_results, bm25_results=[], top_k=5)
        assert len(merged) == 1
        assert merged[0].id == "doc-1"

    def test_merge_only_bm25(self) -> None:
        from app.modules.core.retrieval.bm25_engine.hybrid_merger import HybridMerger

        merger = HybridMerger()
        bm25_results = [
            {"id": "doc-1", "content": "문서1", "score": 0.8, "metadata": {}},
        ]
        merged = merger.merge(dense_results=[], bm25_results=bm25_results, top_k=5)
        assert len(merged) == 1
        assert merged[0].id == "doc-1"

    def test_merge_both_empty(self) -> None:
        from app.modules.core.retrieval.bm25_engine.hybrid_merger import HybridMerger

        merger = HybridMerger()
        merged = merger.merge(dense_results=[], bm25_results=[], top_k=5)
        assert merged == []

    def test_merge_respects_top_k(self) -> None:
        from app.modules.core.retrieval.bm25_engine.hybrid_merger import HybridMerger

        merger = HybridMerger()
        dense_results = [
            SearchResult(id=f"dense-{i}", content=f"D{i}", score=0.9 - i * 0.1, metadata={})
            for i in range(3)
        ]
        bm25_results = [
            {"id": f"bm25-{i}", "content": f"B{i}", "score": 0.9 - i * 0.1, "metadata": {}}
            for i in range(3)
        ]
        merged = merger.merge(dense_results=dense_results, bm25_results=bm25_results, top_k=3)
        assert len(merged) <= 3
