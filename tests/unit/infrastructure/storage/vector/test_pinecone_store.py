"""
PineconeVectorStore 단위 테스트

IVectorStore 인터페이스를 구현한 Pinecone 서버리스 어댑터 검증.
TDD 방식으로 작성 - 테스트 먼저, 구현 나중.

테스트 케이스:
1. IVectorStore 인터페이스 구현 확인
2. 문서 추가 및 개수 반환
3. 벡터 유사도 검색 (Dense)
4. 하이브리드 검색 (Dense + Sparse)
5. 필터 기반 삭제
6. 네임스페이스(collection) 기반 분리

의존성:
- pinecone-client v3+: pip install pinecone-client
"""

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

# pinecone 미설치 환경에서도 테스트 파일 로드 가능하도록 처리
pinecone = pytest.importorskip("pinecone")


def create_mock_pinecone_store() -> tuple[MagicMock, MagicMock, Any]:
    """테스트용 Mock Pinecone 클라이언트와 인덱스 생성"""
    mock_client = MagicMock()
    mock_index = MagicMock()
    mock_client.Index.return_value = mock_index

    from app.infrastructure.storage.vector.pinecone_store import PineconeVectorStore
    store = PineconeVectorStore(api_key="test-api-key", _client=mock_client)

    return mock_client, mock_index, store


class TestPineconeVectorStoreInterface:
    """PineconeVectorStore가 IVectorStore 인터페이스를 올바르게 구현하는지 테스트"""

    def test_pinecone_store_implements_ivectorstore(self) -> None:
        """PineconeVectorStore가 IVectorStore를 구현하는지 확인"""
        from app.core.interfaces.storage import IVectorStore

        _, _, store = create_mock_pinecone_store()

        assert isinstance(store, IVectorStore)

    def test_pinecone_store_has_required_methods(self) -> None:
        """필수 메서드가 모두 구현되어 있는지 확인"""
        _, _, store = create_mock_pinecone_store()

        # IVectorStore 인터페이스의 필수 메서드 확인
        assert hasattr(store, "add_documents")
        assert callable(store.add_documents)

        assert hasattr(store, "search")
        assert callable(store.search)

        assert hasattr(store, "delete")
        assert callable(store.delete)


class TestPineconeVectorStoreAddDocuments:
    """PineconeVectorStore.add_documents() 테스트"""

    @pytest.mark.asyncio
    async def test_add_documents_returns_count(self) -> None:
        """문서 추가 후 저장된 문서 개수를 반환하는지 확인"""
        _, mock_index, store = create_mock_pinecone_store()
        # upsert는 성공 시 upserted_count 반환
        mock_index.upsert.return_value = MagicMock(upserted_count=3)

        documents: list[dict[str, Any]] = [
            {"id": "doc1", "vector": [0.1, 0.2, 0.3], "metadata": {"title": "문서1"}},
            {"id": "doc2", "vector": [0.4, 0.5, 0.6], "metadata": {"title": "문서2"}},
            {"id": "doc3", "vector": [0.7, 0.8, 0.9], "metadata": {"title": "문서3"}},
        ]

        count = await store.add_documents(collection="test_namespace", documents=documents)

        assert count == 3
        # upsert 호출 확인
        mock_index.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_documents_with_empty_list_returns_zero(self) -> None:
        """빈 문서 리스트 추가 시 0을 반환하는지 확인"""
        _, mock_index, store = create_mock_pinecone_store()

        count = await store.add_documents(collection="test_namespace", documents=[])

        assert count == 0
        # 빈 리스트일 때 upsert 호출하지 않음
        mock_index.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_documents_with_sparse_values(self) -> None:
        """Sparse Vector 포함 문서 추가 테스트 (하이브리드 검색 지원)"""
        _, mock_index, store = create_mock_pinecone_store()
        mock_index.upsert.return_value = MagicMock(upserted_count=1)

        # Sparse Vector가 포함된 문서
        documents: list[dict[str, Any]] = [
            {
                "id": "doc1",
                "vector": [0.1, 0.2, 0.3],
                "metadata": {"title": "하이브리드 문서"},
                "sparse_values": {"indices": [0, 5, 10], "values": [0.5, 0.3, 0.2]},
            },
        ]

        count = await store.add_documents(collection="test_namespace", documents=documents)

        assert count == 1
        # upsert 호출 시 sparse_values가 포함되었는지 확인
        call_args = mock_index.upsert.call_args
        vectors = call_args.kwargs.get("vectors") or call_args[1].get("vectors") or call_args[0][0]
        # 첫 번째 벡터에 sparse_values가 포함되어야 함
        assert "sparse_values" in vectors[0] or hasattr(vectors[0], "sparse_values")

    @pytest.mark.asyncio
    async def test_add_documents_uses_namespace_as_collection(self) -> None:
        """collection 파라미터가 Pinecone namespace로 사용되는지 확인"""
        _, mock_index, store = create_mock_pinecone_store()
        mock_index.upsert.return_value = MagicMock(upserted_count=1)

        documents: list[dict[str, Any]] = [
            {"id": "doc1", "vector": [0.1, 0.2, 0.3], "metadata": {"title": "문서1"}},
        ]

        await store.add_documents(collection="my_namespace", documents=documents)

        # upsert 호출 시 namespace 파라미터 확인
        call_args = mock_index.upsert.call_args
        namespace = call_args.kwargs.get("namespace")
        assert namespace == "my_namespace"


