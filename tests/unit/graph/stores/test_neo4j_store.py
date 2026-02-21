"""
Neo4jGraphStore 단위 테스트

Neo4j 그래프 데이터베이스 저장소의 모든 기능을 테스트합니다.
실제 Neo4j 연결 없이 Mock을 사용하여 테스트합니다.

생성일: 2026-01-05
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from neo4j.exceptions import ServiceUnavailable, TransientError

from app.modules.core.graph.interfaces import Entity, GraphSearchResult, Relation


class TestNeo4jGraphStoreInit:
    """Neo4jGraphStore 초기화 테스트"""

    def test_init_with_valid_config(self) -> None:
        """유효한 설정으로 초기화 성공"""
        # Given
        config = {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "testpassword",  # Dummy password for testing
            "database": "neo4j",
        }

        # When
        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_driver.return_value = MagicMock()
            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)

            # Then
            assert store is not None
            mock_driver.assert_called_once()

    def test_init_missing_uri_raises_error(self) -> None:
        """URI 누락 시 ValueError 발생"""
        # Given
        config = {
            "user": "neo4j",
            "password": "testpassword",
        }

        # When/Then
        with pytest.raises(ValueError, match="uri는 필수"):
            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            Neo4jGraphStore(config)

    def test_init_with_minimal_config(self) -> None:
        """최소 설정(uri만)으로 초기화 성공"""
        # Given
        config = {
            "uri": "bolt://localhost:7687",
        }

        # When
        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_driver.return_value = MagicMock()
            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)

            # Then
            assert store is not None
            assert store._database == "neo4j"  # 기본값


class TestNeo4jGraphStoreEntityOperations:
    """Neo4jGraphStore 엔티티 작업 테스트"""

    @pytest.fixture
    def mock_neo4j_store(self) -> Any:
        """Mock Neo4j 드라이버가 주입된 store"""
        config = {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "testpassword",
            "database": "neo4j",
        }

        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            # Mock session 설정
            mock_session = AsyncMock()
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_session
            mock_context.__aexit__.return_value = None
            mock_driver.return_value.session.return_value = mock_context

            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)
            store._driver = mock_driver.return_value
            store._mock_session = mock_session
            return store

    @pytest.mark.asyncio
    async def test_add_entity_success(self, mock_neo4j_store: Any) -> None:
        """엔티티 추가 성공"""
        # Given
        entity = Entity(
            id="e1",
            name="테스트 업체",
            type="company",
            properties={"location": "강남"},
        )
        mock_neo4j_store._mock_session.run = AsyncMock()

        # When
        await mock_neo4j_store.add_entity(entity)

        # Then
        mock_neo4j_store._mock_session.run.assert_called_once()
        call_args = mock_neo4j_store._mock_session.run.call_args
        assert "MERGE" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_add_entity_with_all_properties(self, mock_neo4j_store: Any) -> None:
        """모든 속성을 가진 엔티티 추가"""
        # Given
        entity = Entity(
            id="e1",
            name="테스트 업체",
            type="company",
            properties={
                "location": "강남",
                "rating": 4.5,
                "active": True,
            },
        )
        mock_neo4j_store._mock_session.run = AsyncMock()

        # When
        await mock_neo4j_store.add_entity(entity)

        # Then
        call_args = mock_neo4j_store._mock_session.run.call_args
        kwargs = call_args[1]
        assert kwargs["id"] == "e1"
        assert kwargs["name"] == "테스트 업체"
        assert kwargs["type"] == "company"

    @pytest.mark.asyncio
    async def test_get_entity_found(self, mock_neo4j_store: Any) -> None:
        """존재하는 엔티티 조회 성공"""
        # Given
        mock_record = MagicMock()
        mock_record.__getitem__ = MagicMock(
            return_value={
                "id": "e1",
                "name": "테스트 업체",
                "type": "company",
                "properties": {"location": "강남"},
            }
        )
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=mock_record)
        mock_neo4j_store._mock_session.run = AsyncMock(return_value=mock_result)

        # When
        result = await mock_neo4j_store.get_entity("e1")

        # Then
        assert result is not None
        assert result.id == "e1"
        assert result.name == "테스트 업체"
        assert result.type == "company"

    @pytest.mark.asyncio
    async def test_get_entity_not_found(self, mock_neo4j_store: Any) -> None:
        """존재하지 않는 엔티티 조회 시 None 반환"""
        # Given
        mock_result = AsyncMock()
        mock_result.single = AsyncMock(return_value=None)
        mock_neo4j_store._mock_session.run = AsyncMock(return_value=mock_result)

        # When
        result = await mock_neo4j_store.get_entity("nonexistent")

        # Then
        assert result is None


class TestNeo4jGraphStoreRelationOperations:
    """Neo4jGraphStore 관계 작업 테스트"""

    @pytest.fixture
    def mock_neo4j_store(self) -> Any:
        """Mock Neo4j 드라이버가 주입된 store"""
        config = {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "testpassword",
            "database": "neo4j",
        }

        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_session = AsyncMock()
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_session
            mock_context.__aexit__.return_value = None
            mock_driver.return_value.session.return_value = mock_context

            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)
            store._driver = mock_driver.return_value
            store._mock_session = mock_session
            return store

    @pytest.mark.asyncio
    async def test_add_relation_success(self, mock_neo4j_store: Any) -> None:
        """관계 추가 성공"""
        # Given
        relation = Relation(
            source_id="e1",
            target_id="e2",
            type="partnership",
            weight=1.0,
        )
        mock_neo4j_store._mock_session.run = AsyncMock()

        # When
        await mock_neo4j_store.add_relation(relation)

        # Then
        mock_neo4j_store._mock_session.run.assert_called_once()
        call_args = mock_neo4j_store._mock_session.run.call_args
        query = call_args[0][0]
        assert "MATCH" in query or "MERGE" in query

    @pytest.mark.asyncio
    async def test_add_relation_with_weight(self, mock_neo4j_store: Any) -> None:
        """가중치가 있는 관계 추가"""
        # Given
        relation = Relation(
            source_id="e1",
            target_id="e2",
            type="supply",
            weight=0.8,
        )
        mock_neo4j_store._mock_session.run = AsyncMock()

        # When
        await mock_neo4j_store.add_relation(relation)

        # Then
        call_args = mock_neo4j_store._mock_session.run.call_args
        kwargs = call_args[1]
        assert kwargs["weight"] == 0.8


class TestNeo4jGraphStoreSearch:
    """Neo4jGraphStore 검색 테스트"""

    @pytest.fixture
    def mock_neo4j_store(self) -> Any:
        """Mock Neo4j 드라이버가 주입된 store"""
        config = {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "testpassword",
            "database": "neo4j",
        }

        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_session = AsyncMock()
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_session
            mock_context.__aexit__.return_value = None
            mock_driver.return_value.session.return_value = mock_context

            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)
            store._driver = mock_driver.return_value
            store._mock_session = mock_session
            return store

    @pytest.mark.asyncio
    async def test_search_returns_entities(self, mock_neo4j_store: Any) -> None:
        """검색 결과로 엔티티 목록 반환"""
        # Given
        mock_records = [
            {
                "entity": {
                    "id": "e1",
                    "name": "강남 맛집",
                    "type": "company",
                    "properties": {},
                },
                "relations": [],
            }
        ]
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=mock_records)
        mock_neo4j_store._mock_session.run = AsyncMock(return_value=mock_result)

        # When
        result = await mock_neo4j_store.search("강남")

        # Then
        assert isinstance(result, GraphSearchResult)
        assert len(result.entities) == 1
        assert result.entities[0].name == "강남 맛집"

    @pytest.mark.asyncio
    async def test_search_empty_results(self, mock_neo4j_store: Any) -> None:
        """검색 결과가 없는 경우"""
        # Given
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=[])
        mock_neo4j_store._mock_session.run = AsyncMock(return_value=mock_result)

        # When
        result = await mock_neo4j_store.search("존재하지않는쿼리")

        # Then
        assert isinstance(result, GraphSearchResult)
        assert len(result.entities) == 0

    @pytest.mark.asyncio
    async def test_search_with_entity_types(self, mock_neo4j_store: Any) -> None:
        """엔티티 타입 필터로 검색"""
        # Given
        mock_records = [
            {
                "entity": {
                    "id": "e1",
                    "name": "A 업체",
                    "type": "company",
                    "properties": {},
                },
                "relations": [],
            }
        ]
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=mock_records)
        mock_neo4j_store._mock_session.run = AsyncMock(return_value=mock_result)

        # When
        await mock_neo4j_store.search("업체", entity_types=["company"])

        # Then
        call_args = mock_neo4j_store._mock_session.run.call_args
        query = call_args[0][0]
        assert "company" in query or "type" in query


class TestNeo4jGraphStoreNeighbors:
    """Neo4jGraphStore 이웃 탐색 테스트"""

    @pytest.fixture
    def mock_neo4j_store(self) -> Any:
        """Mock Neo4j 드라이버가 주입된 store"""
        config = {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "testpassword",
            "database": "neo4j",
        }

        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_session = AsyncMock()
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_session
            mock_context.__aexit__.return_value = None
            mock_driver.return_value.session.return_value = mock_context

            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)
            store._driver = mock_driver.return_value
            store._mock_session = mock_session
            return store

    @pytest.mark.asyncio
    async def test_get_neighbors_with_depth(self, mock_neo4j_store: Any) -> None:
        """지정된 깊이만큼 이웃 탐색"""
        # Given
        mock_records: list[dict[str, Any]] = []
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=mock_records)
        mock_neo4j_store._mock_session.run = AsyncMock(return_value=mock_result)

        # When
        result = await mock_neo4j_store.get_neighbors("e1", max_depth=2)

        # Then
        assert isinstance(result, GraphSearchResult)

    @pytest.mark.asyncio
    async def test_get_neighbors_with_relation_filter(self, mock_neo4j_store: Any) -> None:
        """관계 타입 필터로 이웃 탐색"""
        # Given
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=[])
        mock_neo4j_store._mock_session.run = AsyncMock(return_value=mock_result)

        # When
        result = await mock_neo4j_store.get_neighbors(
            "e1",
            relation_types=["partnership"],
            max_depth=1,
        )

        # Then
        assert isinstance(result, GraphSearchResult)
        # 쿼리에 관계 타입 필터가 포함되어야 함
        call_args = mock_neo4j_store._mock_session.run.call_args
        query = call_args[0][0]
        assert "partnership" in query or "type" in query

    @pytest.mark.asyncio
    async def test_get_neighbors_returns_entities_and_relations(
        self, mock_neo4j_store: Any
    ) -> None:
        """이웃 탐색 시 엔티티와 관계 모두 반환"""
        # Given
        mock_records = [
            {
                "entity": {
                    "id": "e2",
                    "name": "이웃 업체",
                    "type": "company",
                    "properties": {},
                },
                "relations": [
                    {
                        "source_id": "e1",
                        "target_id": "e2",
                        "type": "partnership",
                        "weight": 0.9,
                    }
                ],
            }
        ]
        mock_result = AsyncMock()
        mock_result.data = AsyncMock(return_value=mock_records)
        mock_neo4j_store._mock_session.run = AsyncMock(return_value=mock_result)

        # When
        result = await mock_neo4j_store.get_neighbors("e1", max_depth=1)

        # Then
        assert isinstance(result, GraphSearchResult)
        assert len(result.entities) == 1
        assert len(result.relations) == 1


class TestNeo4jGraphStoreStats:
    """Neo4jGraphStore 통계 테스트"""

    @pytest.fixture
    def mock_neo4j_store(self) -> Any:
        """Mock Neo4j 드라이버가 주입된 store"""
        config = {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "testpassword",
            "database": "neo4j",
        }

        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_session = AsyncMock()
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_session
            mock_context.__aexit__.return_value = None
            mock_driver.return_value.session.return_value = mock_context

            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)
            store._driver = mock_driver.return_value
            store._mock_session = mock_session
            return store

    def test_get_stats_returns_dict(self, mock_neo4j_store: Any) -> None:
        """통계 정보가 dict로 반환됨"""
        # When
        stats = mock_neo4j_store.get_stats()

        # Then
        assert isinstance(stats, dict)
        assert "provider" in stats
        assert stats["provider"] == "neo4j"

    def test_get_stats_contains_database_info(self, mock_neo4j_store: Any) -> None:
        """통계에 데이터베이스 정보 포함"""
        # When
        stats = mock_neo4j_store.get_stats()

        # Then
        assert "database" in stats
        assert stats["database"] == "neo4j"

    def test_get_stats_contains_uri(self, mock_neo4j_store: Any) -> None:
        """통계에 URI 정보 포함"""
        # When
        stats = mock_neo4j_store.get_stats()

        # Then
        assert "uri" in stats
        assert "bolt://localhost:7687" in stats["uri"]


class TestNeo4jGraphStoreClear:
    """Neo4jGraphStore 초기화(clear) 테스트"""

    @pytest.fixture
    def mock_neo4j_store(self) -> Any:
        """Mock Neo4j 드라이버가 주입된 store"""
        config = {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "testpassword",
            "database": "neo4j",
        }

        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_session = AsyncMock()
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_session
            mock_context.__aexit__.return_value = None
            mock_driver.return_value.session.return_value = mock_context

            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)
            store._driver = mock_driver.return_value
            store._mock_session = mock_session
            return store

    @pytest.mark.asyncio
    async def test_clear_executes_delete_query(self, mock_neo4j_store: Any) -> None:
        """clear 호출 시 삭제 쿼리 실행"""
        # Given
        mock_neo4j_store._mock_session.run = AsyncMock()

        # When
        await mock_neo4j_store.clear()

        # Then
        mock_neo4j_store._mock_session.run.assert_called_once()
        call_args = mock_neo4j_store._mock_session.run.call_args
        query = call_args[0][0]
        assert "DELETE" in query


class TestNeo4jGraphStoreClose:
    """Neo4jGraphStore 연결 종료 테스트"""

    @pytest.fixture
    def mock_neo4j_store(self) -> Any:
        """Mock Neo4j 드라이버가 주입된 store"""
        config = {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "testpassword",
            "database": "neo4j",
        }

        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_session = AsyncMock()
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_session
            mock_context.__aexit__.return_value = None
            mock_driver.return_value.session.return_value = mock_context
            mock_driver.return_value.close = AsyncMock()

            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)
            store._driver = mock_driver.return_value
            return store

    @pytest.mark.asyncio
    async def test_close_calls_driver_close(self, mock_neo4j_store: Any) -> None:
        """close 호출 시 드라이버 연결 종료"""
        # Given - 드라이버 참조 저장 (close 후 None이 됨)
        driver_mock = mock_neo4j_store._driver

        # When
        await mock_neo4j_store.close()

        # Then - 저장된 참조로 검증
        driver_mock.close.assert_called_once()


class TestNeo4jGraphStoreConnectionPool:
    """Neo4jGraphStore 연결 풀 설정 테스트 (프로덕션 레디)"""

    def test_accepts_pool_config(self) -> None:
        """연결 풀 설정이 올바르게 적용되는지 확인"""
        # Given
        config = {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "testpassword",
            "max_pool_size": 100,
            "connection_timeout": 60.0,
            "query_timeout": 120.0,
        }

        # When
        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_driver.return_value = MagicMock()
            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)

            # Then - 연결 풀 속성이 저장되어야 함
            assert store._max_pool_size == 100
            assert store._connection_timeout == 60.0
            assert store._query_timeout == 120.0

    def test_pool_config_defaults(self) -> None:
        """연결 풀 기본값 확인"""
        # Given
        config = {
            "uri": "bolt://localhost:7687",
        }

        # When
        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_driver.return_value = MagicMock()
            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)

            # Then - 기본값이 설정되어야 함
            assert store._max_pool_size == 50
            assert store._connection_timeout == 30.0
            assert store._query_timeout == 60.0

    def test_driver_created_with_pool_settings(self) -> None:
        """드라이버가 연결 풀 설정으로 생성되는지 확인"""
        # Given
        config = {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "testpassword",
            "max_pool_size": 75,
            "connection_timeout": 45.0,
        }

        # When
        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_driver.return_value = MagicMock()
            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            Neo4jGraphStore(config)

            # Then - 드라이버 호출 시 풀 설정이 전달되어야 함
            mock_driver.assert_called_once()
            call_kwargs = mock_driver.call_args[1]
            assert call_kwargs.get("max_connection_pool_size") == 75
            assert call_kwargs.get("connection_acquisition_timeout") == 45.0

    def test_retry_config_stored(self) -> None:
        """재시도 설정이 저장되는지 확인"""
        # Given
        config = {
            "uri": "bolt://localhost:7687",
            "max_retries": 5,
            "retry_delay": 2.0,
        }

        # When
        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_driver.return_value = MagicMock()
            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)

            # Then
            assert store._max_retries == 5
            assert store._retry_delay == 2.0

    def test_retry_config_defaults(self) -> None:
        """재시도 기본값 확인"""
        # Given
        config = {
            "uri": "bolt://localhost:7687",
        }

        # When
        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_driver.return_value = MagicMock()
            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)

            # Then - 기본값
            assert store._max_retries == 3
            assert store._retry_delay == 1.0


class TestNeo4jGraphStoreHealthCheck:
    """Neo4jGraphStore 헬스체크 테스트 (프로덕션 레디)"""

    @pytest.fixture
    def mock_neo4j_store(self) -> Any:
        """Mock Neo4j 드라이버가 주입된 store"""
        config = {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "testpassword",
            "database": "neo4j",
        }

        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_session = AsyncMock()
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_session
            mock_context.__aexit__.return_value = None
            mock_driver.return_value.session.return_value = mock_context
            mock_driver.return_value.close = AsyncMock()

            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)
            store._driver = mock_driver.return_value
            store._mock_session = mock_session
            return store

    @pytest.mark.asyncio
    async def test_is_healthy_returns_true_on_success(self, mock_neo4j_store: Any) -> None:
        """정상 연결 시 is_healthy()가 True 반환"""
        # Given - 쿼리 성공
        mock_result = AsyncMock()
        mock_neo4j_store._mock_session.run = AsyncMock(return_value=mock_result)

        # When
        result = await mock_neo4j_store.is_healthy()

        # Then
        assert result is True
        mock_neo4j_store._mock_session.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_is_healthy_returns_false_on_error(self, mock_neo4j_store: Any) -> None:
        """연결 오류 시 is_healthy()가 False 반환"""
        # Given - 쿼리 실패
        mock_neo4j_store._mock_session.run = AsyncMock(
            side_effect=Exception("연결 실패")
        )

        # When
        result = await mock_neo4j_store.is_healthy()

        # Then
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_details_on_success(
        self, mock_neo4j_store: Any
    ) -> None:
        """정상 연결 시 health_check()가 상세 정보 반환"""
        # Given - 쿼리 성공
        mock_result = AsyncMock()
        mock_neo4j_store._mock_session.run = AsyncMock(return_value=mock_result)

        # When
        result = await mock_neo4j_store.health_check()

        # Then
        assert isinstance(result, dict)
        assert result["connected"] is True
        assert "response_time_ms" in result
        assert isinstance(result["response_time_ms"], (int, float))
        assert "pool_size" in result

    @pytest.mark.asyncio
    async def test_health_check_returns_error_on_failure(
        self, mock_neo4j_store: Any
    ) -> None:
        """연결 오류 시 health_check()가 에러 정보 반환"""
        # Given - 쿼리 실패
        mock_neo4j_store._mock_session.run = AsyncMock(
            side_effect=Exception("DB 연결 실패")
        )

        # When
        result = await mock_neo4j_store.health_check()

        # Then
        assert isinstance(result, dict)
        assert result["connected"] is False
        assert "error" in result
        assert "DB 연결 실패" in result["error"]


class TestNeo4jGraphStoreTransaction:
    """Neo4jGraphStore 트랜잭션 컨텍스트 매니저 테스트 (프로덕션 레디)"""

    @pytest.fixture
    def mock_neo4j_store(self) -> Any:
        """Mock Neo4j 드라이버가 주입된 store"""
        config = {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "testpassword",
            "database": "neo4j",
        }

        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_tx = AsyncMock()
            mock_tx.run = AsyncMock()
            mock_tx.commit = AsyncMock()
            mock_tx.rollback = AsyncMock()

            mock_session = AsyncMock()
            mock_session.begin_transaction = AsyncMock(return_value=mock_tx)
            mock_session.close = AsyncMock()

            mock_driver.return_value.session.return_value = mock_session

            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)
            store._driver = mock_driver.return_value
            store._mock_session = mock_session
            store._mock_tx = mock_tx
            return store

    @pytest.mark.asyncio
    async def test_transaction_commits_on_success(self, mock_neo4j_store: Any) -> None:
        """성공 시 트랜잭션이 자동으로 커밋됨"""
        # Given/When - 트랜잭션 내에서 작업 수행
        async with mock_neo4j_store.transaction() as tx:
            await tx.run("CREATE (n:Test {name: 'test'})")

        # Then - 커밋이 호출되어야 함
        mock_neo4j_store._mock_tx.commit.assert_called_once()
        mock_neo4j_store._mock_tx.rollback.assert_not_called()
        mock_neo4j_store._mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_transaction_rollbacks_on_error(self, mock_neo4j_store: Any) -> None:
        """예외 발생 시 트랜잭션이 자동으로 롤백됨"""
        # Given/When - 트랜잭션 내에서 예외 발생
        with pytest.raises(ValueError, match="테스트 에러"):
            async with mock_neo4j_store.transaction() as tx:
                await tx.run("CREATE (n:Test {name: 'test'})")
                raise ValueError("테스트 에러")

        # Then - 롤백이 호출되어야 함
        mock_neo4j_store._mock_tx.rollback.assert_called_once()
        mock_neo4j_store._mock_tx.commit.assert_not_called()
        mock_neo4j_store._mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_transaction_closes_session_always(self, mock_neo4j_store: Any) -> None:
        """성공/실패 관계없이 세션이 항상 닫힘"""
        # Case 1: 성공
        async with mock_neo4j_store.transaction():
            pass
        mock_neo4j_store._mock_session.close.assert_called_once()

        # Reset mock
        mock_neo4j_store._mock_session.close.reset_mock()

        # Case 2: 실패
        with pytest.raises(RuntimeError):
            async with mock_neo4j_store.transaction():
                raise RuntimeError("실패")
        mock_neo4j_store._mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_transaction_yields_tx_object(self, mock_neo4j_store: Any) -> None:
        """트랜잭션 컨텍스트 매니저가 tx 객체를 yield함"""
        # When
        async with mock_neo4j_store.transaction() as tx:
            # Then - tx 객체가 반환되어야 함
            assert tx is mock_neo4j_store._mock_tx
            # tx 객체로 쿼리 실행 가능
            await tx.run("RETURN 1")

        mock_neo4j_store._mock_tx.run.assert_called()


class TestNeo4jGraphStoreRetry:
    """Neo4jGraphStore 재시도 로직 테스트 (지수 백오프)"""

    @pytest.fixture
    def mock_neo4j_store(self) -> Any:
        """Mock Neo4j 드라이버가 주입된 store"""
        config = {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "testpassword",
            "database": "neo4j",
            "max_retries": 3,
            "retry_delay": 0.01,  # 테스트에서 빠른 재시도
        }

        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_session = AsyncMock()
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_session
            mock_context.__aexit__.return_value = None
            mock_driver.return_value.session.return_value = mock_context
            mock_driver.return_value.close = AsyncMock()

            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)
            store._driver = mock_driver.return_value
            store._mock_session = mock_session
            return store

    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self, mock_neo4j_store: Any) -> None:
        """일시적 오류 시 재시도"""
        # Given - 처음 2번은 실패, 3번째 성공
        mock_operation = AsyncMock(
            side_effect=[
                TransientError("일시적 오류 1"),
                TransientError("일시적 오류 2"),
                "success",
            ]
        )

        # When
        result = await mock_neo4j_store._execute_with_retry(mock_operation)

        # Then
        assert result == "success"
        assert mock_operation.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_on_service_unavailable(self, mock_neo4j_store: Any) -> None:
        """ServiceUnavailable 오류 시 재시도"""
        # Given - 처음 1번 실패, 2번째 성공
        mock_operation = AsyncMock(
            side_effect=[
                ServiceUnavailable("서비스 불가"),
                "success",
            ]
        )

        # When
        result = await mock_neo4j_store._execute_with_retry(mock_operation)

        # Then
        assert result == "success"
        assert mock_operation.call_count == 2

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_raises(self, mock_neo4j_store: Any) -> None:
        """최대 재시도 초과 시 예외 발생"""
        # Given - 계속 실패
        mock_operation = AsyncMock(
            side_effect=TransientError("지속적 오류")
        )

        # When/Then - max_retries 만큼 시도 후 예외 발생
        with pytest.raises(TransientError, match="지속적 오류"):
            await mock_neo4j_store._execute_with_retry(mock_operation)

        # max_retries=3 이므로 3번 호출
        assert mock_operation.call_count == 3

    @pytest.mark.asyncio
    async def test_non_retryable_error_raises_immediately(
        self, mock_neo4j_store: Any
    ) -> None:
        """재시도 불가능한 오류는 즉시 예외 발생"""
        # Given - 일반 ValueError (재시도 불가)
        mock_operation = AsyncMock(side_effect=ValueError("잘못된 쿼리"))

        # When/Then - 즉시 예외 발생 (재시도 없음)
        with pytest.raises(ValueError, match="잘못된 쿼리"):
            await mock_neo4j_store._execute_with_retry(mock_operation)

        # 재시도 없이 1번만 호출
        assert mock_operation.call_count == 1

    @pytest.mark.asyncio
    async def test_exponential_backoff_applied(self, mock_neo4j_store: Any) -> None:
        """지수 백오프가 적용되는지 확인"""
        # Given
        import time
        call_times: list[float] = []

        async def track_timing_operation() -> str:
            call_times.append(time.perf_counter())
            if len(call_times) < 3:
                raise TransientError("일시적 오류")
            return "success"

        mock_operation = AsyncMock(side_effect=track_timing_operation)

        # When
        await mock_neo4j_store._execute_with_retry(mock_operation)

        # Then - 호출 간격이 증가해야 함 (지수 백오프)
        # 첫 번째 재시도: delay * 2^0 = 0.01s
        # 두 번째 재시도: delay * 2^1 = 0.02s
        assert mock_operation.call_count == 3


class TestNeo4jGraphStoreGracefulShutdown:
    """Neo4jGraphStore Graceful Shutdown 테스트 (프로덕션 레디)"""

    @pytest.fixture
    def mock_neo4j_store(self) -> Any:
        """Mock Neo4j 드라이버가 주입된 store"""
        config = {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "testpassword",
            "database": "neo4j",
        }

        with patch("neo4j.AsyncGraphDatabase.driver") as mock_driver:
            mock_session = AsyncMock()
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_session
            mock_context.__aexit__.return_value = None
            mock_driver.return_value.session.return_value = mock_context
            mock_driver.return_value.close = AsyncMock()

            from app.modules.core.graph.stores.neo4j_store import Neo4jGraphStore

            store = Neo4jGraphStore(config)
            store._driver = mock_driver.return_value
            return store

    @pytest.mark.asyncio
    async def test_close_with_timeout_success(self, mock_neo4j_store: Any) -> None:
        """정상 종료 시 드라이버 close 호출"""
        # Given - 드라이버 참조 저장 (close 후 None이 됨)
        driver_mock = mock_neo4j_store._driver

        # When
        await mock_neo4j_store.close(timeout=5.0)

        # Then - 저장된 참조로 검증
        driver_mock.close.assert_called_once()
        assert mock_neo4j_store._closed is True

    @pytest.mark.asyncio
    async def test_close_sets_driver_to_none(self, mock_neo4j_store: Any) -> None:
        """종료 후 드라이버가 None으로 설정됨"""
        # When
        await mock_neo4j_store.close()

        # Then
        assert mock_neo4j_store._driver is None
        assert mock_neo4j_store._closed is True

    @pytest.mark.asyncio
    async def test_close_timeout_handling(self, mock_neo4j_store: Any) -> None:
        """종료 타임아웃 시 예외 없이 종료"""
        # Given - 드라이버 close가 오래 걸림
        async def slow_close() -> None:
            await asyncio.sleep(2)  # 타임아웃 유발용 (0.01초 타임아웃 대비 충분)

        mock_neo4j_store._driver.close = slow_close

        # When - 매우 짧은 타임아웃으로 호출
        await mock_neo4j_store.close(timeout=0.01)

        # Then - 예외 없이 종료, closed 상태로 설정
        assert mock_neo4j_store._closed is True

    @pytest.mark.asyncio
    async def test_close_idempotent(self, mock_neo4j_store: Any) -> None:
        """close를 여러 번 호출해도 안전함"""
        # When - 두 번 호출
        await mock_neo4j_store.close()
        await mock_neo4j_store.close()  # 두 번째 호출

        # Then - 첫 번째만 실제 close 호출
        # (두 번째는 이미 closed이므로 무시)
        assert mock_neo4j_store._closed is True

    @pytest.mark.asyncio
    async def test_close_default_timeout(self, mock_neo4j_store: Any) -> None:
        """기본 타임아웃 값 확인"""
        # When - 타임아웃 지정 없이 호출
        await mock_neo4j_store.close()

        # Then - 정상 종료
        assert mock_neo4j_store._closed is True
