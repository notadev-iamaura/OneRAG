"""MongoDBRetriever(하이브리드) 단위 테스트 (GAP #4 차용).

테스트 항목:
1. RetrieverFactory에 'mongodb_hybrid' provider가 하이브리드로 등록됐는지.
2. Client-side RRF($vectorSearch + $search 병렬 → Python RRF) 통합 로직.
3. vector-only fallback(하이브리드 실패 시 dense 검색만).
4. dense_weight/sparse_weight 가중치가 RRF 점수에 반영되는지.

Note:
    pymongo가 필요한 optional-provider 테스트입니다(ONERAG_RUN_OPTIONAL_PROVIDER_TESTS=1).
    실제 MongoDB 연결 없이 Mock collection으로 aggregate 동작을 시뮬레이션합니다.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.modules.core.retrieval.interfaces import SearchResult
from app.modules.core.retrieval.retrievers.factory import RetrieverFactory
from app.modules.core.retrieval.retrievers.mongodb_retriever import MongoDBRetriever


class _MockEmbedder:
    """Mock 임베딩 모델(쿼리를 고정 벡터로 변환)."""

    def embed_query(self, text: str) -> list[float]:
        return [0.1] * 8

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 8 for _ in texts]


def _mock_mongodb_client(
    vector_docs: list[dict[str, Any]] | None = None,
    fulltext_docs: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """ping/get_collection을 갖춘 MongoDBClient Mock을 만든다.

    collection.aggregate는 호출 시 pipeline에 $vectorSearch가 있으면 vector_docs를,
    $search가 있으면 fulltext_docs를 반환하도록 분기한다.
    """
    client = MagicMock()
    client.ping.return_value = True

    collection = MagicMock()

    def _aggregate(pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        stage_keys = {key for stage in pipeline for key in stage}
        if "$vectorSearch" in stage_keys:
            return list(vector_docs or [])
        if "$search" in stage_keys:
            return list(fulltext_docs or [])
        return []

    collection.aggregate.side_effect = _aggregate
    collection.count_documents.return_value = 3
    client.get_collection.return_value = collection
    return client


def test_factory_registers_mongodb_hybrid_provider() -> None:
    """'mongodb_hybrid'가 하이브리드 지원 provider로 등록돼야 한다."""
    assert "mongodb_hybrid" in RetrieverFactory.get_available_providers()
    assert RetrieverFactory.supports_hybrid("mongodb_hybrid") is True
    info = RetrieverFactory.get_provider_info("mongodb_hybrid")
    assert info is not None
    assert info["class_path"].endswith("mongodb_retriever.MongoDBRetriever")
    # 기존 dense 전용 'mongodb'는 그대로 유지(회귀 0)
    assert RetrieverFactory.supports_hybrid("mongodb") is False


def test_factory_creates_mongodb_hybrid_instance() -> None:
    """팩토리로 MongoDBRetriever 인스턴스를 생성할 수 있어야 한다."""
    client = _mock_mongodb_client()
    retriever = RetrieverFactory.create(
        provider="mongodb_hybrid",
        embedder=_MockEmbedder(),
        config={"mongodb_client": client, "collection_name": "documents"},
    )
    assert isinstance(retriever, MongoDBRetriever)
    assert retriever.dense_weight == 0.6
    assert retriever.sparse_weight == 0.4


@pytest.mark.asyncio
async def test_hybrid_search_fuses_vector_and_fulltext() -> None:
    """vector·fulltext 결과를 client-side RRF로 통합해야 한다."""
    vector_docs = [
        {"_id": "doc1", "content": "벡터 상위 문서", "metadata": {}, "score": 0.9},
        {"_id": "doc2", "content": "공통 문서", "metadata": {}, "score": 0.8},
    ]
    fulltext_docs = [
        {"_id": "doc2", "content": "공통 문서", "metadata": {}, "score": 5.0},
        {"_id": "doc3", "content": "BM25 상위 문서", "metadata": {}, "score": 4.0},
    ]
    client = _mock_mongodb_client(vector_docs, fulltext_docs)
    retriever = MongoDBRetriever(
        embedder=_MockEmbedder(), mongodb_client=client, collection_name="documents"
    )
    await retriever.initialize()

    results = await retriever.search("쿼리", top_k=3)

    assert all(isinstance(r, SearchResult) for r in results)
    ids = {r.id for r in results}
    # 두 검색에 모두 등장한 doc2가 최상위(RRF 합산)여야 한다
    assert results[0].id == "doc2"
    # 양쪽 검색 결과가 모두 통합돼야 한다
    assert ids == {"doc1", "doc2", "doc3"}


def test_client_side_rrf_respects_weights() -> None:
    """dense_weight/sparse_weight가 RRF 점수에 반영돼야 한다."""
    retriever = MongoDBRetriever(
        embedder=_MockEmbedder(),
        mongodb_client=_mock_mongodb_client(),
        collection_name="documents",
        dense_weight=0.9,
        sparse_weight=0.1,
    )
    vector_only = [{"_id": "v", "content": "v", "metadata": {}}]
    fulltext_only = [{"_id": "f", "content": "f", "metadata": {}}]
    fused = retriever._client_side_rank_fusion(vector_only, fulltext_only, top_k=2)
    by_id = {r.id: r.score for r in fused}
    # dense 가중이 훨씬 크므로 vector 문서 점수가 fulltext 문서보다 높아야 한다
    assert by_id["v"] > by_id["f"]


@pytest.mark.asyncio
async def test_search_survives_one_branch_failure() -> None:
    """한쪽 검색(fulltext)이 실패해도 다른 쪽(vector) 결과로 graceful 동작한다.

    하이브리드 단계는 asyncio.gather(return_exceptions=True)로 개별 분기 예외를
    흡수하므로, fulltext 인덱스가 없는 환경에서도 vector 결과만으로 통합한다.
    """
    from pymongo.errors import PyMongoError

    client = MagicMock()
    client.ping.return_value = True
    collection = MagicMock()

    def _aggregate(pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        stage_keys = {key for stage in pipeline for key in stage}
        if "$search" in stage_keys:
            raise PyMongoError("fulltext index missing")
        return [{"_id": "v1", "content": "벡터 문서", "metadata": {}, "score": 0.9}]

    collection.aggregate.side_effect = _aggregate
    collection.count_documents.return_value = 1
    client.get_collection.return_value = collection

    retriever = MongoDBRetriever(
        embedder=_MockEmbedder(), mongodb_client=client, collection_name="documents"
    )
    await retriever.initialize()

    results = await retriever.search("쿼리", top_k=2)
    assert [r.id for r in results] == ["v1"]


@pytest.mark.asyncio
async def test_vector_only_fallback_helper() -> None:
    """_vector_search_fallback은 dense 검색만 수행해 SearchResult를 반환한다."""
    client = _mock_mongodb_client(
        vector_docs=[{"_id": "fb", "content": "fallback", "metadata": {}, "score": 0.7}]
    )
    retriever = MongoDBRetriever(
        embedder=_MockEmbedder(), mongodb_client=client, collection_name="documents"
    )
    await retriever.initialize()

    results = await retriever._vector_search_fallback("쿼리", top_k=2)
    assert len(results) == 1
    assert results[0].id == "fb"
    assert isinstance(results[0], SearchResult)
