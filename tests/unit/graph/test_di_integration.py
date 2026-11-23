"""
GraphRAG DI Container 통합 테스트

DI Container에 등록된 GraphRAG 컴포넌트들의 통합 테스트.
- graph_store: NetworkXGraphStore 저장소
- entity_extractor: LLMEntityExtractor 엔티티 추출기
- relation_extractor: LLMRelationExtractor 관계 추출기
- knowledge_graph_builder: KnowledgeGraphBuilder 빌더
"""
import pytest


class TestGraphRAGDIIntegration:
    """GraphRAG DI Container 통합 테스트"""

    @pytest.fixture
    def mock_config(self):
        """테스트용 설정"""
        return {
            "graph_rag": {
                "enabled": True,
                "provider": "networkx",
                "extraction": {
                    "entity_extractor": "llm",
                    "relation_extractor": "llm",
                    "llm": {
                        "model": "google/gemini-2.5-flash-lite",
                        "max_entities_per_chunk": 20,
                        "max_relations_per_chunk": 30,
                    },
                },
            }
        }

    @pytest.fixture
    def disabled_config(self):
        """비활성화 설정"""
        return {
            "graph_rag": {
                "enabled": False,
            }
        }

    def test_container_has_graph_store_provider(self):
        """Container에 graph_store provider 존재 확인"""
        from app.core.di_container import AppContainer

        container = AppContainer()
        assert hasattr(container, "graph_store")

    def test_graph_store_disabled_returns_none(self, disabled_config):
        """비활성화 시 None 반환"""
        from app.modules.core.graph import GraphRAGFactory

        store = GraphRAGFactory.create(disabled_config)
        assert store is None

    def test_graph_store_enabled_returns_instance(self, mock_config):
        """활성화 시 인스턴스 반환"""
        from app.modules.core.graph import GraphRAGFactory

        store = GraphRAGFactory.create(mock_config)
        assert store is not None
        assert store.__class__.__name__ == "NetworkXGraphStore"

    @pytest.mark.asyncio
    async def test_graph_store_basic_operations(self, mock_config):
        """기본 CRUD 동작 확인"""
        from app.modules.core.graph import Entity, GraphRAGFactory, Relation

        store = GraphRAGFactory.create(mock_config)

        # 엔티티 추가
        entity = Entity(id="test-1", name="테스트 업체", type="company")
        await store.add_entity(entity)

        # 조회
        retrieved = await store.get_entity("test-1")
        assert retrieved is not None
        assert retrieved.name == "테스트 업체"

        # 관계 추가
        relation = Relation(source_id="test-1", target_id="test-2", type="partnership")
        await store.add_relation(relation)

        # 통계
        stats = store.get_stats()
        assert stats["node_count"] >= 1

    def test_container_has_entity_extractor_provider(self):
        """Container에 entity_extractor provider 존재 확인"""
        from app.core.di_container import AppContainer

        container = AppContainer()
        assert hasattr(container, "entity_extractor")

    def test_container_has_relation_extractor_provider(self):
        """Container에 relation_extractor provider 존재 확인"""
        from app.core.di_container import AppContainer

        container = AppContainer()
        assert hasattr(container, "relation_extractor")

    def test_container_has_knowledge_graph_builder_provider(self):
        """Container에 knowledge_graph_builder provider 존재 확인"""
        from app.core.di_container import AppContainer

        container = AppContainer()
        assert hasattr(container, "knowledge_graph_builder")

    @pytest.mark.asyncio
    async def test_entity_extractor_disabled_returns_none(self, disabled_config):
        """GraphRAG 비활성화 시 entity_extractor None 반환"""
        from app.core.di_container import create_entity_extractor_instance

        extractor = await create_entity_extractor_instance(disabled_config, None)
        assert extractor is None

    @pytest.mark.asyncio
    async def test_relation_extractor_disabled_returns_none(self, disabled_config):
        """GraphRAG 비활성화 시 relation_extractor None 반환"""
        from app.core.di_container import create_relation_extractor_instance

        extractor = await create_relation_extractor_instance(disabled_config, None)
        assert extractor is None

    @pytest.mark.asyncio
    async def test_knowledge_graph_builder_disabled_returns_none(self, disabled_config):
        """GraphRAG 비활성화 시 knowledge_graph_builder None 반환"""
        from app.core.di_container import create_knowledge_graph_builder_instance

        builder = await create_knowledge_graph_builder_instance(
            disabled_config, None, None, None
        )
        assert builder is None

    @pytest.mark.asyncio
    async def test_mcp_server_has_graph_store_in_global_config(self, mock_config):
        """MCP 서버 global_config에 graph_store 포함 확인"""
        from unittest.mock import AsyncMock, MagicMock, patch

        # MCP 활성화 설정 추가
        config = {
            **mock_config,
            "mcp": {
                "enabled": True,
                "server_name": "test-server",
                "tools": {},
            },
        }

        # MCPToolFactory.create 모킹
        mock_server = MagicMock()
        mock_server.initialize = AsyncMock()
        mock_server.server_name = "test-server"
        mock_server._global_config = {}

        with patch(
            "app.core.di_container.MCPToolFactory.create",
            return_value=mock_server,
        ):
            from app.core.di_container import create_mcp_server_instance

            mock_graph_store = MagicMock()
            result = await create_mcp_server_instance(
                config,
                retriever=None,
                graph_store=mock_graph_store,
            )

            # graph_store가 global_config에 포함되었는지 확인
            assert result is not None
            assert "graph_store" in result._global_config
            assert result._global_config["graph_store"] == mock_graph_store
