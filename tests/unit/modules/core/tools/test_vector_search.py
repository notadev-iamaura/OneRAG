# tests/unit/modules/core/tools/test_vector_search.py
"""
vector_search 모듈 테스트

TDD Red 단계: 새로운 vector_search 도구 함수를 테스트합니다.
- search_weaviate 함수 테스트
- get_document_by_id 함수 테스트
"""
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestVectorSearchImport:
    """vector_search 모듈 import 테스트"""

    def test_import_search_weaviate(self) -> None:
        """search_weaviate 함수 import 테스트"""
        from app.modules.core.tools.vector_search import search_weaviate

        assert search_weaviate is not None
        assert callable(search_weaviate)

    def test_import_get_document_by_id(self) -> None:
        """get_document_by_id 함수 import 테스트"""
        from app.modules.core.tools.vector_search import get_document_by_id

        assert get_document_by_id is not None
        assert callable(get_document_by_id)


class TestSearchWeaviate:
    """search_weaviate 함수 테스트"""

    @pytest.mark.asyncio
    async def test_search_weaviate_success(self) -> None:
        """정상적인 검색 테스트"""
        from app.modules.core.tools.vector_search import search_weaviate

        # Mock retriever 생성
        mock_doc = MagicMock()
        mock_doc.page_content = "테스트 문서 내용"
        mock_doc.metadata = {"source": "test.txt"}

        mock_retriever = AsyncMock()
        mock_retriever.search.return_value = [mock_doc]

        arguments = {"query": "테스트 쿼리", "top_k": 5}
        global_config: dict[str, Any] = {
            "retriever": mock_retriever,
            "mcp": {"tools": {"search_weaviate": {"parameters": {}}}},
        }

        result = await search_weaviate(arguments, global_config)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["content"] == "테스트 문서 내용"
        assert result[0]["metadata"] == {"source": "test.txt"}

    @pytest.mark.asyncio
    async def test_search_weaviate_empty_query(self) -> None:
        """빈 쿼리 예외 테스트"""
        from app.modules.core.tools.vector_search import search_weaviate

        arguments: dict[str, Any] = {"query": ""}
        global_config: dict[str, Any] = {"retriever": MagicMock()}

        with pytest.raises(ValueError, match="query는 필수입니다"):
            await search_weaviate(arguments, global_config)

    @pytest.mark.asyncio
    async def test_search_weaviate_no_retriever(self) -> None:
        """retriever 미설정 예외 테스트"""
        from app.modules.core.tools.vector_search import search_weaviate

        arguments = {"query": "테스트 쿼리"}
        global_config: dict[str, Any] = {}

        with pytest.raises(ValueError, match="retriever가 설정되지 않았습니다"):
            await search_weaviate(arguments, global_config)


class TestGetDocumentById:
    """get_document_by_id 함수 테스트"""

    @pytest.mark.asyncio
    async def test_get_document_by_id_success(self) -> None:
        """정상적인 문서 조회 테스트"""
        from app.modules.core.tools.vector_search import get_document_by_id

        # Mock retriever 생성
        mock_doc = MagicMock()
        mock_doc.page_content = "테스트 문서"
        mock_doc.metadata = {"id": "test-uuid"}

        mock_retriever = AsyncMock()
        mock_retriever.get_by_id.return_value = mock_doc

        arguments = {"document_id": "test-uuid"}
        global_config: dict[str, Any] = {"retriever": mock_retriever}

        result = await get_document_by_id(arguments, global_config)

        assert result is not None
        assert result["content"] == "테스트 문서"
        assert result["metadata"] == {"id": "test-uuid"}

    @pytest.mark.asyncio
    async def test_get_document_by_id_empty_id(self) -> None:
        """빈 document_id 예외 테스트"""
        from app.modules.core.tools.vector_search import get_document_by_id

        arguments: dict[str, Any] = {"document_id": ""}
        global_config: dict[str, Any] = {"retriever": MagicMock()}

        with pytest.raises(ValueError, match="document_id는 필수입니다"):
            await get_document_by_id(arguments, global_config)

    @pytest.mark.asyncio
    async def test_get_document_by_id_no_retriever(self) -> None:
        """retriever 미설정 예외 테스트"""
        from app.modules.core.tools.vector_search import get_document_by_id

        arguments = {"document_id": "test-uuid"}
        global_config: dict[str, Any] = {}

        with pytest.raises(ValueError, match="retriever가 설정되지 않았습니다"):
            await get_document_by_id(arguments, global_config)
