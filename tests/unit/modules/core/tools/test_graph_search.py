# tests/unit/modules/core/tools/test_graph_search.py
"""
graph_search 모듈 테스트

TDD Red 단계: 새로운 graph_search 도구 함수를 테스트합니다.
- search_graph 함수 테스트
- get_neighbors 함수 테스트
"""
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestGraphSearchImport:
    """graph_search 모듈 import 테스트"""

    def test_import_search_graph(self) -> None:
        """search_graph 함수 import 테스트"""
        from app.modules.core.tools.graph_search import search_graph

        assert search_graph is not None
        assert callable(search_graph)

    def test_import_get_neighbors(self) -> None:
        """get_neighbors 함수 import 테스트"""
        from app.modules.core.tools.graph_search import get_neighbors

        assert get_neighbors is not None
        assert callable(get_neighbors)


class TestSearchGraph:
    """search_graph 함수 테스트"""

    @pytest.mark.asyncio
    async def test_search_graph_success(self) -> None:
        """정상적인 그래프 검색 테스트"""
        from app.modules.core.tools.graph_search import search_graph

        # Mock entity 생성
        mock_entity = MagicMock()
        mock_entity.id = "entity-1"
        mock_entity.name = "테스트 엔티티"
        mock_entity.type = "COMPANY"
        mock_entity.properties = {"key": "value"}

        # Mock relation 생성
        mock_relation = MagicMock()
        mock_relation.source_id = "entity-1"
        mock_relation.target_id = "entity-2"
        mock_relation.type = "RELATED_TO"
        mock_relation.weight = 0.9

        # Mock result 생성
        mock_result = MagicMock()
        mock_result.entities = [mock_entity]
        mock_result.relations = [mock_relation]
        mock_result.score = 0.95

        # Mock graph_store 생성
        mock_graph_store = AsyncMock()
        mock_graph_store.search.return_value = mock_result

        arguments = {"query": "테스트 검색", "top_k": 10}
        global_config: dict[str, Any] = {
            "graph_store": mock_graph_store,
            "mcp": {"tools": {"search_graph": {"parameters": {}}}},
        }

        result = await search_graph(arguments, global_config)

        assert result["success"] is True
        assert len(result["entities"]) == 1
        assert result["entities"][0]["name"] == "테스트 엔티티"
        assert len(result["relations"]) == 1
        assert result["score"] == 0.95

    @pytest.mark.asyncio
    async def test_search_graph_empty_query(self) -> None:
        """빈 쿼리 예외 테스트"""
        from app.modules.core.tools.graph_search import search_graph

        arguments: dict[str, Any] = {"query": ""}
        global_config: dict[str, Any] = {"graph_store": MagicMock()}

        with pytest.raises(ValueError, match="query는 필수입니다"):
            await search_graph(arguments, global_config)

    @pytest.mark.asyncio
    async def test_search_graph_no_graph_store(self) -> None:
        """graph_store 미설정 예외 테스트"""
        from app.modules.core.tools.graph_search import search_graph

        arguments = {"query": "테스트 쿼리"}
        global_config: dict[str, Any] = {}

        with pytest.raises(ValueError, match="graph_store가 설정되지 않았습니다"):
            await search_graph(arguments, global_config)


class TestGetNeighbors:
    """get_neighbors 함수 테스트"""

    @pytest.mark.asyncio
    async def test_get_neighbors_success(self) -> None:
        """정상적인 이웃 조회 테스트"""
        from app.modules.core.tools.graph_search import get_neighbors

        # Mock entity 생성
        mock_entity = MagicMock()
        mock_entity.id = "neighbor-1"
        mock_entity.name = "이웃 엔티티"
        mock_entity.type = "COMPANY"
        mock_entity.properties = {}

        # Mock relation 생성
        mock_relation = MagicMock()
        mock_relation.source_id = "entity-1"
        mock_relation.target_id = "neighbor-1"
        mock_relation.type = "RELATED_TO"
        mock_relation.weight = 0.8

        # Mock result 생성
        mock_result = MagicMock()
        mock_result.entities = [mock_entity]
        mock_result.relations = [mock_relation]

        # Mock graph_store 생성
        mock_graph_store = AsyncMock()
        mock_graph_store.get_neighbors.return_value = mock_result

        arguments = {"entity_id": "entity-1", "max_depth": 1}
        global_config: dict[str, Any] = {
            "graph_store": mock_graph_store,
            "mcp": {"tools": {"get_neighbors": {"parameters": {}}}},
        }

        result = await get_neighbors(arguments, global_config)

        assert result["success"] is True
        assert len(result["entities"]) == 1
        assert result["entities"][0]["name"] == "이웃 엔티티"

    @pytest.mark.asyncio
    async def test_get_neighbors_empty_entity_id(self) -> None:
        """빈 entity_id 예외 테스트"""
        from app.modules.core.tools.graph_search import get_neighbors

        arguments: dict[str, Any] = {"entity_id": ""}
        global_config: dict[str, Any] = {"graph_store": MagicMock()}

        with pytest.raises(ValueError, match="entity_id는 필수입니다"):
            await get_neighbors(arguments, global_config)

    @pytest.mark.asyncio
    async def test_get_neighbors_no_graph_store(self) -> None:
        """graph_store 미설정 예외 테스트"""
        from app.modules.core.tools.graph_search import get_neighbors

        arguments = {"entity_id": "entity-1"}
        global_config: dict[str, Any] = {}

        with pytest.raises(ValueError, match="graph_store가 설정되지 않았습니다"):
            await get_neighbors(arguments, global_config)