class TestPineconeVectorStoreSearch:
    """PineconeVectorStore.search() 테스트"""

    @pytest.mark.asyncio
    async def test_search_returns_results(self) -> None:
        """벡터 검색이 결과를 반환하는지 확인"""
        _, mock_index, store = create_mock_pinecone_store()

        # 검색 결과 Mock
        mock_match = MagicMock()
        mock_match.id = "doc1"
        mock_match.score = 0.95
        mock_match.metadata = {"title": "문서1"}

        mock_query_result = MagicMock()
        mock_query_result.matches = [mock_match]
        mock_index.query.return_value = mock_query_result

        results = await store.search(
            collection="test_namespace",
            query_vector=[0.1, 0.2, 0.3],
            top_k=5,
        )

        assert len(results) == 1
        assert results[0]["_id"] == "doc1"
        assert results[0]["_score"] == 0.95
        assert results[0]["title"] == "문서1"

    @pytest.mark.asyncio
    async def test_search_respects_top_k(self) -> None:
        """top_k 파라미터가 올바르게 적용되는지 확인"""
        _, mock_index, store = create_mock_pinecone_store()
        mock_index.query.return_value = MagicMock(matches=[])

        await store.search(
            collection="test_namespace",
            query_vector=[0.1, 0.2, 0.3],
            top_k=10,
        )

        # query 호출 시 top_k 확인
        call_args = mock_index.query.call_args
        top_k = call_args.kwargs.get("top_k")
        assert top_k == 10

    @pytest.mark.asyncio
    async def test_search_with_filters(self) -> None:
        """메타데이터 필터가 적용된 검색 테스트"""
        _, mock_index, store = create_mock_pinecone_store()
        mock_index.query.return_value = MagicMock(matches=[])

        await store.search(
            collection="test_namespace",
            query_vector=[0.1, 0.2, 0.3],
            top_k=5,
            filters={"category": "tech"},
        )

        # query 호출 시 filter 파라미터 확인
        call_args = mock_index.query.call_args
        filter_param = call_args.kwargs.get("filter")
        assert filter_param == {"category": "tech"}

    @pytest.mark.asyncio
    async def test_hybrid_search_with_sparse_vector(self) -> None:
        """Sparse Vector를 사용한 하이브리드 검색 테스트"""
        _, mock_index, store = create_mock_pinecone_store()
        mock_index.query.return_value = MagicMock(matches=[])

        sparse_vector = {"indices": [0, 5, 10], "values": [0.5, 0.3, 0.2]}

        # search 메서드에 sparse_vector 파라미터 추가 (인터페이스 확장)
        # IVectorStore.search()의 시그니처를 따르되 추가 파라미터 지원
        await store.search(
            collection="test_namespace",
            query_vector=[0.1, 0.2, 0.3],
            top_k=5,
            sparse_vector=sparse_vector,
        )

        # query 호출 시 sparse_vector 확인
        call_args = mock_index.query.call_args
        sparse_param = call_args.kwargs.get("sparse_vector")
        assert sparse_param is not None

    @pytest.mark.asyncio
    async def test_search_empty_collection_returns_empty_list(self) -> None:
        """빈 네임스페이스 검색 시 빈 리스트 반환"""
        _, mock_index, store = create_mock_pinecone_store()
        mock_index.query.return_value = MagicMock(matches=[])

        results = await store.search(
            collection="empty_namespace",
            query_vector=[0.1, 0.2, 0.3],
            top_k=10,
        )

        assert results == []


