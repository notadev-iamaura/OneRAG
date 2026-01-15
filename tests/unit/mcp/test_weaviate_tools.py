"""벡터 검색 도구 테스트 (tools 모듈)"""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_retriever():
    """WeaviateRetriever 목킹"""
    retriever = AsyncMock()
    retriever.search = AsyncMock(
        return_value=[
            MagicMock(
                page_content="레스토랑 A 정보",
                metadata={"source": "test", "name": "레스토랑 A"},
            ),
            MagicMock(
                page_content="레스토랑 B 정보",
                metadata={"source": "test", "name": "레스토랑 B"},
            ),
        ]
    )
    return retriever


@pytest.fixture
def mock_global_config(mock_retriever):
    """global_config 목킹"""
    return {
        "retriever": mock_retriever,
        "mcp": {
            "tools": {
                "search_weaviate": {
                    "parameters": {
                        "default_top_k": 5,
                        "alpha": 0.6,
                    }
                }
            }
        },
    }


def test_vector_search_module_exists():
    """벡터 검색 도구 모듈 존재 확인"""
    from app.modules.core.tools import vector_search

    assert vector_search is not None


def test_search_weaviate_function_exists():
    """search_weaviate 함수 존재 확인"""
    from app.modules.core.tools.vector_search import search_weaviate

    assert callable(search_weaviate)


def test_get_document_by_id_function_exists():
    """get_document_by_id 함수 존재 확인"""
    from app.modules.core.tools.vector_search import get_document_by_id

    assert callable(get_document_by_id)


@pytest.mark.asyncio
async def test_search_weaviate_basic(mock_global_config):
    """search_weaviate 기본 동작 테스트"""
    from app.modules.core.tools.vector_search import search_weaviate

    arguments = {"query": "강남 맛집", "top_k": 5}

    result = await search_weaviate(arguments, mock_global_config)

    assert isinstance(result, list)
    assert len(result) == 2
    assert "content" in result[0]
    assert "metadata" in result[0]


@pytest.mark.asyncio
async def test_search_weaviate_uses_default_top_k(mock_global_config):
    """top_k 미지정 시 기본값 사용"""
    from app.modules.core.tools.vector_search import search_weaviate

    arguments = {"query": "레스토랑"}

    await search_weaviate(arguments, mock_global_config)

    # retriever.search가 default_top_k=5로 호출되었는지 확인
    mock_global_config["retriever"].search.assert_called_once()
    call_args = mock_global_config["retriever"].search.call_args
    assert call_args.kwargs.get("top_k", call_args.args[1] if len(call_args.args) > 1 else 5) == 5


@pytest.mark.asyncio
async def test_search_weaviate_no_retriever():
    """retriever 미설정 시 에러 처리"""
    from app.modules.core.tools.vector_search import search_weaviate

    arguments = {"query": "테스트"}
    config_without_retriever = {"mcp": {"tools": {"search_weaviate": {}}}}

    with pytest.raises(ValueError, match="retriever"):
        await search_weaviate(arguments, config_without_retriever)


@pytest.mark.asyncio
async def test_search_weaviate_empty_query():
    """빈 쿼리 시 에러 처리"""
    from app.modules.core.tools.vector_search import search_weaviate

    arguments = {"query": ""}

    with pytest.raises(ValueError, match="query"):
        await search_weaviate(arguments, {})


@pytest.mark.asyncio
async def test_get_document_by_id_basic(mock_global_config):
    """get_document_by_id 기본 동작 테스트"""
    from app.modules.core.tools.vector_search import get_document_by_id

    # get_by_id 목킹
    mock_global_config["retriever"].get_by_id = AsyncMock(
        return_value=MagicMock(
            page_content="테스트 문서",
            metadata={"id": "test-uuid"},
        )
    )

    arguments = {"document_id": "test-uuid-12345"}

    result = await get_document_by_id(arguments, mock_global_config)

    assert result is not None
    assert "content" in result
    assert "metadata" in result


