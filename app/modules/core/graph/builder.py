"""
지식 그래프 빌더

텍스트/문서에서 엔티티와 관계를 추출하여 그래프를 구축합니다.

생성일: 2026-01-04
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.lib.logger import get_logger

if TYPE_CHECKING:
    from .interfaces import IEntityExtractor, IGraphStore, IRelationExtractor

logger = get_logger(__name__)


class KnowledgeGraphBuilder:
    """
    지식 그래프 빌더

    엔티티 추출 → 관계 추출 → 그래프 저장 파이프라인을 실행합니다.

    사용 예시:
        >>> builder = KnowledgeGraphBuilder(
        ...     graph_store=store,
        ...     entity_extractor=entity_extractor,
        ...     relation_extractor=relation_extractor,
        ... )
        >>> result = await builder.build("텍스트")
    """

    def __init__(
        self,
        graph_store: IGraphStore,
        entity_extractor: IEntityExtractor,
        relation_extractor: IRelationExtractor,
    ) -> None:
        """
        Args:
            graph_store: 그래프 저장소
            entity_extractor: 엔티티 추출기
            relation_extractor: 관계 추출기
        """
        self._graph_store = graph_store
        self._entity_extractor = entity_extractor
        self._relation_extractor = relation_extractor

    async def build(self, text: str) -> dict[str, Any]:
        """
        단일 텍스트에서 지식 그래프 빌드

        Args:
            text: 소스 텍스트

        Returns:
            빌드 결과 (entities_count, relations_count)
        """
        # 1. 엔티티 추출
        entities = await self._entity_extractor.extract(text)
        logger.info(f"엔티티 {len(entities)}개 추출")

        # 2. 그래프에 엔티티 저장
        for entity in entities:
            await self._graph_store.add_entity(entity)

        # 3. 관계 추출
        relations = await self._relation_extractor.extract(text, entities)
        logger.info(f"관계 {len(relations)}개 추출")

        # 4. 그래프에 관계 저장
        for relation in relations:
            await self._graph_store.add_relation(relation)

        return {
            "entities_count": len(entities),
            "relations_count": len(relations),
        }

    async def build_from_documents(
        self,
        documents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        여러 문서에서 지식 그래프 빌드

        Args:
            documents: 문서 리스트 (각 문서는 content, metadata 포함)

        Returns:
            빌드 결과 (documents_processed, total_entities, total_relations)
        """
        total_entities = 0
        total_relations = 0

        for doc in documents:
            content = doc.get("content", "")
            if not content:
                continue

            result = await self.build(content)
            total_entities += result["entities_count"]
            total_relations += result["relations_count"]

        return {
            "documents_processed": len(documents),
            "total_entities": total_entities,
            "total_relations": total_relations,
        }
