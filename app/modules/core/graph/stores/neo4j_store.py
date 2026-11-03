"""
Neo4jGraphStore - Neo4j 그래프 데이터베이스 저장소

프로덕션 환경을 위한 대규모 지식 그래프 저장소입니다.
IGraphStore 프로토콜을 구현하며, Neo4j의 Cypher 쿼리를 사용합니다.

주요 기능:
- 엔티티/관계 CRUD (MERGE 사용으로 중복 방지)
- 깊이 기반 이웃 탐색 (가변 길이 경로)
- 전문 검색 (CONTAINS 기반, 향후 Full-text index 확장 가능)
- 비동기 드라이버 지원

생성일: 2026-01-05
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, TypeVar

from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import ServiceUnavailable, TransientError

from app.lib.logger import get_logger
from app.lib.retry import RetryCallState, RetryPolicy
from app.modules.core.graph.interfaces import IGraphStore
from app.modules.core.graph.models import Entity, GraphSearchResult, Relation

if TYPE_CHECKING:
    pass

T = TypeVar("T")

logger = get_logger(__name__)


class Neo4jGraphStore(IGraphStore):
    """
    Neo4j 기반 그래프 저장소

    대규모 프로덕션 환경을 위한 그래프 데이터베이스 저장소입니다.
    비동기 드라이버를 사용하여 높은 동시성을 지원합니다.

    Attributes:
        _driver: Neo4j AsyncDriver 인스턴스
        _database: 사용할 데이터베이스 이름
        _config: 설정 딕셔너리
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Neo4jGraphStore 초기화

        Args:
            config: 설정 딕셔너리
                - uri (str): Neo4j URI (bolt://host:port) - 필수
                - user (str): 사용자명 (기본값: "neo4j")
                - password (str): 비밀번호 (기본값: "")
                - database (str): 데이터베이스 이름 (기본값: "neo4j")
                - max_pool_size (int): 최대 연결 풀 크기 (기본값: 50)
                - connection_timeout (float): 연결 획득 타임아웃 초 (기본값: 30.0)
                - query_timeout (float): 쿼리 실행 타임아웃 초 (기본값: 60.0)
                - max_retries (int): 최대 재시도 횟수 (기본값: 3)
                - retry_delay (float): 재시도 대기 시간 초 (기본값: 1.0)

        Raises:
            ValueError: uri가 누락된 경우
        """
        uri = config.get("uri")
        if not uri:
            raise ValueError("uri는 필수입니다")

        user = config.get("user", "neo4j")
        password = config.get("password", "")
        self._database = config.get("database", "neo4j")
        self._config = config

        # 연결 풀 설정 (프로덕션 레디)
        self._max_pool_size = config.get("max_pool_size", 50)
        self._connection_timeout = config.get("connection_timeout", 30.0)
        self._query_timeout = config.get("query_timeout", 60.0)

        # 재시도 설정
        self._max_retries = config.get("max_retries", 3)
        self._retry_delay = config.get("retry_delay", 1.0)

        # 상태 추적
        self._closed = False

        # Neo4j 비동기 드라이버 초기화 (연결 풀 설정 적용)
        self._driver: AsyncDriver | None = AsyncGraphDatabase.driver(
            uri,
            auth=(user, password) if user and password else None,
            max_connection_pool_size=self._max_pool_size,
            connection_acquisition_timeout=self._connection_timeout,
        )

        logger.info(
            f"Neo4jGraphStore 초기화: uri={uri}, database={self._database}, "
            f"pool_size={self._max_pool_size}, timeout={self._connection_timeout}s"
        )

    def _get_driver(self) -> AsyncDriver:
        """초기화된 Neo4j AsyncDriver 반환"""
        if self._driver is None:
            raise RuntimeError("Neo4j driver is not initialized or already closed")
        return self._driver

    async def close(self, timeout: float = 30.0) -> None:
        """
        Graceful Shutdown - 드라이버 연결 안전 종료

        리소스 정리를 위해 애플리케이션 종료 시 호출해야 합니다.
        타임아웃 내에 종료되지 않으면 강제 종료합니다.

        Args:
            timeout: 종료 대기 시간 (초, 기본값: 30.0)
        """
        if self._driver is None or self._closed:
            # 이미 종료됨 (멱등성 보장)
            return

        try:
            await asyncio.wait_for(self._driver.close(), timeout=timeout)
            logger.info("Neo4j 드라이버 정상 종료")
        except TimeoutError:
            logger.warning(f"Neo4j 종료 타임아웃 ({timeout}초), 강제 종료")
        except Exception as e:
            logger.error(f"Neo4j 종료 중 오류: {e}")
        finally:
            self._driver = None
            self._closed = True

    async def is_healthy(self) -> bool:
        """
        빠른 헬스체크 - 연결 가능 여부만 확인

        간단한 쿼리를 실행하여 Neo4j 연결 상태를 확인합니다.
        프로덕션 환경의 로드밸런서 헬스체크에 적합합니다.

        Returns:
            bool: 연결 가능하면 True, 불가능하면 False
        """
        try:
            driver = self._get_driver()
            async with driver.session(database=self._database) as session:
                await session.run("RETURN 1")
            return True
        except Exception as e:
            logger.warning(f"Neo4j 헬스체크 실패: {e}")
            return False

    async def health_check(self) -> dict[str, Any]:
        """
        상세 헬스체크 - 연결 상태와 성능 정보 반환

        연결 상태, 응답 시간, 연결 풀 정보 등을 포함합니다.
        모니터링 대시보드나 상세 상태 확인에 적합합니다.

        Returns:
            dict: 상세 헬스체크 결과
                - connected (bool): 연결 상태
                - response_time_ms (float): 응답 시간 (밀리초)
                - pool_size (int): 연결 풀 크기
                - database (str): 데이터베이스 이름
                - error (str, optional): 오류 메시지 (실패 시)
        """
        start = time.perf_counter()
        try:
            driver = self._get_driver()
            async with driver.session(database=self._database) as session:
                await session.run("RETURN 1")
            elapsed = (time.perf_counter() - start) * 1000

            return {
                "connected": True,
                "response_time_ms": round(elapsed, 2),
                "pool_size": self._max_pool_size,
                "database": self._database,
            }
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.warning(f"Neo4j 헬스체크 실패: {e}")
            return {
                "connected": False,
                "response_time_ms": round(elapsed, 2),
                "error": str(e),
            }

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        """
        트랜잭션 컨텍스트 매니저

        여러 그래프 작업을 원자적으로 실행합니다.
        성공 시 자동 커밋, 예외 발생 시 자동 롤백됩니다.

        Usage:
            async with store.transaction() as tx:
                await tx.run("CREATE (n:Test {name: 'test'})")
                await tx.run("CREATE (m:Test {name: 'test2'})")
            # 블록을 벗어나면 자동 커밋

            # 예외 발생 시 자동 롤백
            async with store.transaction() as tx:
                await tx.run("CREATE (n:Test)")
                raise ValueError("rollback!")  # 자동 롤백

        Yields:
            AsyncManagedTransaction: Neo4j 트랜잭션 객체
        """
        driver = self._get_driver()
        session = driver.session(database=self._database)
        tx = await session.begin_transaction()
        try:
            yield tx
            await tx.commit()
            logger.debug("트랜잭션 커밋 완료")
        except Exception as e:
            await tx.rollback()
            logger.warning(f"트랜잭션 롤백: {e}")
            raise
        finally:
            await session.close()

    async def _execute_with_retry(
        self,
        operation: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """
        지수 백오프를 적용한 재시도 로직 (공용 ``app.lib.retry.RetryPolicy`` 사용)

        일시적인 Neo4j 오류(TransientError, ServiceUnavailable) 발생 시
        지정된 횟수만큼 재시도합니다. 재시도 간 대기 시간은
        지수적으로 증가합니다 (delay * 2^attempt).

        Args:
            operation: 실행할 비동기 함수
            *args: 함수에 전달할 위치 인자
            **kwargs: 함수에 전달할 키워드 인자

        Returns:
            T: operation 함수의 반환값

        Raises:
            TransientError: 최대 재시도 횟수 초과 시
            ServiceUnavailable: 최대 재시도 횟수 초과 시
            Exception: 재시도 불가능한 오류는 즉시 발생
        """
        max_retries = self._max_retries

        def _log_retry(retry_state: RetryCallState) -> None:
            """재시도 직전(before_sleep) 경고 로그"""
            outcome = retry_state.outcome
            error = outcome.exception() if outcome is not None else None
            next_action = retry_state.next_action
            delay = float(next_action.sleep) if next_action is not None else 0.0
            logger.warning(
                f"Neo4j 재시도 {retry_state.attempt_number}/{max_retries}, "
                f"대기 {delay:.2f}초: {error}"
            )

        # 공용 RetryPolicy: 지수 백오프 delay * 2^attempt (jitter 없음, 상한 없음)
        policy = RetryPolicy(
            retry_exceptions=(TransientError, ServiceUnavailable),
            max_attempts=max_retries,
            initial_delay_s=self._retry_delay,
            max_delay_s=float("inf"),
            jitter_s=0.0,
            before_sleep=_log_retry,
        )
        async for attempt in policy.build_async_retrying():
            with attempt:
                return await operation(*args, **kwargs)

        # 이 지점에 도달하면 안 됨 (방어적 코드)
        raise RuntimeError("Unexpected state in retry logic")  # pragma: no cover

    async def add_entity(self, entity: Entity) -> None:
        """
        엔티티를 그래프에 추가합니다.

        MERGE를 사용하여 중복 생성을 방지합니다.
        이미 존재하는 엔티티는 속성이 업데이트됩니다.

        Args:
            entity: 추가할 엔티티
        """
        # MERGE를 사용하여 중복 방지
        query = """
        MERGE (e:Entity {id: $id})
        SET e.name = $name,
            e.type = $type,
            e.properties = $properties
        """

        driver = self._get_driver()
        async with driver.session(database=self._database) as session:
            await session.run(
                query,
                id=entity.id,
                name=entity.name,
                type=entity.type,
                properties=dict(entity.properties) if entity.properties else {},
            )

        logger.debug(f"엔티티 추가: {entity.id} ({entity.type})")

    async def add_relation(self, relation: Relation) -> None:
        """
        관계를 그래프에 추가합니다.

        MERGE를 사용하여 중복 관계를 방지합니다.
        소스/타겟 노드가 없으면 자동으로 플레이스홀더를 생성합니다.

        Args:
            relation: 추가할 관계
        """
        # MERGE를 사용하여 노드가 없으면 생성, 관계도 중복 방지
        query = """
        MERGE (s:Entity {id: $source_id})
        MERGE (t:Entity {id: $target_id})
        MERGE (s)-[r:RELATES_TO]->(t)
        SET r.type = $type,
            r.weight = $weight
        """

        driver = self._get_driver()
        async with driver.session(database=self._database) as session:
            await session.run(
                query,
                source_id=relation.source_id,
                target_id=relation.target_id,
                type=relation.type,
                weight=relation.weight,
            )

        logger.debug(
            f"관계 추가: {relation.source_id} -[{relation.type}]-> {relation.target_id}"
        )

    async def get_entity(self, entity_id: str) -> Entity | None:
        """
        ID로 엔티티를 조회합니다.

        Args:
            entity_id: 조회할 엔티티 ID

        Returns:
            Entity 또는 None (엔티티가 없는 경우)
        """
        query = """
        MATCH (e:Entity {id: $id})
        RETURN e {.id, .name, .type, .properties} as entity
        """

        driver = self._get_driver()
        async with driver.session(database=self._database) as session:
            result = await session.run(query, id=entity_id)
            record = await result.single()

            if record is None:
                return None

            data = record["entity"]
            return Entity(
                id=data["id"],
                name=data.get("name", ""),
                type=data.get("type", "unknown"),
                properties=data.get("properties", {}),
            )

    async def get_neighbors(
        self,
        entity_id: str,
        relation_types: list[str] | None = None,
        max_depth: int = 1,
    ) -> GraphSearchResult:
        """
        엔티티의 이웃을 탐색합니다.

        가변 길이 경로 쿼리(variable length path)를 사용하여
        지정된 깊이까지 연결된 노드를 탐색합니다.

        Args:
            entity_id: 시작 엔티티 ID
            relation_types: 필터링할 관계 타입 목록 (None이면 전체)
            max_depth: 최대 탐색 깊이 (기본값: 1)

        Returns:
            GraphSearchResult: 이웃 엔티티와 관계
        """
        # 관계 타입 필터 조건 생성
        type_filter = ""
        if relation_types:
            # OR 조건으로 관계 타입 필터링
            type_conditions = " OR ".join(
                [f"r.type = '{t}'" for t in relation_types]
            )
            type_filter = f"WHERE {type_conditions}"

        # 가변 길이 경로 쿼리 (*1..{max_depth})
        query = f"""
        MATCH (start:Entity {{id: $entity_id}})
        MATCH path = (start)-[r:RELATES_TO*1..{max_depth}]-(neighbor:Entity)
        {type_filter}
        WITH neighbor, r, path
        RETURN DISTINCT
            neighbor {{.id, .name, .type, .properties}} as entity,
            [rel in relationships(path) | {{
                source_id: startNode(rel).id,
                target_id: endNode(rel).id,
                type: rel.type,
                weight: rel.weight
            }}] as relations
        """

        entities: list[Entity] = []
        relations: list[Relation] = []
        seen_entities: set[str] = set()
        seen_relations: set[str] = set()

        driver = self._get_driver()
        async with driver.session(database=self._database) as session:
            result = await session.run(query, entity_id=entity_id)
            records = await result.data()

            for record in records:
                # 엔티티 추가 (중복 제거)
                entity_data = record["entity"]
                if entity_data["id"] not in seen_entities:
                    entities.append(
                        Entity(
                            id=entity_data["id"],
                            name=entity_data.get("name", ""),
                            type=entity_data.get("type", "unknown"),
                            properties=entity_data.get("properties", {}),
                        )
                    )
                    seen_entities.add(entity_data["id"])

                # 관계 추가 (중복 제거)
                for rel_data in record.get("relations", []):
                    if rel_data.get("source_id") is None:
                        continue
                    rel_key = (
                        f"{rel_data['source_id']}-{rel_data['type']}-"
                        f"{rel_data['target_id']}"
                    )
                    if rel_key not in seen_relations:
                        relations.append(
                            Relation(
                                source_id=rel_data["source_id"],
                                target_id=rel_data["target_id"],
                                type=rel_data.get("type", "unknown"),
                                weight=rel_data.get("weight", 1.0),
                            )
                        )
                        seen_relations.add(rel_key)

        logger.debug(
            f"이웃 탐색: {entity_id} -> {len(entities)}개 엔티티, "
            f"{len(relations)}개 관계"
        )

        return GraphSearchResult(
            entities=entities,
            relations=relations,
            score=1.0 if entities else 0.0,
        )

    async def search(
        self,
        query: str,
        entity_types: list[str] | None = None,
        top_k: int = 10,
    ) -> GraphSearchResult:
        """
        그래프에서 엔티티를 검색합니다.

        엔티티 이름에 대해 CONTAINS 검색을 수행합니다.
        대소문자를 무시한 부분 문자열 매칭입니다.

        Args:
            query: 검색 쿼리 문자열
            entity_types: 필터링할 엔티티 타입 목록
            top_k: 반환할 최대 결과 수 (기본값: 10)

        Returns:
            GraphSearchResult: 검색된 엔티티와 연관 관계
        """
        # 타입 필터 조건 생성
        type_filter = ""
        if entity_types:
            type_conditions = " OR ".join(
                [f"e.type = '{t}'" for t in entity_types]
            )
            type_filter = f"AND ({type_conditions})"

        # CONTAINS를 사용한 부분 문자열 검색
        cypher_query = f"""
        MATCH (e:Entity)
        WHERE toLower(e.name) CONTAINS toLower($search_query) {type_filter}
        WITH e
        LIMIT $top_k
        OPTIONAL MATCH (e)-[r:RELATES_TO]-(related:Entity)
        RETURN
            e {{.id, .name, .type, .properties}} as entity,
            collect(DISTINCT {{
                source_id: startNode(r).id,
                target_id: endNode(r).id,
                type: r.type,
                weight: r.weight
            }}) as relations
        """

        entities: list[Entity] = []
        relations: list[Relation] = []
        seen_relations: set[str] = set()

        driver = self._get_driver()
        async with driver.session(database=self._database) as session:
            result = await session.run(cypher_query, search_query=query, top_k=top_k)
            records = await result.data()

            for record in records:
                # 엔티티 추가
                entity_data = record["entity"]
                entities.append(
                    Entity(
                        id=entity_data["id"],
                        name=entity_data.get("name", ""),
                        type=entity_data.get("type", "unknown"),
                        properties=entity_data.get("properties", {}),
                    )
                )

                # 관계 추가 (중복 제거)
                for rel_data in record.get("relations", []):
                    # 관계가 없는 경우 (OPTIONAL MATCH 결과)
                    if rel_data.get("source_id") is None:
                        continue
                    rel_key = (
                        f"{rel_data['source_id']}-{rel_data['type']}-"
                        f"{rel_data['target_id']}"
                    )
                    if rel_key not in seen_relations:
                        relations.append(
                            Relation(
                                source_id=rel_data["source_id"],
                                target_id=rel_data["target_id"],
                                type=rel_data.get("type", "unknown"),
                                weight=rel_data.get("weight", 1.0),
                            )
                        )
                        seen_relations.add(rel_key)

        # 검색 점수 계산 (간단한 휴리스틱)
        score = min(1.0, len(entities) / top_k) if top_k > 0 else 0.0

        logger.info(f"검색 완료: query='{query}' -> {len(entities)}개 엔티티")

        return GraphSearchResult(
            entities=entities,
            relations=relations,
            score=score,
        )

    async def clear(self) -> None:
        """
        그래프의 모든 데이터를 삭제합니다.

        주의: 프로덕션 환경에서는 신중하게 사용하세요.
        모든 노드와 관계가 삭제됩니다.
        """
        # DETACH DELETE로 모든 노드와 연결된 관계 삭제
        query = """
        MATCH (n)
        DETACH DELETE n
        """

        driver = self._get_driver()
        async with driver.session(database=self._database) as session:
            await session.run(query)

        logger.warning("Neo4j 그래프 전체 삭제 완료")

    def get_stats(self) -> dict[str, Any]:
        """
        그래프 통계를 반환합니다.

        동기 메서드이므로 기본 설정 정보만 반환합니다.
        상세 통계는 get_stats_async()를 사용하세요.

        Returns:
            통계 정보 딕셔너리 (provider, database, uri)
        """
        return {
            "provider": "neo4j",
            "database": self._database,
            "uri": self._config.get("uri", "unknown"),
        }

    async def get_stats_async(self) -> dict[str, Any]:
        """
        그래프 통계를 비동기로 조회합니다.

        실제 Neo4j 데이터베이스에서 노드/관계 수를 조회합니다.

        Returns:
            상세 통계 정보 (entity_count, relation_count 포함)
        """
        query = """
        MATCH (e:Entity)
        WITH count(e) as entity_count
        MATCH ()-[r:RELATES_TO]->()
        RETURN entity_count, count(r) as relation_count
        """

        driver = self._get_driver()
        async with driver.session(database=self._database) as session:
            result = await session.run(query)
            record = await result.single()

            if record:
                return {
                    "provider": "neo4j",
                    "database": self._database,
                    "uri": self._config.get("uri", "unknown"),
                    "entity_count": record["entity_count"],
                    "relation_count": record["relation_count"],
                }

        # 조회 실패 시 기본 통계 반환
        return self.get_stats()
