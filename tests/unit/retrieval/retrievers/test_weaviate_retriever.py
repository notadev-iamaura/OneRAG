"""
Weaviate Retriever 단위 테스트

현재 커버리지: 0%
목표 커버리지: 70-80%

테스트 전략:
1. 연결 및 초기화 테스트
2. 하이브리드 검색 (alpha 파라미터 변화)
3. 빈 결과 및 에러 핸들링
4. BM25 전처리 파이프라인
5. 문서 업로드 및 cleanup
"""

from typing import Any
from unittest.mock import MagicMock

import pytest


class TestWeaviateRetrieverConnection:
    """Weaviate 연결 및 초기화 테스트"""

    @pytest.fixture
    def mock_embedder(self) -> MagicMock:
        """Mock Embedder"""
        embedder = MagicMock()
        embedder.embed_query = MagicMock(return_value=[0.1] * 3072)
        return embedder

    @pytest.fixture
    def mock_weaviate_client(self) -> MagicMock:
        """Mock Weaviate Client"""
        client = MagicMock()
        client.is_ready = MagicMock(return_value=True)

        # Mock collection
        mock_collection = MagicMock()
        client.get_collection = MagicMock(return_value=mock_collection)

        return client

    @pytest.mark.asyncio
    async def test_initialization_success(
        self, mock_embedder: MagicMock, mock_weaviate_client: MagicMock
    ) -> None:
        """
        Weaviate 연결 성공 테스트

        Given: 유효한 Weaviate 클라이언트와 설정
        When: WeaviateRetriever 초기화
        Then: 연결 성공, 컬렉션 초기화 완료
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        # Retriever 생성
        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
            alpha=0.6,
        )

        # 초기화
        await retriever.initialize()

        # 검증: 컬렉션이 초기화되었는지
        assert retriever.collection is not None
        mock_weaviate_client.get_collection.assert_called_once_with("Documents")

    @pytest.mark.asyncio
    async def test_initialization_weaviate_not_ready(
        self, mock_embedder: MagicMock, mock_weaviate_client: MagicMock
    ) -> None:
        """
        Weaviate 연결 실패 시 명시적 에러 발생 테스트

        Given: Weaviate가 준비되지 않음
        When: WeaviateRetriever 초기화 시도
        Then: ConnectionError 발생 (해결 방법 포함)
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        # Weaviate 준비 안 됨
        mock_weaviate_client.is_ready = MagicMock(return_value=False)

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )

        # 초기화 시도 - ConnectionError 발생해야 함
        with pytest.raises(ConnectionError) as exc_info:
            await retriever.initialize()

        # 에러 메시지 검증
        error_msg = str(exc_info.value)
        assert "Weaviate 벡터 데이터베이스에 연결할 수 없습니다" in error_msg
        assert "해결 방법:" in error_msg

    @pytest.mark.asyncio
    async def test_initialization_collection_not_found(
        self, mock_embedder: MagicMock, mock_weaviate_client: MagicMock
    ) -> None:
        """
        컬렉션을 찾을 수 없을 때 명시적 에러 발생 테스트

        Given: Weaviate는 준비되었지만 컬렉션이 없음
        When: WeaviateRetriever 초기화
        Then: RuntimeError 발생 (해결 방법 포함)
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        # 컬렉션 반환 None
        mock_weaviate_client.get_collection = MagicMock(return_value=None)

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="NonExistent",
        )

        # 초기화 시도 - RuntimeError 발생해야 함
        with pytest.raises(RuntimeError) as exc_info:
            await retriever.initialize()

        # 에러 메시지 검증
        error_msg = str(exc_info.value)
        assert "Weaviate 'Documents' 컬렉션이 존재하지 않습니다" in error_msg
        assert "해결 방법:" in error_msg


class TestWeaviateRetrieverSearch:
    """Weaviate 검색 테스트"""

    @pytest.fixture
    def mock_embedder(self) -> MagicMock:
        """Mock Embedder"""
        embedder = MagicMock()
        embedder.embed_query = MagicMock(return_value=[0.1] * 3072)
        return embedder

    @pytest.fixture
    def mock_collection(self) -> MagicMock:
        """Mock Weaviate Collection with hybrid query"""
        collection = MagicMock()

        # Mock query.hybrid() 체인
        mock_query = MagicMock()
        mock_response = MagicMock()

        # Mock result objects
        mock_obj1 = MagicMock()
        mock_obj1.uuid = "uuid-1"
        mock_obj1.properties = {
            "content": "테스트 문서 1",
            "source_file": "test1.md",
            "file_type": "MARKDOWN",
        }
        mock_obj1.metadata = MagicMock()
        mock_obj1.metadata.score = 0.95

        mock_obj2 = MagicMock()
        mock_obj2.uuid = "uuid-2"
        mock_obj2.properties = {
            "content": "테스트 문서 2",
            "source_file": "test2.md",
            "file_type": "MARKDOWN",
        }
        mock_obj2.metadata = MagicMock()
        mock_obj2.metadata.score = 0.85

        mock_response.objects = [mock_obj1, mock_obj2]

        mock_query.hybrid = MagicMock(return_value=mock_response)
        collection.query = mock_query

        return collection

    @pytest.fixture
    def mock_weaviate_client(self, mock_collection: MagicMock) -> MagicMock:
        """Mock Weaviate Client"""
        client = MagicMock()
        client.is_ready = MagicMock(return_value=True)
        client.get_collection = MagicMock(return_value=mock_collection)
        return client

    @pytest.mark.asyncio
    async def test_hybrid_search_with_default_alpha(
        self,
        mock_embedder: MagicMock,
        mock_weaviate_client: MagicMock,
        mock_collection: MagicMock,
    ) -> None:
        """
        하이브리드 검색 - 기본 alpha 값 테스트

        Given: alpha=0.6 (기본값, 벡터 60% + BM25 40%)
        When: 하이브리드 검색 수행
        Then: 검색 결과 반환, hybrid 메서드 호출됨
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
            alpha=0.6,
        )

        # 수동 컬렉션 설정 (initialize 건너뛰기)
        retriever.collection = mock_collection

        # 검색 수행
        results = await retriever.search(query="테스트 쿼리", top_k=10)

        # 검증: 결과 반환
        assert len(results) == 2
        assert results[0].content == "테스트 문서 1"
        assert results[0].score == 0.95
        assert results[1].content == "테스트 문서 2"

        # hybrid 메서드가 호출되었는지 확인
        mock_collection.query.hybrid.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_results_handling(
        self,
        mock_embedder: MagicMock,
        mock_weaviate_client: MagicMock,
    ) -> None:
        """
        빈 결과 처리 테스트

        Given: 검색 결과가 없는 경우
        When: 검색 수행
        Then: 빈 리스트 반환, 에러 없음
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        # Mock collection with empty results
        mock_collection = MagicMock()
        mock_query = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = []  # 빈 결과
        mock_query.hybrid = MagicMock(return_value=mock_response)
        mock_collection.query = mock_query

        mock_weaviate_client.get_collection = MagicMock(return_value=mock_collection)

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )

        retriever.collection = mock_collection

        # 검색 수행
        results = await retriever.search(query="존재하지 않는 문서", top_k=10)

        # 검증: 빈 리스트 반환
        assert results == []

    @pytest.mark.asyncio
    async def test_search_passes_metadata_filters_to_weaviate(
        self,
        mock_embedder: MagicMock,
        mock_weaviate_client: MagicMock,
        mock_collection: MagicMock,
    ) -> None:
        """
        메타데이터 필터 전달 테스트

        Given: file_type 필터가 지정됨
        When: Weaviate 검색 수행
        Then: hybrid 호출에 filters 인자가 전달됨
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )
        retriever.collection = mock_collection

        await retriever.search(query="테스트 쿼리", top_k=10, filters={"file_type": "PDF"})

        call_kwargs = mock_collection.query.hybrid.call_args.kwargs
        assert "filters" in call_kwargs

    def test_metadata_filter_normalizes_case_folded_text(
        self,
        mock_embedder: MagicMock,
        mock_weaviate_client: MagicMock,
    ) -> None:
        """#12: file_type 같은 소문자 저장 필드는 필터 값도 소문자로 정규화한다."""
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )

        # file_type은 저장 규칙과 동일하게 소문자화되어야 매칭이 성립한다.
        assert retriever._normalize_metadata_property("file_type", "PDF") == "pdf"
        # 정확매칭 키(document_id 등)는 절대 소문자화하면 안 된다(대소문자 보존).
        assert retriever._normalize_metadata_property("document_id", "AbC123") == "AbC123"

    def test_metadata_filter_rejects_unsupported_keys(
        self,
        mock_embedder: MagicMock,
        mock_weaviate_client: MagicMock,
    ) -> None:
        """미지원 필터 키는 silent drop 대신 fail-closed"""
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )

        with pytest.raises(ValueError, match="Unsupported Weaviate retrieval filters"):
            retriever._build_metadata_filter({"unknown_property": "x"})

    @pytest.mark.asyncio
    async def test_search_with_uninitialized_collection(
        self,
        mock_embedder: MagicMock,
        mock_weaviate_client: MagicMock,
    ) -> None:
        """
        초기화되지 않은 컬렉션으로 검색 시도 테스트

        Given: 컬렉션이 None (초기화 안 됨)
        When: 검색 시도
        Then: RuntimeError 발생 (해결 방법 포함)
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )

        # 컬렉션 초기화 안 함 (collection=None)
        retriever.collection = None

        # 검색 시도 - RuntimeError 발생해야 함
        with pytest.raises(RuntimeError) as exc_info:
            await retriever.search(query="테스트", top_k=10)

        # 에러 메시지 검증
        error_msg = str(exc_info.value)
        assert "Weaviate 'Documents' 컬렉션이 존재하지 않습니다" in error_msg
        assert "해결 방법:" in error_msg


class TestWeaviateRetrieverErrorHandling:
    """Weaviate 에러 핸들링 테스트"""

    @pytest.fixture
    def mock_embedder(self) -> MagicMock:
        """Mock Embedder"""
        embedder = MagicMock()
        embedder.embed_query = MagicMock(return_value=[0.1] * 3072)
        return embedder

    @pytest.mark.asyncio
    async def test_weaviate_query_error_explicit_raise(
        self, mock_embedder: MagicMock
    ) -> None:
        """
        Weaviate 검색 에러 시 명시적 에러 발생 테스트

        Given: Weaviate 검색 중 WeaviateQueryError 발생
        When: 검색 수행
        Then: RuntimeError로 변환하여 발생 (해결 방법 포함)
        """
        from weaviate.exceptions import WeaviateQueryError

        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        # Mock collection that raises WeaviateQueryError
        mock_collection = MagicMock()
        mock_query = MagicMock()
        mock_query.hybrid = MagicMock(
            side_effect=WeaviateQueryError("Query failed", "grpc")
        )
        mock_collection.query = mock_query

        mock_weaviate_client = MagicMock()
        mock_weaviate_client.is_ready = MagicMock(return_value=True)
        mock_weaviate_client.get_collection = MagicMock(return_value=mock_collection)

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )

        retriever.collection = mock_collection

        # 검색 시도 - RuntimeError 발생해야 함
        with pytest.raises(RuntimeError) as exc_info:
            await retriever.search(query="테스트", top_k=10)

        # 에러 메시지 검증
        error_msg = str(exc_info.value)
        assert "Weaviate 검색 중 오류가 발생했습니다" in error_msg
        assert "해결 방법:" in error_msg
        assert retriever.stats["errors"] == 1

    @pytest.mark.asyncio
    async def test_embedding_error_propagation(
        self, mock_embedder: MagicMock
    ) -> None:
        """
        Embedding 생성 에러 시 예외 전파 테스트

        Given: Embedder가 에러 발생
        When: 검색 수행
        Then: 예외 전파 (ValueError 또는 RuntimeError)
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        # Embedder가 에러 발생
        mock_embedder.embed_query = MagicMock(
            side_effect=ValueError("Embedding failed")
        )

        mock_collection = MagicMock()
        mock_weaviate_client = MagicMock()
        mock_weaviate_client.is_ready = MagicMock(return_value=True)
        mock_weaviate_client.get_collection = MagicMock(return_value=mock_collection)

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )

        retriever.collection = mock_collection

        # 검색 시도 (에러 전파되어야 함)
        with pytest.raises((ValueError, RuntimeError)):
            await retriever.search(query="테스트", top_k=10)


