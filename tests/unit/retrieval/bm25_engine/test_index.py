"""
BM25Index 단위 테스트

rank-bm25 라이브러리를 래핑한 BM25 인덱스.
문서 인덱싱 및 키워드 검색 기능을 테스트합니다.

테스트 범위:
1. 문서 인덱싱
2. 쿼리 검색 (점수 및 랭킹)
3. 빈 인덱스 처리
4. 점수 정규화 (0~1)
5. 메타데이터 필터링
"""

import pytest

# rank_bm25 선택적 의존성
pytest.importorskip("rank_bm25")
# kiwipiepy도 필요
pytest.importorskip("kiwipiepy")


class TestBM25IndexBuild:
    """BM25Index 인덱스 구축 테스트"""

    def test_build_index_from_documents(self) -> None:
        """
        문서 리스트로 인덱스 구축

        Given: 문서 3개 (id, content, metadata 포함)
        When: build() 호출
        Then: 인덱스 구축 성공, document_count == 3
        """
        from app.modules.core.retrieval.bm25_engine.index import BM25Index
        from app.modules.core.retrieval.bm25_engine.tokenizer import KoreanTokenizer

        tokenizer = KoreanTokenizer()
        index = BM25Index(tokenizer=tokenizer)

        documents = [
            {"id": "doc-1", "content": "삼성전자 주가 분석 리포트", "metadata": {"source": "finance"}},
            {"id": "doc-2", "content": "애플 아이폰 신제품 출시", "metadata": {"source": "tech"}},
            {"id": "doc-3", "content": "RAG 시스템 설치 가이드", "metadata": {"source": "docs"}},
        ]
        index.build(documents)

        assert index.document_count == 3

    def test_build_empty_documents(self) -> None:
        """빈 문서 리스트로 인덱스 구축"""
        from app.modules.core.retrieval.bm25_engine.index import BM25Index
        from app.modules.core.retrieval.bm25_engine.tokenizer import KoreanTokenizer

        tokenizer = KoreanTokenizer()
        index = BM25Index(tokenizer=tokenizer)
        index.build([])

        assert index.document_count == 0


class TestBM25IndexSearch:
    """BM25Index 검색 테스트"""

    @pytest.fixture
    def built_index(self):
        """인덱스가 구축된 BM25Index"""
        from app.modules.core.retrieval.bm25_engine.index import BM25Index
        from app.modules.core.retrieval.bm25_engine.tokenizer import KoreanTokenizer

        tokenizer = KoreanTokenizer()
        index = BM25Index(tokenizer=tokenizer)

        documents = [
            {"id": "doc-1", "content": "삼성전자 주가 분석 리포트", "metadata": {"source": "finance"}},
            {"id": "doc-2", "content": "애플 아이폰 신제품 출시 소식", "metadata": {"source": "tech"}},
            {"id": "doc-3", "content": "RAG 시스템 설치 가이드 문서", "metadata": {"source": "docs"}},
            {"id": "doc-4", "content": "삼성전자 반도체 사업 전망", "metadata": {"source": "finance"}},
        ]
        index.build(documents)
        return index

    def test_search_returns_ranked_results(self, built_index) -> None:
        results = built_index.search("삼성전자", top_k=4)
        assert len(results) > 0
        top_ids = [r["id"] for r in results[:2]]
        assert "doc-1" in top_ids or "doc-4" in top_ids

    def test_search_score_normalized(self, built_index) -> None:
        results = built_index.search("삼성전자 주가", top_k=4)
        for result in results:
            assert 0.0 <= result["score"] <= 1.0

    def test_search_respects_top_k(self, built_index) -> None:
        results = built_index.search("삼성전자", top_k=2)
        assert len(results) <= 2

    def test_search_returns_metadata(self, built_index) -> None:
        results = built_index.search("삼성전자", top_k=1)
        assert len(results) > 0
        assert "metadata" in results[0]
        assert "source" in results[0]["metadata"]

    def test_search_empty_index(self) -> None:
        from app.modules.core.retrieval.bm25_engine.index import BM25Index
        from app.modules.core.retrieval.bm25_engine.tokenizer import KoreanTokenizer

        tokenizer = KoreanTokenizer()
        index = BM25Index(tokenizer=tokenizer)
        index.build([])
        results = index.search("아무거나", top_k=10)
        assert results == []

    def test_search_no_match(self, built_index) -> None:
        results = built_index.search("zyxwvuts", top_k=4)
        if results:
            assert all(r["score"] < 0.1 for r in results)


class TestBM25IndexResultFormat:
    """BM25Index 결과 형식 테스트"""

    def test_result_contains_required_fields(self) -> None:
        from app.modules.core.retrieval.bm25_engine.index import BM25Index
        from app.modules.core.retrieval.bm25_engine.tokenizer import KoreanTokenizer

        tokenizer = KoreanTokenizer()
        index = BM25Index(tokenizer=tokenizer)
        index.build([
            {"id": "doc-1", "content": "테스트 문서", "metadata": {"source": "test"}},
        ])

        results = index.search("테스트", top_k=1)
        assert len(results) == 1
        result = results[0]
        assert "id" in result
        assert "content" in result
        assert "score" in result
        assert "metadata" in result


def test_rank_before_sigmoid_and_exclude_documents_without_query_terms():
    from app.modules.core.retrieval.bm25_engine.index import BM25Index
    from app.modules.core.retrieval.bm25_engine.tokenizer import WhitespaceTokenizer

    index = BM25Index(WhitespaceTokenizer())
    index.build([{"id": "weak", "content": "term padding padding"},
                 {"id": "strong", "content": "term term term"},
                 {"id": "noise", "content": "irrelevant"}])
    hits = index.search("term " * 100)
    assert [hit["id"] for hit in hits] == ["strong", "weak"]
    assert [hit["score"] for hit in hits] == [1.0, 1.0]


def test_sparse_scores_match_reference_with_repeated_and_unknown_terms():
    from rank_bm25 import BM25Plus

    from app.modules.core.retrieval.bm25_engine.index import BM25Index
    from app.modules.core.retrieval.bm25_engine.tokenizer import WhitespaceTokenizer

    tokenizer = WhitespaceTokenizer()
    docs = [{"id": str(i), "content": text} for i, text in enumerate([
        "alpha beta", "alpha alpha delta", "gamma epsilon", "beta gamma",
    ])]
    reference = BM25Plus(tokenizer.tokenize_batch([doc["content"] for doc in docs]))
    index = BM25Index(tokenizer)
    index.build(docs)
    q = "alpha beta beta missing"
    scores = reference.get_scores(tokenizer.tokenize(q))
    hits = index.search(q)
    assert [int(h["id"]) for h in hits] == sorted((0, 1, 3), key=lambda i: -scores[i])
    for hit in hits:
        assert hit["score"] == pytest.approx(index._normalize_score(scores[int(hit["id"])]))


def test_linked_titles_require_a_full_word_and_preserve_leading_hits():
    from app.modules.core.retrieval.bm25_engine.linked_titles import prioritize_linked_titles

    titles = ["First source", "North", "South", "Fourth", "Fifth", "Port", "Harbor"]
    hits = [{"id": t, "metadata": {"title": t}, "content": t} for t in titles]
    hits[0]["content"] = "Passengers use the airport or Harbor."
    order = [d["id"] for d in prioritize_linked_titles(hits)]
    assert order[:3] == titles[:3]
    assert order.index("Harbor") < order.index("Fifth") < order.index("Port")
