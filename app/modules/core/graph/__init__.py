"""
GraphRAG 모듈
지식 그래프 기반 검색 시스템

사용 예시:
    from app.modules.core.graph import GraphRAGFactory, Entity, Relation

    # 설정 기반 그래프 저장소 생성
    store = GraphRAGFactory.create(config)

    # 엔티티/관계 추가
    entity = Entity(id="e1", name="A사", type="company")
    await store.add_entity(entity)

    # LLM 기반 추출기 사용
    from app.modules.core.graph import LLMEntityExtractor, LLMRelationExtractor
    extractor = LLMEntityExtractor(llm_client=llm_client)
    entities = await extractor.extract("A사는 서울에 있습니다.")

    # 지식 그래프 빌더
    from app.modules.core.graph import KnowledgeGraphBuilder
    builder = KnowledgeGraphBuilder(store, entity_extractor, relation_extractor)
    result = await builder.build("텍스트")
"""
from .builder import KnowledgeGraphBuilder
from .extractors import LLMEntityExtractor, LLMRelationExtractor
from .factory import GraphRAGFactory
from .interfaces import IEntityExtractor, IGraphStore, IRelationExtractor
from .models import Entity, GraphSearchResult, Relation
from .stores import NetworkXGraphStore

__all__ = [
    # 데이터 모델
    "Entity",
    "Relation",
    "GraphSearchResult",
    # 인터페이스
    "IGraphStore",
    "IEntityExtractor",
    "IRelationExtractor",
    # 구현체
    "NetworkXGraphStore",
    # 추출기 (LLM 기반)
    "LLMEntityExtractor",
    "LLMRelationExtractor",
    # 빌더
    "KnowledgeGraphBuilder",
    # 팩토리
    "GraphRAGFactory",
]