class TestWeaviateRetrieverHealthCheck:
    """Weaviate Health Check 테스트"""

    @pytest.fixture
    def mock_embedder(self) -> MagicMock:
        """Mock Embedder"""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_embedder: MagicMock) -> None:
        """
        Health Check 성공 테스트

        Given: Weaviate 연결 정상, 컬렉션 초기화됨
        When: health_check() 호출
        Then: True 반환
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        mock_collection = MagicMock()
        mock_weaviate_client = MagicMock()
        mock_weaviate_client.is_ready = MagicMock(return_value=True)
        mock_weaviate_client.get_collection = MagicMock(return_value=mock_collection)

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )

        retriever.collection = mock_collection

        # Health Check
        is_healthy = await retriever.health_check()

        # 검증: True 반환
        assert is_healthy is True

    @pytest.mark.asyncio
    async def test_health_check_collection_not_initialized(
        self, mock_embedder: MagicMock
    ) -> None:
        """
        컬렉션 미초기화 시 Health Check 실패 테스트

        Given: 컬렉션이 None
        When: health_check() 호출
        Then: False 반환
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        mock_weaviate_client = MagicMock()

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )

        retriever.collection = None  # 초기화 안 됨

        # Health Check
        is_healthy = await retriever.health_check()

        # 검증: False 반환
        assert is_healthy is False

    @pytest.mark.asyncio
    async def test_health_check_weaviate_not_ready(
        self, mock_embedder: MagicMock
    ) -> None:
        """
        Weaviate 연결 끊김 시 Health Check 실패 테스트

        Given: Weaviate가 준비되지 않음
        When: health_check() 호출
        Then: False 반환
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        mock_collection = MagicMock()
        mock_weaviate_client = MagicMock()
        mock_weaviate_client.is_ready = MagicMock(return_value=False)  # 연결 끊김

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )

        retriever.collection = mock_collection

        # Health Check
        is_healthy = await retriever.health_check()

        # 검증: False 반환
        assert is_healthy is False


class TestWeaviateRetrieverCleanup:
    """Weaviate Cleanup 테스트"""

    @pytest.fixture
    def mock_embedder(self) -> MagicMock:
        """Mock Embedder"""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_cleanup_success(self, mock_embedder: MagicMock) -> None:
        """
        Cleanup 성공 테스트

        Given: 초기화된 Retriever
        When: cleanup() 호출
        Then: 컬렉션 참조 해제, 에러 없음
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        mock_collection = MagicMock()
        mock_weaviate_client = MagicMock()

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )

        retriever.collection = mock_collection

        # Cleanup
        await retriever.cleanup()

        # 검증: 컬렉션 참조 해제됨
        assert retriever.collection is None

    @pytest.mark.asyncio
    async def test_cleanup_already_cleaned(self, mock_embedder: MagicMock) -> None:
        """
        이미 cleanup된 상태에서 다시 cleanup 테스트

        Given: 컬렉션이 이미 None
        When: cleanup() 호출
        Then: 에러 없이 진행
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        mock_weaviate_client = MagicMock()

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )

        retriever.collection = None  # 이미 cleanup됨

        # Cleanup (에러 없이 진행되어야 함)
        await retriever.cleanup()

        # 검증: 여전히 None
        assert retriever.collection is None


class TestWeaviateRetrieverAddDocuments:
    """Weaviate 문서 업로드 테스트"""

    @pytest.fixture
    def mock_embedder(self) -> MagicMock:
        """Mock Embedder"""
        return MagicMock()

    @pytest.fixture
    def mock_collection(self) -> MagicMock:
        """Mock Collection with data.insert_many (배치 적재)"""
        collection = MagicMock()
        collection.data = MagicMock()
        # insert_many 는 배치 결과 객체를 반환한다. errors={} 는 전건 성공을 의미한다.
        collection.data.insert_many = MagicMock(return_value=MagicMock(errors={}))
        return collection

    @pytest.mark.asyncio
    async def test_add_documents_success(
        self, mock_embedder: MagicMock, mock_collection: MagicMock
    ) -> None:
        """
        문서 업로드 성공 테스트

        Given: 유효한 문서 리스트
        When: add_documents() 호출
        Then: 모든 문서 업로드 성공
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        mock_weaviate_client = MagicMock()

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )

        retriever.collection = mock_collection

        # 업로드할 문서
        documents = [
            {
                "content": "테스트 문서 1",
                "embedding": [0.1] * 3072,
                "metadata": {"source": "test1.md", "file_type": "MARKDOWN"},
            },
            {
                "content": "테스트 문서 2",
                "embedding": [0.2] * 3072,
                "metadata": {"source": "test2.md", "file_type": "MARKDOWN"},
            },
        ]

        # 업로드
        result = await retriever.add_documents(documents)

        # 검증
        assert result["success_count"] == 2
        assert result["error_count"] == 0
        assert result["total_count"] == 2
        # 코드가 단건 insert 직렬 반복을 한 번의 배치(insert_many)로 대체했으므로,
        # insert_many 가 1회 호출되고 그 안에 2개의 DataObject 가 담겨야 한다.
        assert mock_collection.data.insert_many.call_count == 1
        inserted_objects = mock_collection.data.insert_many.call_args.args[0]
        assert len(inserted_objects) == 2

    @pytest.mark.asyncio
    async def test_add_documents_accepts_document_processor_dense_embedding(
        self, mock_embedder: MagicMock, mock_collection: MagicMock
    ) -> None:
        """
        DocumentProcessor의 이전 dense_embedding 키를 호환 입력으로 허용한다.
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=MagicMock(),
            collection_name="Documents",
        )
        retriever.collection = mock_collection

        documents = [
            {
                "content": "테스트 문서",
                "dense_embedding": [0.3] * 3072,
                "metadata": {
                    "document_id": "doc-1",
                    "source_file": "test.md",
                    "file_type": "MARKDOWN",
                },
            }
        ]

        result = await retriever.add_documents(documents)

        assert result["success_count"] == 1
        assert result["error_count"] == 0
        # 배치 적재이므로 insert_many 에 전달된 DataObject 의 vector 를 검증한다.
        inserted_objects = mock_collection.data.insert_many.call_args.args[0]
        assert inserted_objects[0].vector == [0.3] * 3072

    @pytest.mark.asyncio
    async def test_add_documents_normalizes_known_metadata_and_preserves_extras(
        self, mock_embedder: MagicMock, mock_collection: MagicMock
    ) -> None:
        """스키마에 맞는 메타데이터만 property로 쓰고 나머지는 JSON으로 보존한다."""
        import json

        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=MagicMock(),
            collection_name="Documents",
        )
        retriever.collection = mock_collection

        documents = [
            {
                "content": "테스트 문서",
                "embedding": [0.4] * 3072,
                "metadata": {
                    "document_id": "doc-1",
                    "chunk_index": "2",
                    "load_timestamp": "123.5",
                    "keys": ["a", "b"],
                    "custom": {"nested": True},
                },
            }
        ]

        result = await retriever.add_documents(documents)

        # 배치 적재이므로 insert_many 에 전달된 DataObject 의 properties 를 검증한다.
        inserted_objects = mock_collection.data.insert_many.call_args.args[0]
        properties = inserted_objects[0].properties
        assert result["success_count"] == 1
        assert properties["document_id"] == "doc-1"
        assert properties["chunk_index"] == 2
        assert properties["load_timestamp"] == 123.5
        assert properties["keys"] == ["a", "b"]
        assert json.loads(properties["metadata_json"]) == {"custom": {"nested": True}}

    @pytest.mark.asyncio
    async def test_add_documents_missing_content(
        self, mock_embedder: MagicMock, mock_collection: MagicMock
    ) -> None:
        """
        필수 필드 누락 시 graceful handling 테스트

        Given: content 필드가 없는 문서
        When: add_documents() 호출
        Then: 해당 문서는 스킵하고 계속 진행
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        mock_weaviate_client = MagicMock()

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )

        retriever.collection = mock_collection

        # 문서 (content 누락)
        documents = [
            {
                "embedding": [0.1] * 3072,  # content 없음
            },
            {
                "content": "정상 문서",
                "embedding": [0.2] * 3072,
            },
        ]

        # 업로드
        result = await retriever.add_documents(documents)

        # 검증: 하나만 성공
        assert result["success_count"] == 1
        assert result["error_count"] == 1
        assert result["total_count"] == 2

    @pytest.mark.asyncio
    async def test_add_documents_uninitialized_collection(
        self, mock_embedder: MagicMock
    ) -> None:
        """
        초기화되지 않은 컬렉션으로 업로드 시도 테스트

        Given: 컬렉션이 None
        When: add_documents() 호출
        Then: RuntimeError 발생 (해결 방법 포함)
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        mock_weaviate_client = MagicMock()

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
        )

        retriever.collection = None  # 초기화 안 됨

        documents = [
            {
                "content": "테스트",
                "embedding": [0.1] * 3072,
            }
        ]

        # 업로드 시도 - RuntimeError 발생해야 함
        with pytest.raises(RuntimeError) as exc_info:
            await retriever.add_documents(documents)

        # 에러 메시지 검증
        error_msg = str(exc_info.value)
        assert "Weaviate 'Documents' 컬렉션이 존재하지 않습니다" in error_msg
        assert "해결 방법:" in error_msg


class TestWeaviateRetrieverBM25Preprocessing:
    """BM25 쿼리 전처리 테스트"""

    @pytest.fixture
    def mock_embedder(self) -> MagicMock:
        """Mock Embedder"""
        embedder = MagicMock()
        embedder.embed_query = MagicMock(return_value=[0.1] * 3072)
        return embedder

    @pytest.mark.asyncio
    async def test_preprocess_query_disabled(
        self, mock_embedder: MagicMock
    ) -> None:
        """
        BM25 전처리 비활성화 테스트

        Given: BM25 모듈이 None (비활성화)
        When: 검색 수행
        Then: 원본 쿼리 그대로 사용
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        mock_collection = MagicMock()
        mock_query = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = []
        mock_query.hybrid = MagicMock(return_value=mock_response)
        mock_collection.query = mock_query

        mock_weaviate_client = MagicMock()
        mock_weaviate_client.is_ready = MagicMock(return_value=True)

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
            synonym_manager=None,  # 비활성화
            stopword_filter=None,  # 비활성화
            user_dictionary=None,  # 비활성화
        )

        retriever.collection = mock_collection

        # 검색
        await retriever.search(query="테스트 쿼리", top_k=10)

        # 검증: bm25_preprocessed 통계가 0
        assert retriever.stats["bm25_preprocessed"] == 0

    @pytest.mark.asyncio
    async def test_preprocess_query_with_synonym_manager(
        self, mock_embedder: MagicMock
    ) -> None:
        """
        동의어 확장 테스트

        Given: 동의어 관리자가 활성화됨
        When: 검색 수행
        Then: 동의어 확장 적용됨
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        # Mock 동의어 관리자
        mock_synonym_manager = MagicMock()
        mock_synonym_manager.expand_query = MagicMock(
            side_effect=lambda q: q.replace("축약어", "표준어")
        )

        mock_collection = MagicMock()
        mock_query = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = []
        mock_query.hybrid = MagicMock(return_value=mock_response)
        mock_collection.query = mock_query

        mock_weaviate_client = MagicMock()

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
            synonym_manager=mock_synonym_manager,
        )

        retriever.collection = mock_collection

        # 검색
        await retriever.search(query="축약어 쿼리", top_k=10)

        # 검증: expand_query 호출됨
        mock_synonym_manager.expand_query.assert_called()
        assert retriever.stats["bm25_preprocessed"] == 1


class TestWeaviateRetrieverAdditionalCollections:
    """추가 컬렉션 (Phase 3) 테스트"""

    @pytest.fixture
    def mock_embedder(self) -> MagicMock:
        """Mock Embedder"""
        embedder = MagicMock()
        embedder.embed_query = MagicMock(return_value=[0.1] * 3072)
        return embedder

    @pytest.mark.asyncio
    async def test_initialize_with_additional_collections(
        self, mock_embedder: MagicMock
    ) -> None:
        """
        추가 컬렉션 초기화 테스트

        Given: additional_collections 설정
        When: initialize() 호출
        Then: 추가 컬렉션도 초기화됨
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        # Mock collections
        mock_main_collection = MagicMock()
        mock_additional_collection = MagicMock()

        mock_weaviate_client = MagicMock()
        mock_weaviate_client.is_ready = MagicMock(return_value=True)
        mock_weaviate_client.get_collection = MagicMock(
            side_effect=lambda name: mock_main_collection
            if name == "Documents"
            else mock_additional_collection
        )

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
            additional_collections=["StructuredMetadata"],
        )

        # 초기화
        await retriever.initialize()

        # 검증: 메인 + 추가 컬렉션 모두 초기화됨
        assert retriever.collection is not None
        assert "StructuredMetadata" in retriever._additional_collection_objects
        assert mock_weaviate_client.get_collection.call_count == 2

    @pytest.mark.asyncio
    async def test_initialize_additional_collection_failure(
        self, mock_embedder: MagicMock
    ) -> None:
        """
        추가 컬렉션 초기화 실패 시 graceful degradation 테스트

        Given: 추가 컬렉션이 존재하지 않음
        When: initialize() 호출
        Then: 경고 로깅, 메인 컬렉션만 사용
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        # Mock collections
        mock_main_collection = MagicMock()

        mock_weaviate_client = MagicMock()
        mock_weaviate_client.is_ready = MagicMock(return_value=True)
        mock_weaviate_client.get_collection = MagicMock(
            side_effect=lambda name: mock_main_collection
            if name == "Documents"
            else None  # 추가 컬렉션 없음
        )

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
            additional_collections=["NonExistent"],
        )

        # 초기화 (에러 없이 진행되어야 함)
        await retriever.initialize()

        # 검증: 메인 컬렉션만 초기화됨
        assert retriever.collection is not None
        assert "NonExistent" not in retriever._additional_collection_objects

    @pytest.mark.asyncio
    async def test_search_multi_collections_with_rrf(
        self, mock_embedder: MagicMock
    ) -> None:
        """
        다중 컬렉션 RRF 병합 검색 테스트

        Given: 메인 컬렉션 + 추가 컬렉션
        When: 검색 수행
        Then: RRF로 결과 병합됨
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        # Mock main collection results
        mock_main_obj = MagicMock()
        mock_main_obj.uuid = "main-1"
        mock_main_obj.properties = {
            "content": "메인 문서",
            "source_file": "main.md",
        }
        mock_main_obj.metadata = MagicMock()
        mock_main_obj.metadata.score = 0.9

        mock_main_collection = MagicMock()
        mock_main_query = MagicMock()
        mock_main_response = MagicMock()
        mock_main_response.objects = [mock_main_obj]
        mock_main_query.hybrid = MagicMock(return_value=mock_main_response)
        mock_main_collection.query = mock_main_query

        # Mock additional collection results
        mock_add_obj = MagicMock()
        mock_add_obj.uuid = "add-1"
        mock_add_obj.properties = {
            "content": "추가 문서",
            "entity_name": "테스트 엔티티",
        }
        mock_add_obj.metadata = MagicMock()
        mock_add_obj.metadata.score = 0.8

        mock_add_collection = MagicMock()
        mock_add_query = MagicMock()
        mock_add_response = MagicMock()
        mock_add_response.objects = [mock_add_obj]
        mock_add_query.hybrid = MagicMock(return_value=mock_add_response)
        mock_add_collection.query = mock_add_query

        mock_weaviate_client = MagicMock()
        mock_weaviate_client.is_ready = MagicMock(return_value=True)
        mock_weaviate_client.get_collection = MagicMock(
            side_effect=lambda name: mock_main_collection
            if name == "Documents"
            else mock_add_collection
        )

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
            additional_collections=["StructuredMetadata"],
        )

        # 초기화
        await retriever.initialize()

        # 검색 (다중 컬렉션)
        results = await retriever.search(query="테스트 쿼리", top_k=10)

        # 검증: RRF 병합된 결과
        assert len(results) == 2  # 메인 + 추가
        assert retriever.stats["multi_collection_searches"] == 1

        # RRF 점수가 설정되었는지 확인
        for result in results:
            assert "_rrf_score" in result.metadata
            assert "_sources" in result.metadata

    @pytest.mark.asyncio
    async def test_initialize_additional_collection_exception(
        self, mock_embedder: MagicMock
    ) -> None:
        """
        추가 컬렉션 초기화 중 예외 발생 시 graceful degradation 테스트

        Given: 추가 컬렉션 get_collection()이 예외 발생
        When: initialize() 호출
        Then: 경고 로깅, 메인 컬렉션만 사용
        """
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        # Mock collections
        mock_main_collection = MagicMock()

        mock_weaviate_client = MagicMock()
        mock_weaviate_client.is_ready = MagicMock(return_value=True)

        # 메인은 성공, 추가는 예외 발생
        def side_effect(name: str) -> Any:
            if name == "Documents":
                return mock_main_collection
            else:
                raise Exception("Collection error")

        mock_weaviate_client.get_collection = MagicMock(side_effect=side_effect)

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
            additional_collections=["FailCollection"],
        )

        # 초기화 (에러 없이 진행되어야 함)
        await retriever.initialize()

        # 검증: 메인 컬렉션만 초기화됨
        assert retriever.collection is not None
        assert "FailCollection" not in retriever._additional_collection_objects