class TestPineconeVectorStoreDelete:
    """PineconeVectorStore.delete() 테스트"""

    @pytest.mark.asyncio
    async def test_delete_by_id_returns_count(self) -> None:
        """ID로 삭제 후 삭제된 개수 반환"""
        _, mock_index, store = create_mock_pinecone_store()
        # delete는 응답을 반환하지 않으므로 삭제 시도한 개수를 반환
        mock_index.delete.return_value = {}

        deleted_count = await store.delete(
            collection="test_namespace",
            filters={"id": "doc1"},
        )

        assert deleted_count == 1
        # delete 호출 시 ids 파라미터 확인
        call_args = mock_index.delete.call_args
        ids = call_args.kwargs.get("ids")
        assert ids == ["doc1"]

    @pytest.mark.asyncio
    async def test_delete_multiple_by_ids(self) -> None:
        """여러 ID로 삭제"""
        _, mock_index, store = create_mock_pinecone_store()
        mock_index.delete.return_value = {}

        deleted_count = await store.delete(
            collection="test_namespace",
            filters={"ids": ["doc1", "doc2", "doc3"]},
        )

        assert deleted_count == 3
        # delete 호출 시 ids 파라미터 확인
        call_args = mock_index.delete.call_args
        ids = call_args.kwargs.get("ids")
        assert ids == ["doc1", "doc2", "doc3"]

    @pytest.mark.asyncio
    async def test_delete_by_filter(self) -> None:
        """메타데이터 필터로 삭제"""
        _, mock_index, store = create_mock_pinecone_store()
        mock_index.delete.return_value = {}

        # Pinecone은 filter 기반 삭제 지원
        deleted_count = await store.delete(
            collection="test_namespace",
            filters={"category": "old"},
        )

        # 필터 기반 삭제는 개수를 정확히 알 수 없으므로 -1 또는 특정 값 반환
        # 구현에 따라 다름
        assert isinstance(deleted_count, int)


class TestPineconeVectorStoreFetchObjects:
    """PineconeVectorStore.fetch_objects() 테스트 (문서관리 위임 대상)"""

    @staticmethod
    def _make_vector(vec_id: str, metadata: dict[str, Any]) -> MagicMock:
        """Pinecone FetchResponse.vectors의 단일 Vector를 흉내내는 fake."""
        vec = MagicMock()
        vec.id = vec_id
        vec.metadata = metadata
        return vec

    @staticmethod
    def _make_list_page(ids: list[str], next_token: str | None) -> MagicMock:
        """list_paginated 응답을 흉내내는 fake (vectors[].id, pagination.next)."""
        page = MagicMock()
        page.vectors = [MagicMock(id=i) for i in ids]
        if next_token is None:
            page.pagination = None
        else:
            pagination = MagicMock()
            pagination.next = next_token
            page.pagination = pagination
        return page

    @pytest.mark.asyncio
    async def test_fetch_objects_by_ids_uses_fetch(self) -> None:
        """ids 필터는 list_paginated 없이 fetch로 직접 조회한다"""
        _, mock_index, store = create_mock_pinecone_store()
        fetch_response = MagicMock()
        fetch_response.vectors = {
            "id-1": self._make_vector(
                "id-1", {"content": "본문1", "document_id": "doc-1"}
            ),
        }
        mock_index.fetch.return_value = fetch_response

        results = await store.fetch_objects(
            collection="ns", filters={"ids": ["id-1"]}
        )

        # list_paginated는 호출되지 않아야 함 (직접 ID 조회)
        mock_index.list_paginated.assert_not_called()
        # fetch가 올바른 ids/namespace로 호출되었는지 확인
        call = mock_index.fetch.call_args
        assert call.kwargs.get("ids") == ["id-1"]
        assert call.kwargs.get("namespace") == "ns"
        # chroma_store 파리티 반환 형태 검증
        assert len(results) == 1
        assert results[0]["_id"] == "id-1"
        assert results[0]["content"] == "본문1"
        assert results[0]["document_id"] == "doc-1"

    @pytest.mark.asyncio
    async def test_fetch_objects_all_lists_then_fetches(self) -> None:
        """필터 없으면 list_paginated로 전체 ID 수집 후 fetch로 메타데이터 조회"""
        _, mock_index, store = create_mock_pinecone_store()
        # 2페이지에 걸친 ID 목록
        mock_index.list_paginated.side_effect = [
            self._make_list_page(["id-1"], next_token="tok-2"),
            self._make_list_page(["id-2"], next_token=None),
        ]
        fetch_response = MagicMock()
        fetch_response.vectors = {
            "id-1": self._make_vector("id-1", {"content": "a", "document_id": "doc-1"}),
            "id-2": self._make_vector("id-2", {"content": "b", "document_id": "doc-2"}),
        }
        mock_index.fetch.return_value = fetch_response

        results = await store.fetch_objects(collection="ns")

        # list_paginated가 페이지네이션으로 2회 호출됐는지 확인
        assert mock_index.list_paginated.call_count == 2
        second_call = mock_index.list_paginated.call_args_list[1]
        assert second_call.kwargs.get("pagination_token") == "tok-2"
        # fetch가 수집된 ID로 호출됐는지 확인
        fetch_call = mock_index.fetch.call_args
        assert sorted(fetch_call.kwargs.get("ids")) == ["id-1", "id-2"]
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_fetch_objects_metadata_filter(self) -> None:
        """전수 조회 후 메타데이터 필터로 메모리 필터링한다"""
        _, mock_index, store = create_mock_pinecone_store()
        mock_index.list_paginated.return_value = self._make_list_page(
            ["id-1", "id-2"], next_token=None
        )
        fetch_response = MagicMock()
        fetch_response.vectors = {
            "id-1": self._make_vector("id-1", {"content": "a", "document_id": "doc-1"}),
            "id-2": self._make_vector("id-2", {"content": "b", "document_id": "doc-2"}),
        }
        mock_index.fetch.return_value = fetch_response

        results = await store.fetch_objects(
            collection="ns", filters={"document_id": "doc-1"}
        )

        assert len(results) == 1
        assert results[0]["_id"] == "id-1"

    @pytest.mark.asyncio
    async def test_delete_objects_delegates_to_delete(self) -> None:
        """delete_objects는 fetch_objects의 _id를 그대로 사용해 삭제한다"""
        _, mock_index, store = create_mock_pinecone_store()
        mock_index.delete.return_value = {}

        deleted = await store.delete_objects(
            collection="ns", object_ids=["id-1", "id-2"]
        )

        assert deleted == 2
        call = mock_index.delete.call_args
        assert call.kwargs.get("ids") == ["id-1", "id-2"]
        assert call.kwargs.get("namespace") == "ns"

    @pytest.mark.asyncio
    async def test_delete_objects_empty_is_noop(self) -> None:
        """빈 ID 목록은 삭제 호출 없이 0을 반환한다"""
        _, mock_index, store = create_mock_pinecone_store()

        deleted = await store.delete_objects(collection="ns", object_ids=[])

        assert deleted == 0
        mock_index.delete.assert_not_called()


