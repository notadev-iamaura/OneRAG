"""
GraphRAG 데이터 모델
엔티티, 관계, 검색 결과 정의

범용적인 지식 그래프 노드/엣지 모델로,
어떤 도메인에도 적용 가능합니다.
"""

from pydantic import BaseModel, Field


class Entity(BaseModel):
    """
    지식 그래프의 엔티티 (노드)

    Attributes:
        id: 고유 식별자
        name: 엔티티 이름 (예: "A사", "김 담당자")
        type: 엔티티 유형 (예: "company", "person", "location")
        properties: 추가 속성 딕셔너리
    """

    id: str
    name: str
    type: str
    properties: dict[str, str | int | float | bool] = Field(default_factory=dict)


class Relation(BaseModel):
    """
    지식 그래프의 관계 (엣지)

    Attributes:
        source_id: 출발 엔티티 ID
        target_id: 도착 엔티티 ID
        type: 관계 유형 (예: "partnership", "supply", "manages")
        weight: 관계 강도 (0.0 ~ 1.0)
        properties: 추가 속성 딕셔너리
    """

    source_id: str
    target_id: str
    type: str
    weight: float = 1.0
    properties: dict[str, str | int | float | bool] = Field(default_factory=dict)


class GraphSearchResult(BaseModel):
    """
    그래프 검색 결과

    Attributes:
        entities: 검색된 엔티티 목록
        relations: 검색된 관계 목록
        score: 검색 점수 (0.0 ~ 1.0)
    """

    entities: list[Entity]
    relations: list[Relation]
    score: float

    @property
    def is_empty(self) -> bool:
        """검색 결과가 비어있는지 확인"""
        return len(self.entities) == 0 and len(self.relations) == 0
