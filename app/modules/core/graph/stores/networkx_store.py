"""
NetworkX 기반 인메모리 그래프 저장소
경량 구현으로 PoC 및 소규모 데이터에 적합

특징:
- 인메모리 저장 (서버 재시작 시 초기화)
- 단일 인스턴스 환경에 적합
- 빠른 그래프 연산 (NetworkX 최적화)
"""
import logging
import math
from collections import deque
from collections.abc import Iterator
from typing import Any, Literal, overload

from ..interfaces import IGraphStore
from ..models import Entity, GraphSearchResult, Relation

logger = logging.getLogger(__name__)


class _EdgeView:
    """Small edge-data view compatible with the subset this store needs."""

    def __init__(self, successors: dict[str, dict[str, dict[str, Any]]]) -> None:
        self._successors = successors

    def __getitem__(self, edge: tuple[str, str]) -> dict[str, Any]:
        source_id, target_id = edge
        return self._successors[source_id][target_id]


class _SimpleDiGraph:
    """Minimal directed graph used to avoid importing NetworkX at test collection time."""

    def __init__(self) -> None:
        self._nodes: dict[str, dict[str, Any]] = {}
        self._successors: dict[str, dict[str, dict[str, Any]]] = {}
        self._predecessors: dict[str, dict[str, dict[str, Any]]] = {}
        self.edges = _EdgeView(self._successors)

    def __contains__(self, node_id: str) -> bool:
        return node_id in self._nodes

    def add_node(self, node_id: str, **attributes: Any) -> None:
        self._nodes.setdefault(node_id, {}).update(attributes)
        self._successors.setdefault(node_id, {})
        self._predecessors.setdefault(node_id, {})

    def add_edge(self, source_id: str, target_id: str, **attributes: Any) -> None:
        if source_id not in self._nodes:
            self.add_node(source_id)
        if target_id not in self._nodes:
            self.add_node(target_id)

        edge_data = dict(attributes)
        self._successors[source_id][target_id] = edge_data
        self._predecessors[target_id][source_id] = edge_data

    def successors(self, node_id: str) -> Iterator[str]:
        return iter(self._successors.get(node_id, {}))

    def predecessors(self, node_id: str) -> Iterator[str]:
        return iter(self._predecessors.get(node_id, {}))

    @overload
    def nodes(self, data: Literal[False] = False) -> Iterator[str]: ...

    @overload
    def nodes(self, data: Literal[True]) -> Iterator[tuple[str, dict[str, Any]]]: ...

    def nodes(self, data: bool = False) -> Iterator[str] | Iterator[tuple[str, dict[str, Any]]]:
        if data:
            return iter(self._nodes.items())
        return iter(self._nodes.keys())

    def clear(self) -> None:
        self._nodes.clear()
        self._successors.clear()
        self._predecessors.clear()

    def number_of_nodes(self) -> int:
        return len(self._nodes)

    def number_of_edges(self) -> int:
        return sum(len(targets) for targets in self._successors.values())


def _cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    if len(vector_a) != len(vector_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vector_a, vector_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in vector_a))
    norm_b = math.sqrt(sum(b * b for b in vector_b))

    return dot_product / (norm_a * norm_b) if norm_a > 0 and norm_b > 0 else 0.0


