# tests/unit/mcp/test_graph_tools.py
"""
GraphRAG 도구 테스트 (tools 모듈)

search_graph, get_neighbors 도구를 도구 패턴(arguments, global_config)에 맞게 검증합니다.
에러 케이스와 엣지 케이스도 테스트합니다.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.core.graph.models import Entity, GraphSearchResult, Relation


class TestSearchGraphTool:
    """search_graph 도구 테스트"""

    @pytest.fixture
    def mock_graph_store(self):
        """그래프 저장소 모킹"""
        store = MagicMock()
        store.search = AsyncMock(
            return_value=GraphSearchResult(
                entities=[
                    Entity(id="e1", name="A 업체", type="company"),
                ],
                relations=[
                    Relation(source_id="e1", target_id="e2", type="partnership"),
                ],
                score=0.9,
            )
        )
        return store

    @pytest.fixture
    def global_config(self, mock_graph_store):
        """global_config 구성"""
        return {
            "graph_store": mock_graph_store,
            "mcp": {
                "tools": {
                    "search_graph": {
                        "parameters": {
                            "default_top_k": 10,
                        }
                    }
                }
            },
        }

    @pytest.mark.asyncio
    async def test_search_graph_success(self, global_config, mock_graph_store):
        """정상 검색: 엔티티와 관계 반환"""
        from app.modules.core.tools.graph_search import search_graph

        result = await search_graph(
            arguments={"query": "A 업체", "top_k": 5},
            global_config=global_config,
        )

        # 검증
        assert result["success"] is True
        assert len(result["entities"]) == 1
        assert result["entities"][0]["name"] == "A 업체"
        assert result["entities"][0]["type"] == "company"
        assert len(result["relations"]) == 1
        assert result["relations"][0]["type"] == "partnership"
        assert result["score"] == 0.9

        # graph_store.search 호출 확인
        mock_graph_store.search.assert_called_once_with(
            query="A 업체",
            entity_types=None,
            top_k=5,
        )

    @pytest.mark.asyncio
    async def test_search_graph_with_entity_types(self, global_config, mock_graph_store):
        """entity_types 필터링"""
        from app.modules.core.tools.graph_search import search_graph

        result = await search_graph(
            arguments={
                "query": "맛집",
                "entity_types": ["company", "venue"],
                "top_k": 20,
            },
            global_config=global_config,
        )

        assert result["success"] is True
        # Then - 전달한 인자와 동일하게 검증
        mock_graph_store.search.assert_called_once_with(
            query="맛집",
            entity_types=["company", "venue"],
            top_k=20,
        )

    @pytest.mark.asyncio
    async def test_search_graph_empty_query_error(self, global_config):
        """빈 쿼리 시 ValueError"""
        from app.modules.core.tools.graph_search import search_graph

        with pytest.raises(ValueError, match="query는 필수입니다"):
            await search_graph(
                arguments={"query": ""},
                global_config=global_config,
            )

    @pytest.mark.asyncio
    async def test_search_graph_missing_query_error(self, global_config):
        """query 누락 시 ValueError"""
        from app.modules.core.tools.graph_search import search_graph

        with pytest.raises(ValueError, match="query는 필수입니다"):
            await search_graph(
                arguments={},
                global_config=global_config,
            )

    @pytest.mark.asyncio
    async def test_search_graph_no_graph_store_error(self):
        """graph_store 미설정 시 ValueError"""
        from app.modules.core.tools.graph_search import search_graph

        with pytest.raises(ValueError, match="graph_store가 설정되지 않았습니다"):
            await search_graph(
                arguments={"query": "테스트"},
                global_config={},  # graph_store 없음
            )

    @pytest.mark.asyncio
    async def test_search_graph_store_error_propagation(
        self, global_config, mock_graph_store
    ):
        """graph_store.search 에러 전파"""
        from app.modules.core.tools.graph_search import search_graph

        # 검색 실패 시나리오
        mock_graph_store.search.side_effect = RuntimeError("DB 연결 실패")

        with pytest.raises(RuntimeError, match="DB 연결 실패"):
            await search_graph(
                arguments={"query": "테스트"},
                global_config=global_config,
            )


class TestGetNeighborsTool:
    """get_neighbors 도구 테스트"""

    @pytest.fixture
    def mock_graph_store(self):
        """그래프 저장소 모킹"""
        store = MagicMock()
        store.get_neighbors = AsyncMock(
            return_value=GraphSearchResult(
                entities=[
                    Entity(id="e2", name="B 업체", type="company"),
                    Entity(id="e3", name="C 업체", type="company"),
                ],
                relations=[
                    Relation(source_id="e1", target_id="e2", type="partnership"),
                    Relation(source_id="e1", target_id="e3", type="supplier"),
                ],
                score=1.0,
            )
        )
        return store

    @pytest.fixture
    def global_config(self, mock_graph_store):
        """global_config 구성"""
        return {
            "graph_store": mock_graph_store,
            "mcp": {
                "tools": {
                    "get_neighbors": {
                        "parameters": {
                            "default_max_depth": 1,
                        }
                    }
                }
            },
        }

    @pytest.mark.asyncio
    async def test_get_neighbors_success(self, global_config, mock_graph_store):
        """정상 이웃 조회"""
        from app.modules.core.tools.graph_search import get_neighbors

        result = await get_neighbors(
            arguments={"entity_id": "e1", "max_depth": 2},
            global_config=global_config,
        )

        assert result["success"] is True
        assert len(result["entities"]) == 2
        assert result["entities"][0]["name"] == "B 업체"
        assert len(result["relations"]) == 2

        mock_graph_store.get_neighbors.assert_called_once_with(
            entity_id="e1",
            relation_types=None,
            max_depth=2,
        )

    @pytest.mark.asyncio
    async def test_get_neighbors_with_relation_types(
        self, global_config, mock_graph_store
    ):
        """relation_types 필터링"""
        from app.modules.core.tools.graph_search import get_neighbors

        result = await get_neighbors(
            arguments={
                "entity_id": "e1",
                "relation_types": ["partnership"],
                "max_depth": 3,
            },
            global_config=global_config,
        )

        assert result["success"] is True
        mock_graph_store.get_neighbors.assert_called_once_with(
            entity_id="e1",
            relation_types=["partnership"],
            max_depth=3,
        )

    @pytest.mark.asyncio
    async def test_get_neighbors_missing_entity_id_error(self, global_config):
        """entity_id 누락 시 ValueError"""
        from app.modules.core.tools.graph_search import get_neighbors

        with pytest.raises(ValueError, match="entity_id는 필수입니다"):
            await get_neighbors(
                arguments={},
                global_config=global_config,
            )

    @pytest.mark.asyncio
    async def test_get_neighbors_empty_entity_id_error(self, global_config):
        """빈 entity_id 시 ValueError"""
        from app.modules.core.tools.graph_search import get_neighbors

        with pytest.raises(ValueError, match="entity_id는 필수입니다"):
            await get_neighbors(
                arguments={"entity_id": ""},
                global_config=global_config,
            )

    @pytest.mark.asyncio
    async def test_get_neighbors_no_graph_store_error(self):
        """graph_store 미설정 시 ValueError"""
        from app.modules.core.tools.graph_search import get_neighbors

        with pytest.raises(ValueError, match="graph_store가 설정되지 않았습니다"):
            await get_neighbors(
                arguments={"entity_id": "e1"},
                global_config={},  # graph_store 없음
            )

    @pytest.mark.asyncio
    async def test_get_neighbors_store_error_propagation(
        self, global_config, mock_graph_store
    ):
        """graph_store.get_neighbors 에러 전파"""
        from app.modules.core.tools.graph_search import get_neighbors

        mock_graph_store.get_neighbors.side_effect = RuntimeError("엔티티 조회 실패")

        with pytest.raises(RuntimeError, match="엔티티 조회 실패"):
            await get_neighbors(
                arguments={"entity_id": "e1"},
                global_config=global_config,
            )


class TestFactoryIntegration:
    """ToolFactory와 통합 테스트"""

    def test_graph_tools_registered_in_factory(self):
        """SUPPORTED_TOOLS에 GraphRAG 도구 등록 확인"""
        from app.modules.core.tools.factory import SUPPORTED_TOOLS

        # 도구 등록 확인
        assert "search_graph" in SUPPORTED_TOOLS
        assert "get_neighbors" in SUPPORTED_TOOLS

        # 카테고리 확인
        assert SUPPORTED_TOOLS["search_graph"]["category"] == "graph"
        assert SUPPORTED_TOOLS["get_neighbors"]["category"] == "graph"

        # 모듈/함수 경로 확인
        assert "graph_search" in SUPPORTED_TOOLS["search_graph"]["module"]
        assert SUPPORTED_TOOLS["search_graph"]["function"] == "search_graph"

    def test_list_tools_by_graph_category(self):
        """graph 카테고리 도구 목록 조회"""
        from app.modules.core.tools import ToolFactory

        graph_tools = ToolFactory.list_tools_by_category("graph")

        assert "search_graph" in graph_tools
        assert "get_neighbors" in graph_tools
        assert len(graph_tools) == 2

    def test_get_tool_info(self):
        """도구 상세 정보 조회"""
        from app.modules.core.tools import ToolFactory

        info = ToolFactory.get_tool_info("search_graph")

        assert info is not None
        assert info["category"] == "graph"
        assert info["default_config"]["timeout"] == 15
        assert info["default_config"]["default_top_k"] == 10
