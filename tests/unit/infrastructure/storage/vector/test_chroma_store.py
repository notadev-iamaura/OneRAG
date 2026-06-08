"""
ChromaVectorStore 단위 테스트

IVectorStore 인터페이스를 구현한 ChromaVectorStore 검증.
TDD 방식으로 작성 - 테스트 먼저, 구현 나중.

테스트 케이스:
1. IVectorStore 인터페이스 구현 확인
2. 문서 추가 및 개수 반환
3. 벡터 유사도 검색
4. 필터 기반 삭제
5. in-memory 모드 동작
6. persistent 모드 동작
"""

import asyncio
from typing import Any

import pytest

# chromadb 미설치 환경에서도 테스트 파일 로드 가능하도록 처리
chromadb = pytest.importorskip("chromadb")


class TestChromaVectorStoreInterface:
    """ChromaVectorStore가 IVectorStore 인터페이스를 올바르게 구현하는지 테스트"""

    def test_chroma_store_implements_ivectorstore(self) -> None:
        """ChromaVectorStore가 IVectorStore를 구현하는지 확인"""
        from app.core.interfaces.storage import IVectorStore
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        # in-memory 모드로 생성
        store = ChromaVectorStore()

        assert isinstance(store, IVectorStore)

    def test_chroma_store_has_required_methods(self) -> None:
        """필수 메서드가 모두 구현되어 있는지 확인"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()

        # IVectorStore 인터페이스의 필수 메서드 확인
        assert hasattr(store, "add_documents")
        assert callable(store.add_documents)

        assert hasattr(store, "search")
        assert callable(store.search)

        assert hasattr(store, "delete")
        assert callable(store.delete)


class TestChromaVectorStoreAddDocuments:
    """ChromaVectorStore.add_documents() 테스트"""

    @pytest.mark.asyncio
    async def test_add_documents_returns_count(self) -> None:
        """문서 추가 후 저장된 문서 개수를 반환하는지 확인"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()

        documents: list[dict[str, Any]] = [
            {"id": "doc1", "vector": [0.1, 0.2, 0.3], "metadata": {"title": "문서1"}},
            {"id": "doc2", "vector": [0.4, 0.5, 0.6], "metadata": {"title": "문서2"}},
            {"id": "doc3", "vector": [0.7, 0.8, 0.9], "metadata": {"title": "문서3"}},
        ]

        count = await store.add_documents(collection="test_collection", documents=documents)

        assert count == 3

    @pytest.mark.asyncio
    async def test_add_documents_stores_and_returns_content(self) -> None:
        """본문(content)이 저장되고 검색 결과로 복원되는지 확인(#12 chroma 파리티)."""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()

        documents: list[dict[str, Any]] = [
            {
                "id": "doc-c1",
                "vector": [0.1, 0.2, 0.3],
                "content": "마스코트는 보라색 수달입니다",
                "metadata": {"document_id": "d1"},
            },
        ]
        await store.add_documents(collection="content_collection", documents=documents)

        results = await store.search(
            collection="content_collection", query_vector=[0.1, 0.2, 0.3], top_k=1
        )

        assert len(results) == 1
        assert results[0]["content"] == "마스코트는 보라색 수달입니다"

    @pytest.mark.asyncio
    async def test_add_documents_with_empty_list_returns_zero(self) -> None:
        """빈 문서 리스트 추가 시 0을 반환하는지 확인"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()

        count = await store.add_documents(collection="test_collection", documents=[])

        assert count == 0

    @pytest.mark.asyncio
    async def test_add_documents_upsert_behavior(self) -> None:
        """동일 ID 문서 재추가 시 upsert 동작 확인"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()

        # 첫 번째 추가
        documents: list[dict[str, Any]] = [
            {"id": "doc1", "vector": [0.1, 0.2, 0.3], "metadata": {"title": "원본"}},
        ]
        await store.add_documents(collection="test_collection", documents=documents)

        # 동일 ID로 업데이트
        updated_documents: list[dict[str, Any]] = [
            {"id": "doc1", "vector": [0.9, 0.8, 0.7], "metadata": {"title": "업데이트됨"}},
        ]
        count = await store.add_documents(collection="test_collection", documents=updated_documents)

        assert count == 1

        # 검색으로 업데이트 확인
        results = await store.search(
            collection="test_collection",
            query_vector=[0.9, 0.8, 0.7],
            top_k=1
        )

        assert len(results) == 1
        # 메타데이터가 업데이트 되었는지 확인
        assert results[0].get("title") == "업데이트됨" or results[0].get("metadata", {}).get("title") == "업데이트됨"