class NetworkXGraphStore(IGraphStore):
    """
    NetworkX 기반 그래프 저장소

    어떤 도메인에도 적용 가능한 범용 그래프 저장소입니다.
    엔티티(노드)와 관계(엣지)를 저장하고 탐색합니다.
    v3.3.0: 벡터 검색 기능 통합으로 오타 및 의미적 유사도 검색 지원.
    """

    def __init__(self) -> None:
        """그래프 초기화"""
        self._graph = _SimpleDiGraph()  # 방향 그래프
        self._entities: dict[str, Entity] = {}
        self._embedder: Any = None  # 임베딩 모델 (선택적)

    def set_embedder(self, embedder: Any) -> None:
        """
        임베딩 모델 설정

        Args:
            embedder: 임베딩 기능을 가진 객체 (async embed_query, embed_documents 지원)
        """
        self._embedder = embedder

    async def add_entity(self, entity: Entity) -> None:
        """
        엔티티 추가 또는 업데이트

        엔티티의 이름과 속성을 기반으로 임베딩을 생성하여 노드에 저장합니다.
        """
        self._entities[entity.id] = entity

        # 임베딩 대상 텍스트 구성 (이름 + 설명)
        description = entity.properties.get("description", "")
        text_to_embed = f"{entity.name} {description}".strip()

        embedding = None
        if self._embedder and text_to_embed:
            try:
                embedding = await self._embedder.embed_query(text_to_embed)
            except Exception as e:
                logger.warning(f"Failed to create embedding for entity {entity.id}: {e}")

        self._graph.add_node(
            entity.id,
            name=entity.name,
            type=entity.type,
            properties=entity.properties,
            embedding=embedding,  # 벡터 저장
        )

    async def add_relation(self, relation: Relation) -> None:
        """관계 추가 (없는 엔티티는 자동 생성)"""
        # 엔티티가 없으면 placeholder 생성
        if relation.source_id not in self._entities:
            placeholder = Entity(
                id=relation.source_id,
                name=relation.source_id,
                type="unknown",
            )
            await self.add_entity(placeholder)

        if relation.target_id not in self._entities:
            placeholder = Entity(
                id=relation.target_id,
                name=relation.target_id,
                type="unknown",
            )
            await self.add_entity(placeholder)

        # 엣지 추가
        self._graph.add_edge(
            relation.source_id,
            relation.target_id,
            type=relation.type,
            weight=relation.weight,
            properties=relation.properties,
        )

    async def get_entity(self, entity_id: str) -> Entity | None:
        """엔티티 조회"""
        return self._entities.get(entity_id)

    async def get_neighbors(
        self,
        entity_id: str,
        relation_types: list[str] | None = None,
        max_depth: int = 1,
    ) -> GraphSearchResult:
        """BFS 기반 이웃 탐색"""
        if entity_id not in self._graph:
            return GraphSearchResult(entities=[], relations=[], score=0.0)

        visited_entities: set[str] = set()
        found_entities: list[Entity] = []
        found_relations: list[Relation] = []

        # BFS 탐색
        queue: deque[tuple[str, int]] = deque([(entity_id, 0)])
        visited_entities.add(entity_id)

        while queue:
            current_id, depth = queue.popleft()

            if depth >= max_depth:
                continue

            # 나가는 엣지 탐색
            for neighbor_id in self._graph.successors(current_id):
                edge_data = self._graph.edges[current_id, neighbor_id]
                edge_type = edge_data.get("type", "unknown")

                # 관계 타입 필터링
                if relation_types and edge_type not in relation_types:
                    continue

                # 관계 추가
                relation = Relation(
                    source_id=current_id,
                    target_id=neighbor_id,
                    type=edge_type,
                    weight=edge_data.get("weight", 1.0),
                    properties=edge_data.get("properties", {}),
                )
                found_relations.append(relation)

                # 방문하지 않은 이웃 추가
                if neighbor_id not in visited_entities:
                    visited_entities.add(neighbor_id)
                    if neighbor_id in self._entities:
                        found_entities.append(self._entities[neighbor_id])
                    queue.append((neighbor_id, depth + 1))

            # 들어오는 엣지도 탐색 (양방향)
            for neighbor_id in self._graph.predecessors(current_id):
                edge_data = self._graph.edges[neighbor_id, current_id]
                edge_type = edge_data.get("type", "unknown")

                if relation_types and edge_type not in relation_types:
                    continue

                relation = Relation(
                    source_id=neighbor_id,
                    target_id=current_id,
                    type=edge_type,
                    weight=edge_data.get("weight", 1.0),
                    properties=edge_data.get("properties", {}),
                )
                found_relations.append(relation)

                if neighbor_id not in visited_entities:
                    visited_entities.add(neighbor_id)
                    if neighbor_id in self._entities:
                        found_entities.append(self._entities[neighbor_id])
                    queue.append((neighbor_id, depth + 1))

        return GraphSearchResult(
            entities=found_entities,
            relations=found_relations,
            score=1.0 if found_entities else 0.0,
        )

    async def search(
        self,
        query: str,
        entity_types: list[str] | None = None,
        top_k: int = 10,
    ) -> GraphSearchResult:
        """
        그래프 검색 (벡터 유사도 + 이름 매칭)

        1. 임베더가 있는 경우: 쿼리 임베딩 후 모든 노드와 코사인 유사도 검색
        2. 임베더가 없는 경우: 단순 이름 문자열 매칭 (하위 호환성)

        Args:
            query: 검색 쿼리
            entity_types: 필터링할 엔티티 유형
            top_k: 최대 결과 수
        """
        if not self._entities:
            return GraphSearchResult(entities=[], relations=[], score=0.0)

        # 1. 벡터 검색 시도 (임베더가 설정된 경우)
        if self._embedder:
            try:
                query_vec = await self._embedder.embed_query(query)

                scored_entities: list[tuple[Entity, float]] = []
                for node_id, node_data in self._graph.nodes(data=True):
                    # 타입 필터링
                    if entity_types and node_data.get("type") not in entity_types:
                        continue

                    node_vec = node_data.get("embedding")
                    if node_vec is None:
                        continue

                    # 코사인 유사도 계산
                    similarity = _cosine_similarity(query_vec, node_vec)

                    if similarity > 0:
                        entity = self._entities.get(node_id)
                        if entity:
                            scored_entities.append((entity, float(similarity)))

                # 점수 높은 순으로 정렬
                scored_entities.sort(key=lambda x: x[1], reverse=True)

                matched_entities = [e for e, s in scored_entities[:top_k]]
                best_score = scored_entities[0][1] if scored_entities else 0.0

                if matched_entities:
                    return GraphSearchResult(
                        entities=matched_entities,
                        relations=[],
                        score=best_score,
                    )
            except Exception as e:
                logger.warning(f"Vector search failed, falling back to string match: {e}")

        # 2. 이름 기반 검색 (Fallback)
        matched_entities = []
        query_lower = query.lower()

        for entity in self._entities.values():
            if entity_types and entity.type not in entity_types:
                continue

            if query_lower in entity.name.lower():
                matched_entities.append(entity)
                if len(matched_entities) >= top_k:
                    break

        return GraphSearchResult(
            entities=matched_entities,
            relations=[],
            score=1.0 if matched_entities else 0.0,
        )

    async def clear(self) -> None:
        """그래프 전체 삭제"""
        self._graph.clear()
        self._entities.clear()

    def get_stats(self) -> dict[str, Any]:
        """그래프 통계 반환"""
        return {
            "node_count": self._graph.number_of_nodes(),
            "edge_count": self._graph.number_of_edges(),
            "entity_types": list({e.type for e in self._entities.values()}),
        }