class TestWeaviateHybridFusionType:
    """Weaviate hybrid fusion_type 설정화 + fail-fast 리졸버 테스트 (#28)"""

    @pytest.fixture
    def mock_embedder(self) -> MagicMock:
        """Mock Embedder"""
        embedder = MagicMock()
        embedder.embed_query = MagicMock(return_value=[0.1] * 3072)
        return embedder

    @pytest.fixture
    def mock_weaviate_client(self) -> MagicMock:
        """Mock Weaviate Client"""
        client = MagicMock()
        client.is_ready = MagicMock(return_value=True)
        client.get_collection = MagicMock(return_value=MagicMock())
        return client

    def test_resolve_fusion_type_none_defaults_to_ranked(
        self, mock_embedder: MagicMock, mock_weaviate_client: MagicMock
    ) -> None:
        """None이면 RANKED(기본)로 리졸브된다."""
        from weaviate.classes.query import HybridFusion

        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        assert (
            WeaviateRetriever._resolve_hybrid_fusion_type(None)
            == HybridFusion.RANKED
        )

    def test_resolve_fusion_type_aliases(self) -> None:
        """문자열 별칭이 올바른 HybridFusion enum으로 매핑된다."""
        from weaviate.classes.query import HybridFusion

        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        resolve = WeaviateRetriever._resolve_hybrid_fusion_type
        assert resolve("ranked") == HybridFusion.RANKED
        assert resolve("rrf") == HybridFusion.RANKED
        assert resolve("relative_score") == HybridFusion.RELATIVE_SCORE
        assert resolve("relative-score") == HybridFusion.RELATIVE_SCORE
        assert resolve("RELATIVE") == HybridFusion.RELATIVE_SCORE

    def test_resolve_fusion_type_passthrough_enum(self) -> None:
        """HybridFusion 인스턴스는 그대로 통과된다."""
        from weaviate.classes.query import HybridFusion

        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        assert (
            WeaviateRetriever._resolve_hybrid_fusion_type(HybridFusion.RELATIVE_SCORE)
            == HybridFusion.RELATIVE_SCORE
        )

    def test_resolve_fusion_type_invalid_raises(self) -> None:
        """미지원 값은 fail-fast로 ValueError를 던진다."""
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        with pytest.raises(ValueError, match="fusion_type"):
            WeaviateRetriever._resolve_hybrid_fusion_type("bogus_fusion")

    def test_constructor_accepts_and_resolves_fusion_type(
        self, mock_embedder: MagicMock, mock_weaviate_client: MagicMock
    ) -> None:
        """생성자가 fusion_type 문자열을 받아 enum으로 저장한다."""
        from weaviate.classes.query import HybridFusion

        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
            fusion_type="relative_score",
        )
        assert retriever.fusion_type == HybridFusion.RELATIVE_SCORE

    @pytest.mark.asyncio
    async def test_search_passes_fusion_type_to_hybrid(
        self, mock_embedder: MagicMock, mock_weaviate_client: MagicMock
    ) -> None:
        """search가 hybrid 호출에 fusion_type을 전달한다."""
        from weaviate.classes.query import HybridFusion

        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        mock_collection = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query = MagicMock()
        mock_collection.query.hybrid = MagicMock(return_value=mock_response)

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
            fusion_type="relative_score",
        )
        retriever.collection = mock_collection

        await retriever.search(query="q", top_k=5)

        call_kwargs = mock_collection.query.hybrid.call_args.kwargs
        assert call_kwargs["fusion_type"] == HybridFusion.RELATIVE_SCORE