class TestChromaVectorStoreSearch:
    """ChromaVectorStore.search() 테스트"""

    @pytest.mark.asyncio
    async def test_search_returns_similar_vectors(self) -> None:
        """유사 벡터 검색이 올바르게 동작하는지 확인"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()

        # 테스트 문서 추가
        documents: list[dict[str, Any]] = [
            {"id": "doc1", "vector": [1.0, 0.0, 0.0], "metadata": {"title": "X축"}},
            {"id": "doc2", "vector": [0.0, 1.0, 0.0], "metadata": {"title": "Y축"}},
            {"id": "doc3", "vector": [0.0, 0.0, 1.0], "metadata": {"title": "Z축"}},
        ]
        await store.add_documents(collection="test_collection", documents=documents)

        # X축과 가장 유사한 벡터 검색
        results = await store.search(
            collection="test_collection",
            query_vector=[0.9, 0.1, 0.0],
            top_k=1
        )

        assert len(results) == 1
        # X축 문서가 가장 유사해야 함
        assert "doc1" in str(results[0].get("_id", results[0].get("id", "")))

    @pytest.mark.asyncio
    async def test_search_respects_top_k(self) -> None:
        """top_k 파라미터가 올바르게 적용되는지 확인"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()

        # 5개 문서 추가
        documents: list[dict[str, Any]] = [
            {"id": f"doc{i}", "vector": [float(i), 0.0, 0.0], "metadata": {"index": i}}
            for i in range(5)
        ]
        await store.add_documents(collection="test_collection", documents=documents)

        # top_k=3으로 검색
        results = await store.search(
            collection="test_collection",
            query_vector=[2.5, 0.0, 0.0],
            top_k=3
        )

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_search_with_filters(self) -> None:
        """필터가 적용된 검색이 올바르게 동작하는지 확인"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()

        # 카테고리가 다른 문서들 추가
        documents: list[dict[str, Any]] = [
            {"id": "doc1", "vector": [1.0, 0.0, 0.0], "metadata": {"category": "A"}},
            {"id": "doc2", "vector": [0.9, 0.1, 0.0], "metadata": {"category": "B"}},
            {"id": "doc3", "vector": [0.8, 0.2, 0.0], "metadata": {"category": "A"}},
        ]
        await store.add_documents(collection="test_collection", documents=documents)

        # category A만 필터링
        results = await store.search(
            collection="test_collection",
            query_vector=[1.0, 0.0, 0.0],
            top_k=10,
            filters={"category": "A"}
        )

        # category가 A인 문서만 반환되어야 함
        assert len(results) == 2
        for result in results:
            category = result.get("category") or result.get("metadata", {}).get("category")
            assert category == "A"

    @pytest.mark.asyncio
    async def test_search_empty_collection_returns_empty_list(self) -> None:
        """빈 컬렉션 검색 시 빈 리스트 반환"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()

        results = await store.search(
            collection="empty_collection",
            query_vector=[0.1, 0.2, 0.3],
            top_k=10
        )

        assert results == []


