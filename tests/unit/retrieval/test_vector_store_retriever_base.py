"""VectorStore 기반 Retriever 공용 베이스 테스트.

Qdrant/Pinecone/pgvector Retriever가 공유하는
``VectorStoreRetrieverBase`` / ``HybridVectorStoreRetrieverBase``의 공통 흐름을
provider 패키지 없이(Mock) 검증한다:
- Dense 검색 흐름: to_thread 임베딩 → store.search → SearchResult 변환 → 통계
- 컬렉션 속성 이름 선언(_collection_attr)과 health check 차원 선언
- 하이브리드: alpha/Sparse 인코더 조건에 따른 sparse_vector 전달, BM25 전처리 파이프라인
- 문서 관리 메서드: store 미지원 시 NotImplementedError, 청크 집계
"""

from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.core.retrieval.retrievers._vector_store_retriever_base import (
    HybridVectorStoreRetrieverBase,
    VectorStoreRetrieverBase,
)


class _DenseRetriever(VectorStoreRetrieverBase):
    _collection_attr: ClassVar[str] = "table_name"
    _health_check_dimension: ClassVar[int] = 4

    table_name: str

    def __init__(self, embedder: Any, store: Any) -> None:
        super().__init__(embedder=embedder, store=store, collection="docs", top_k=3)


class _HybridRetriever(HybridVectorStoreRetrieverBase):
    _collection_attr: ClassVar[str] = "namespace"

    namespace: str

    def __init__(self, embedder: Any, store: Any, **kwargs: Any) -> None:
        super().__init__(
            embedder=embedder,
            store=store,
            collection="ns",
            top_k=3,
            hybrid_alpha=kwargs.get("hybrid_alpha", 0.6),
            synonym_manager=kwargs.get("synonym_manager"),
            stopword_filter=kwargs.get("stopword_filter"),
            user_dictionary=kwargs.get("user_dictionary"),
        )


def _embedder() -> MagicMock:
    embedder = MagicMock()
    embedder.embed_query.return_value = [0.1, 0.2]
    return embedder


def _store(results: list[dict[str, Any]] | None = None) -> MagicMock:
    store = MagicMock()
    store.search = AsyncMock(
        return_value=results
        if results is not None
        else [{"_id": "d1", "_score": 0.9, "content": "hello", "source": "a.pdf"}]
    )
    return store


@pytest.mark.asyncio
async def test_dense_search_converts_results_and_updates_stats() -> None:
    store = _store()
    retriever = _DenseRetriever(_embedder(), store)

    results = await retriever.search("q", top_k=2, filters={"k": "v"})

    assert retriever.table_name == "docs"
    assert len(results) == 1
    assert results[0].id == "d1"
    assert results[0].score == 0.9
    assert results[0].content == "hello"
    assert results[0].metadata == {"source": "a.pdf"}
    store.search.assert_awaited_once_with(
        collection="docs", query_vector=[0.1, 0.2], top_k=2, filters={"k": "v"}
    )
    assert retriever.stats == {"total_searches": 1, "errors": 0}


@pytest.mark.asyncio
async def test_search_failure_counts_error_and_reraises() -> None:
    store = _store()
    store.search.side_effect = RuntimeError("down")
    retriever = _DenseRetriever(_embedder(), store)

    with pytest.raises(RuntimeError, match="down"):
        await retriever.search("q")

    assert retriever.stats["errors"] == 1
    assert retriever.stats["total_searches"] == 0


@pytest.mark.asyncio
async def test_health_check_uses_declared_dimension() -> None:
    store = _store()
    retriever = _DenseRetriever(_embedder(), store)

    assert await retriever.health_check() is True
    assert store.search.call_args.kwargs["query_vector"] == [0.0] * 4
    assert store.search.call_args.kwargs["collection"] == "docs"

    store.search.side_effect = RuntimeError("down")
    assert await retriever.health_check() is False


@pytest.mark.asyncio
async def test_hybrid_passes_sparse_vector_only_when_encoder_ready_and_alpha_below_one() -> None:
    store = _store()
    retriever = _HybridRetriever(_embedder(), store, hybrid_alpha=0.6)
    assert retriever.namespace == "ns"

    await retriever.search("q")
    assert store.search.call_args.kwargs["sparse_vector"] is None
    assert retriever.stats["hybrid_searches"] == 0

    retriever._sparse_encoder = MagicMock()
    retriever._sparse_encoder.encode.return_value = {"indices": [1], "values": [0.5]}

    await retriever.search("q")
    assert store.search.call_args.kwargs["sparse_vector"] == {"indices": [1], "values": [0.5]}
    assert retriever.stats["hybrid_searches"] == 1

    # alpha 오버라이드 1.0 → Dense 전용
    await retriever.search("q", alpha=1.0)
    assert store.search.call_args.kwargs["sparse_vector"] is None
    assert retriever.stats["hybrid_searches"] == 1