class TestWeaviateDynamicAlpha:
    """질의별 동적 하이브리드 alpha 적용 테스트 (#35)"""

    @pytest.fixture
    def mock_embedder(self) -> MagicMock:
        """Mock Embedder"""
        embedder = MagicMock()
        embedder.embed_query = MagicMock(return_value=[0.1] * 3072)
        return embedder

    @pytest.fixture
    def mock_weaviate_client(self) -> MagicMock:
        """Mock Weaviate Client"""
        client = MagicMock()
        client.is_ready = MagicMock(return_value=True)
        client.get_collection = MagicMock(return_value=MagicMock())
        return client

    def _retriever_with_collection(
        self, mock_embedder: MagicMock, mock_weaviate_client: MagicMock
    ):
        from app.modules.core.retrieval.retrievers.weaviate_retriever import (
            WeaviateRetriever,
        )

        mock_collection = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query = MagicMock()
        mock_collection.query.hybrid = MagicMock(return_value=mock_response)

        retriever = WeaviateRetriever(
            embedder=mock_embedder,
            weaviate_client=mock_weaviate_client,
            collection_name="Documents",
            alpha=0.6,
        )
        retriever.collection = mock_collection
        return retriever, mock_collection

    @pytest.mark.asyncio
    async def test_search_uses_default_alpha_when_none(
        self, mock_embedder: MagicMock, mock_weaviate_client: MagicMock
    ) -> None:
        """alpha 미지정 시 인스턴스 기본 alpha(0.6)를 사용한다(하위 호환)."""
        retriever, mock_collection = self._retriever_with_collection(
            mock_embedder, mock_weaviate_client
        )

        await retriever.search(query="q", top_k=5)

        call_kwargs = mock_collection.query.hybrid.call_args.kwargs
        assert call_kwargs["alpha"] == 0.6

    @pytest.mark.asyncio
    async def test_search_applies_override_alpha(
        self, mock_embedder: MagicMock, mock_weaviate_client: MagicMock
    ) -> None:
        """alpha 오버라이드가 hybrid 호출에 적용된다(BM25 가중 강화)."""
        retriever, mock_collection = self._retriever_with_collection(
            mock_embedder, mock_weaviate_client
        )

        await retriever.search(query="q", top_k=5, alpha=0.2)

        call_kwargs = mock_collection.query.hybrid.call_args.kwargs
        assert call_kwargs["alpha"] == 0.2