class TestPineconeVectorStoreConfiguration:
    """PineconeVectorStore 설정 테스트"""

    def test_init_with_api_key(self) -> None:
        """API 키로 초기화 (클라이언트 주입 방식)"""
        mock_client = MagicMock()
        mock_index = MagicMock()
        mock_client.Index.return_value = mock_index

        from app.infrastructure.storage.vector.pinecone_store import PineconeVectorStore
        store = PineconeVectorStore(api_key="my-api-key", _client=mock_client)

        # api_key 속성이 올바르게 저장되었는지 확인
        assert store.api_key == "my-api-key"

    def test_init_with_custom_index_name(self) -> None:
        """커스텀 인덱스 이름으로 초기화"""
        mock_client = MagicMock()
        mock_index = MagicMock()
        mock_client.Index.return_value = mock_index

        from app.infrastructure.storage.vector.pinecone_store import PineconeVectorStore
        PineconeVectorStore(
            api_key="my-api-key",
            index_name="custom-index",
            _client=mock_client,
        )

        # Index 메서드가 커스텀 인덱스 이름으로 호출되었는지 확인
        mock_client.Index.assert_called_with("custom-index")


class TestPineconeVectorStoreAsyncWrapper:
    """PineconeVectorStore의 비동기 래핑 테스트"""

    @pytest.mark.asyncio
    async def test_add_documents_is_async(self) -> None:
        """add_documents가 비동기로 실행되는지 확인"""
        _, _, store = create_mock_pinecone_store()

        assert asyncio.iscoroutinefunction(store.add_documents)

    @pytest.mark.asyncio
    async def test_search_is_async(self) -> None:
        """search가 비동기로 실행되는지 확인"""
        _, _, store = create_mock_pinecone_store()

        assert asyncio.iscoroutinefunction(store.search)

    @pytest.mark.asyncio
    async def test_delete_is_async(self) -> None:
        """delete가 비동기로 실행되는지 확인"""
        _, _, store = create_mock_pinecone_store()

        assert asyncio.iscoroutinefunction(store.delete)


class TestPineconeVectorStoreFactoryIntegration:
    """PineconeVectorStore와 VectorStoreFactory 통합 테스트"""

    def test_pinecone_registered_in_factory(self) -> None:
        """pinecone이 VectorStoreFactory에 등록되어 있는지 확인"""
        from app.infrastructure.storage.vector.factory import VectorStoreFactory

        providers = VectorStoreFactory.get_available_providers()

        assert "pinecone" in providers

    def test_factory_creates_pinecone_store(self) -> None:
        """VectorStoreFactory를 통해 PineconeVectorStore 생성"""
        from app.core.interfaces.storage import IVectorStore
        from app.infrastructure.storage.vector.factory import VectorStoreFactory

        # Mock 클라이언트 생성
        mock_client = MagicMock()
        mock_index = MagicMock()
        mock_client.Index.return_value = mock_index

        # _client 파라미터로 Mock 주입
        store = VectorStoreFactory.create(
            provider="pinecone",
            config={"api_key": "test-api-key", "_client": mock_client},
        )

        assert isinstance(store, IVectorStore)
