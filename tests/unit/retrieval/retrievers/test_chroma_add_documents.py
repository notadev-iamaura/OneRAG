"""ChromaRetriever.add_documents 회귀 테스트.

chroma 모드 ingestion 파리티(원본 백포트): 업로드 임베딩 청크를
{id, vector, content, metadata}로 변환해 ChromaVectorStore에 위임하고
{success_count, error_count, total_count, errors} 결과를 반환한다.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.core.retrieval.retrievers.chroma_retriever import ChromaRetriever


def _retriever(store: MagicMock) -> ChromaRetriever:
    embedder = MagicMock()
    embedder.embed_query = MagicMock(return_value=[0.1] * 8)
    return ChromaRetriever(embedder=embedder, store=store, collection_name="documents")


@pytest.mark.asyncio
async def test_add_documents_maps_and_delegates_to_store() -> None:
    store = MagicMock()
    store.add_documents = AsyncMock(return_value=2)
    retriever = _retriever(store)

    docs = [
        {"content": "첫 청크", "embedding": [0.1] * 8, "metadata": {"document_id": "d1", "chunk_index": 0}},
        {"content": "둘째 청크", "embedding": [0.2] * 8, "metadata": {"document_id": "d1", "chunk_index": 1}},
    ]
    result = await retriever.add_documents(docs)

    assert result["success_count"] == 2
    assert result["error_count"] == 0
    assert result["total_count"] == 2

    # store.add_documents가 변환된 포맷으로 호출됐는지 확인
    call = store.add_documents.call_args
    assert call.kwargs["collection"] == "documents"
    prepared = call.kwargs["documents"]
    assert len(prepared) == 2
    assert prepared[0]["content"] == "첫 청크"
    assert prepared[0]["vector"] == [0.1] * 8
    assert prepared[0]["metadata"]["document_id"] == "d1"


@pytest.mark.asyncio
async def test_add_documents_skips_chunks_without_embedding() -> None:
    store = MagicMock()
    store.add_documents = AsyncMock(return_value=1)
    retriever = _retriever(store)

    docs = [
        {"content": "임베딩 있음", "embedding": [0.1] * 8, "metadata": {"document_id": "d1"}},
        {"content": "임베딩 없음", "metadata": {"document_id": "d1"}},  # vector 누락
    ]
    result = await retriever.add_documents(docs)

    # 1개만 store로 전달되고, 누락 청크는 결과 total에 반영
    prepared = store.add_documents.call_args.kwargs["documents"]
    assert len(prepared) == 1
    assert result["total_count"] == 2
    assert result["success_count"] == 1


@pytest.mark.asyncio
async def test_add_documents_all_invalid_returns_error_dict() -> None:
    store = MagicMock()
    store.add_documents = AsyncMock(return_value=0)
    retriever = _retriever(store)

    result = await retriever.add_documents([{"content": "no vector", "metadata": {}}])

    store.add_documents.assert_not_called()
    assert result["success_count"] == 0
    assert result["error_count"] == 1
    assert result["errors"]