class TestWeaviateRetrieverPropertyTypeMapDerivation:
    """필터 타입맵이 스키마 단일 진실원천에서 파생되는지 검증(도메인 범용화)."""

    def test_type_maps_derived_from_schema_single_source(self) -> None:
        """(c) _TEXT_PROPERTIES 등이 weaviate_setup 스키마 정의에서 파생된다.

        중복 하드코딩을 제거했으므로, 리트리버의 타입 집합 합집합은
        스키마 단일 진실원천(document_property_types)의 키 집합과 일치해야 한다.
        """
        from app.lib.weaviate_setup import document_property_types
        from app.modules.core.retrieval.retrievers import weaviate_retriever as wr

        property_types = document_property_types()

        # 리트리버 타입 집합 합집합 == 스키마 전체 프로퍼티 집합(파생 일관성)
        union = (
            wr._TEXT_PROPERTIES
            | wr._INT_PROPERTIES
            | wr._NUMBER_PROPERTIES
            | wr._TEXT_ARRAY_PROPERTIES
        )
        assert union == set(property_types)

        # 타입별 분류도 스키마 정의와 정확히 일치해야 한다.
        for name, category in property_types.items():
            if category == "text":
                assert name in wr._TEXT_PROPERTIES
            elif category == "int":
                assert name in wr._INT_PROPERTIES
            elif category == "number":
                assert name in wr._NUMBER_PROPERTIES
            elif category == "text_array":
                assert name in wr._TEXT_ARRAY_PROPERTIES

    def test_default_type_maps_have_no_venue_fields(self) -> None:
        """기본(중립) 타입맵에는 venue 도메인 필드가 없어야 한다."""
        from app.modules.core.retrieval.retrievers import weaviate_retriever as wr

        venue_fields = {
            "price",
            "capacity",
            "rating",
            "location",
            "entity_name",
            "numeric_value",
        }
        union = (
            wr._TEXT_PROPERTIES
            | wr._INT_PROPERTIES
            | wr._NUMBER_PROPERTIES
            | wr._TEXT_ARRAY_PROPERTIES
        )
        assert venue_fields & union == set()