class TestChromaVectorStoreDelete:
    """ChromaVectorStore.delete() 테스트"""

    @pytest.mark.asyncio
    async def test_delete_by_id_returns_count(self) -> None:
        """ID로 삭제 후 삭제된 개수 반환"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()

        # 문서 추가
        documents: list[dict[str, Any]] = [
            {"id": "doc1", "vector": [0.1, 0.2, 0.3], "metadata": {"title": "문서1"}},
            {"id": "doc2", "vector": [0.4, 0.5, 0.6], "metadata": {"title": "문서2"}},
        ]
        await store.add_documents(collection="test_collection", documents=documents)

        # doc1 삭제
        deleted_count = await store.delete(
            collection="test_collection",
            filters={"id": "doc1"}
        )

        assert deleted_count == 1

        # 삭제 확인: doc1은 검색되지 않아야 함
        results = await store.search(
            collection="test_collection",
            query_vector=[0.1, 0.2, 0.3],
            top_k=10
        )

        result_ids = [str(r.get("_id", r.get("id", ""))) for r in results]
        assert "doc1" not in result_ids

    @pytest.mark.asyncio
    async def test_delete_multiple_by_ids(self) -> None:
        """여러 ID로 삭제"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()

        # 문서 추가
        documents: list[dict[str, Any]] = [
            {"id": "doc1", "vector": [0.1, 0.2, 0.3], "metadata": {"title": "문서1"}},
            {"id": "doc2", "vector": [0.4, 0.5, 0.6], "metadata": {"title": "문서2"}},
            {"id": "doc3", "vector": [0.7, 0.8, 0.9], "metadata": {"title": "문서3"}},
        ]
        await store.add_documents(collection="test_collection", documents=documents)

        # doc1, doc2 삭제
        deleted_count = await store.delete(
            collection="test_collection",
            filters={"ids": ["doc1", "doc2"]}
        )

        assert deleted_count == 2

    @pytest.mark.asyncio
    async def test_delete_nonexistent_document_returns_zero(self) -> None:
        """존재하지 않는 문서 삭제 시 0 반환"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()

        # 빈 컬렉션에서 삭제 시도
        deleted_count = await store.delete(
            collection="test_collection",
            filters={"id": "nonexistent"}
        )

        assert deleted_count == 0


class TestChromaVectorStoreModes:
    """ChromaVectorStore 모드 테스트 (in-memory, persistent)"""

    def test_in_memory_mode_default(self) -> None:
        """기본값이 in-memory 모드인지 확인"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        # persist_directory 없이 생성하면 in-memory
        store = ChromaVectorStore()

        assert store is not None
        # 내부 클라이언트가 정상 생성되었는지 확인
        assert store._client is not None

    def test_persistent_mode_with_directory(self, tmp_path: Any) -> None:
        """persist_directory 설정 시 persistent 모드로 동작"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        persist_dir = str(tmp_path / "chroma_data")

        store = ChromaVectorStore(persist_directory=persist_dir)

        assert store is not None
        assert store._client is not None


class TestChromaVectorStoreAsyncWrapper:
    """ChromaVectorStore의 비동기 래핑 테스트"""

    @pytest.mark.asyncio
    async def test_add_documents_is_async(self) -> None:
        """add_documents가 비동기로 실행되는지 확인"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()

        # asyncio.iscoroutinefunction으로 코루틴 함수인지 확인
        assert asyncio.iscoroutinefunction(store.add_documents)

    @pytest.mark.asyncio
    async def test_search_is_async(self) -> None:
        """search가 비동기로 실행되는지 확인"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()

        assert asyncio.iscoroutinefunction(store.search)

    @pytest.mark.asyncio
    async def test_delete_is_async(self) -> None:
        """delete가 비동기로 실행되는지 확인"""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()

        assert asyncio.iscoroutinefunction(store.delete)


class TestChromaVectorStoreFactoryIntegration:
    """ChromaVectorStore와 VectorStoreFactory 통합 테스트"""

    def test_chroma_registered_in_factory(self) -> None:
        """chroma가 VectorStoreFactory에 등록되어 있는지 확인"""
        from app.infrastructure.storage.vector.factory import VectorStoreFactory

        providers = VectorStoreFactory.get_available_providers()

        assert "chroma" in providers

    def test_factory_creates_chroma_store(self) -> None:
        """VectorStoreFactory를 통해 ChromaVectorStore 생성"""
        from app.core.interfaces.storage import IVectorStore
        from app.infrastructure.storage.vector.factory import VectorStoreFactory

        store = VectorStoreFactory.create(
            provider="chroma",
            config={}  # in-memory 모드
        )

        assert isinstance(store, IVectorStore)


class TestChromaVectorStoreDocumentManagement:
    """fetch_objects / delete_objects / metadata_json 라운드트립 (chroma 파리티 백포트)"""

    @pytest.mark.asyncio
    async def test_fetch_objects_and_delete_objects_roundtrip(self) -> None:
        """fetch_objects로 조회, delete_objects로 삭제가 동작해야 한다(문서관리)."""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()
        docs: list[dict[str, Any]] = [
            {
                "id": "x1",
                "vector": [0.1, 0.2, 0.3],
                "content": "안녕하세요",
                "metadata": {"document_id": "d1"},
            },
        ]
        await store.add_documents(collection="mgmt", documents=docs)

        fetched = await store.fetch_objects(collection="mgmt", filters={"document_id": "d1"})
        assert len(fetched) == 1
        assert fetched[0]["_id"] == "x1"
        assert fetched[0]["content"] == "안녕하세요"

        deleted = await store.delete_objects(collection="mgmt", object_ids=["x1"])
        assert deleted == 1

        after = await store.fetch_objects(collection="mgmt", filters={"document_id": "d1"})
        assert after == []

    @pytest.mark.asyncio
    async def test_metadata_json_restored_on_read(self) -> None:
        """비기본 메타데이터(list)가 round-trip에서 복원되고 metadata_json은 노출되지 않아야 한다."""
        from app.infrastructure.storage.vector.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()
        docs: list[dict[str, Any]] = [
            {
                "id": "m1",
                "vector": [0.1, 0.2, 0.3],
                "content": "본문",
                "metadata": {"document_id": "d1", "keywords": ["a", "b"]},
            },
        ]
        await store.add_documents(collection="meta", documents=docs)

        results = await store.search(collection="meta", query_vector=[0.1, 0.2, 0.3], top_k=1)
        assert results[0].get("keywords") == ["a", "b"]
        assert "metadata_json" not in results[0]

        fetched = await store.fetch_objects(collection="meta", filters={"document_id": "d1"})
        assert fetched[0].get("keywords") == ["a", "b"]
        assert "metadata_json" not in fetched[0]