def test_hybrid_preprocess_pipeline_order_and_graceful_degradation() -> None:
    user_dictionary = MagicMock()
    user_dictionary.protect_entries.return_value = ("__T0__ AI", {"__T0__": "머신러닝"})
    user_dictionary.restore_entries.side_effect = lambda text, m: text.replace("__T0__", m["__T0__"])
    synonym_manager = MagicMock()
    synonym_manager.expand_query.side_effect = lambda text: text.replace("AI", "AI 인공지능")
    stopword_filter = MagicMock()
    stopword_filter.filter_text.side_effect = lambda text: text

    retriever = _HybridRetriever(
        _embedder(),
        _store(),
        synonym_manager=synonym_manager,
        stopword_filter=stopword_filter,
        user_dictionary=user_dictionary,
    )

    assert retriever._preprocess_query("머신러닝 AI") == "머신러닝 AI 인공지능"
    assert retriever.stats["bm25_preprocessed"] == 1

    # 전처리 실패 시 원본 쿼리 사용
    synonym_manager.expand_query.side_effect = RuntimeError("boom")
    assert retriever._preprocess_query("머신러닝 AI") == "머신러닝 AI"

    # 전처리 모듈이 없으면 원본 그대로
    plain = _HybridRetriever(_embedder(), _store())
    assert plain._preprocess_query("그대로") == "그대로"


@pytest.mark.asyncio
async def test_document_management_requires_store_support() -> None:
    store = MagicMock(spec=["search"])
    retriever = _DenseRetriever(_embedder(), store)

    with pytest.raises(NotImplementedError):
        await retriever.get_document_chunks("doc-1")
    with pytest.raises(NotImplementedError):
        await retriever.list_documents()
    with pytest.raises(NotImplementedError):
        await retriever.delete_all_documents()


@pytest.mark.asyncio
async def test_document_management_aggregates_chunks_by_document() -> None:
    chunks = [
        {"_id": "c1", "document_id": "doc-1", "content": "a", "source_file": "a.pdf",
         "file_type": "pdf", "created_at": "2026-01-01"},
        {"_id": "c2", "document_id": "doc-1", "content": "bb", "source_file": "a.pdf",
         "file_type": "pdf", "created_at": "2026-01-01"},
        {"_id": "c3", "document_id": "doc-2", "content": "c", "source_file": "b.md",
         "file_type": "md", "created_at": "2026-02-01"},
    ]
    store = _store()
    store.fetch_objects = AsyncMock(
        side_effect=lambda collection, filters=None: [
            c for c in chunks if not filters or c["document_id"] == filters["document_id"]
        ]
    )
    store.delete_objects = AsyncMock()
    retriever = _DenseRetriever(_embedder(), store)

    listed = await retriever.list_documents(page=1, page_size=1)
    assert listed["total_count"] == 2
    assert listed["documents"] == [
        {"id": "doc-1", "filename": "a.pdf", "file_type": "pdf",
         "created_at": "2026-01-01", "chunk_count": 2}
    ]

    details = await retriever.get_document_details("doc-1")
    assert details is not None
    assert details["actual_chunk_count"] == 2
    assert details["file_size"] == 3
    assert await retriever.get_document_details("missing") is None

    assert await retriever.get_document_stats() == {"total_documents": 2, "vector_count": 3}
    info = await retriever.get_collection_info()
    assert info == {
        "collection_name": "docs",
        "total_objects": 3,
        "oldest_document": "2026-01-01",
        "newest_document": "2026-02-01",
    }
    assert [d["id"] for d in await retriever.backup_metadata()] == ["doc-1", "doc-2"]

    assert await retriever.delete_document("doc-2") is True
    store.delete_objects.assert_awaited_once_with(collection="docs", object_ids=["c3"])
    assert await retriever.delete_document("missing") is False

    assert await retriever.delete_all_documents() is True
    assert store.delete_objects.call_args.kwargs["object_ids"] == ["c1", "c2", "c3"]
