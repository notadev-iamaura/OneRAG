# app/modules/core/tools/graph_search.py
"""
그래프 검색 도구

그래프 검색, 이웃 조회 등의 도구를 제공합니다.
Agent가 사용할 수 있습니다.

도구 목록:
- search_graph: 그래프에서 엔티티 검색
- get_neighbors: 엔티티의 이웃 조회
"""
from __future__ import annotations

from typing import Any

from ....lib.logger import get_logger

logger = get_logger(__name__)


async def search_graph(
    arguments: dict[str, Any],
    global_config: dict[str, Any],
) -> dict[str, Any]:
    """
    그래프에서 엔티티를 검색합니다.

    지식 그래프에서 키워드 기반 검색을 수행하여
    관련 엔티티와 관계를 반환합니다.

    Args:
        arguments: 도구 인자
            - query (str): 검색 쿼리 (필수)
            - entity_types (list[str]): 필터링할 엔티티 타입 (선택)
            - top_k (int): 반환할 최대 결과 수 (기본값: 10)
        global_config: 전역 설정 (graph_store 접근용)

    Returns:
        dict: 검색 결과
            - success (bool): 성공 여부
            - entities (list): 엔티티 목록
            - relations (list): 관계 목록
            - score (float): 검색 점수
            - error (str, optional): 실패 시 에러 메시지

    Raises:
        ValueError: 쿼리가 비어있거나 graph_store가 설정되지 않은 경우
    """
    query = arguments.get("query", "")

    # 빈 쿼리 검증
    if not query or not query.strip():
        raise ValueError("query는 필수입니다")

    # GraphStore 확인
    graph_store = global_config.get("graph_store")
    if graph_store is None:
        raise ValueError("graph_store가 설정되지 않았습니다")

    # 설정에서 파라미터 가져오기
    mcp_config = global_config.get("mcp", {})
    tool_config = mcp_config.get("tools", {}).get("search_graph", {})
    params = tool_config.get("parameters", {})

    default_top_k = params.get("default_top_k", 10)

    entity_types = arguments.get("entity_types")
    top_k = arguments.get("top_k", default_top_k)

    logger.info(
        f"🔍 search_graph: query='{query}', entity_types={entity_types}, top_k={top_k}"
    )

    try:
        result = await graph_store.search(
            query=query,
            entity_types=entity_types,
            top_k=top_k,
        )

        entities_list = [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "properties": e.properties,
            }
            for e in result.entities
        ]

        relations_list = [
            {
                "source_id": r.source_id,
                "target_id": r.target_id,
                "type": r.type,
                "weight": r.weight,
            }
            for r in result.relations
        ]

        response = {
            "success": True,
            "entities": entities_list,
            "relations": relations_list,
            "score": result.score,
        }

        logger.info(
            f"✅ search_graph: {len(entities_list)}개 엔티티, "
            f"{len(relations_list)}개 관계"
        )

        return response

    except Exception as e:
        logger.error(f"❌ search_graph 실패: {e}")
        raise


async def get_neighbors(
    arguments: dict[str, Any],
    global_config: dict[str, Any],
) -> dict[str, Any]:
    """
    엔티티의 이웃을 조회합니다.

    지정된 엔티티에서 시작하여 연결된 이웃 엔티티와
    관계를 탐색합니다.

    Args:
        arguments: 도구 인자
            - entity_id (str): 시작 엔티티 ID (필수)
            - relation_types (list[str]): 필터링할 관계 타입 (선택)
            - max_depth (int): 최대 탐색 깊이 (기본값: 1)
        global_config: 전역 설정 (graph_store 접근용)

    Returns:
        dict: 이웃 정보
            - success (bool): 성공 여부
            - entities (list): 이웃 엔티티 목록
            - relations (list): 관계 목록
            - error (str, optional): 실패 시 에러 메시지

    Raises:
        ValueError: entity_id가 없거나 graph_store가 설정되지 않은 경우
    """
    entity_id = arguments.get("entity_id", "")

    # 필수값 검증
    if not entity_id:
        raise ValueError("entity_id는 필수입니다")

    # GraphStore 확인
    graph_store = global_config.get("graph_store")
    if graph_store is None:
        raise ValueError("graph_store가 설정되지 않았습니다")

    # 설정에서 파라미터 가져오기
    mcp_config = global_config.get("mcp", {})
    tool_config = mcp_config.get("tools", {}).get("get_neighbors", {})
    params = tool_config.get("parameters", {})

    default_max_depth = params.get("default_max_depth", 1)

    relation_types = arguments.get("relation_types")
    max_depth = arguments.get("max_depth", default_max_depth)

    logger.info(
        f"📄 get_neighbors: entity_id='{entity_id}', "
        f"relation_types={relation_types}, max_depth={max_depth}"
    )

    try:
        result = await graph_store.get_neighbors(
            entity_id=entity_id,
            relation_types=relation_types,
            max_depth=max_depth,
        )

        entities_list = [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "properties": e.properties,
            }
            for e in result.entities
        ]

        relations_list = [
            {
                "source_id": r.source_id,
                "target_id": r.target_id,
                "type": r.type,
                "weight": r.weight,
            }
            for r in result.relations
        ]

        response = {
            "success": True,
            "entities": entities_list,
            "relations": relations_list,
        }

        logger.info(f"✅ get_neighbors: {len(entities_list)}개 이웃 엔티티")

        return response

    except Exception as e:
        logger.error(f"❌ get_neighbors 실패: {e}")
        raise
