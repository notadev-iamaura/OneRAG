# app/modules/core/tools/factory.py
"""
ToolFactory - 설정 기반 도구 팩토리

EmbedderFactory, RerankerFactory와 동일한 패턴.
YAML 설정에 따라 도구를 동적으로 등록/비활성화.

사용 예시:
    from app.modules.core.tools import ToolFactory, ToolServer

    # 설정 기반 도구 서버 생성
    server = ToolFactory.create(config)

    # 지원 도구 조회
    ToolFactory.get_supported_tools()
    ToolFactory.list_tools_by_category("vector")

하위 호환성:
    MCPToolFactory는 ToolFactory의 alias입니다.
"""
from typing import TYPE_CHECKING, Any

from ....lib.logger import get_logger
from .interfaces import ToolConfig, ToolServerConfig

if TYPE_CHECKING:
    from .server import ToolServer

logger = get_logger(__name__)


# ========================================
# 지원 도구 레지스트리
# ========================================
# 새 도구 추가 시 여기에 등록
# 패턴: RerankerFactory.SUPPORTED_RERANKERS와 동일

SUPPORTED_TOOLS: dict[str, dict[str, Any]] = {
    # 벡터 검색 도구
    "search_weaviate": {
        "category": "vector",
        "description": "Weaviate 벡터 DB에서 정보를 하이브리드 검색합니다",
        "module": "app.modules.core.tools.vector_search",
        "function": "search_weaviate",
        "default_config": {
            "timeout": 15,
            "default_top_k": 10,
            "alpha": 0.6,
        },
    },
    "get_document_by_id": {
        "category": "vector",
        "description": "문서 ID로 벡터 DB에서 직접 조회합니다",
        "module": "app.modules.core.tools.vector_search",
        "function": "get_document_by_id",
        "default_config": {
            "timeout": 5,
        },
    },
    # 그래프 검색 도구
    "search_graph": {
        "category": "graph",
        "description": "지식 그래프에서 엔티티와 관계를 검색합니다",
        "module": "app.modules.core.tools.graph_search",
        "function": "search_graph",
        "default_config": {
            "timeout": 15,
            "default_top_k": 10,
        },
    },
    "get_neighbors": {
        "category": "graph",
        "description": "엔티티의 이웃 엔티티와 관계를 조회합니다",
        "module": "app.modules.core.tools.graph_search",
        "function": "get_neighbors",
        "default_config": {
            "timeout": 10,
            "default_max_depth": 1,
        },
    },
    # 웹 검색 도구
    "web_search": {
        "category": "web",
        "description": "인터넷에서 실시간 정보를 검색합니다 (Fallback: Tavily -> Brave -> DuckDuckGo)",
        "module": "app.modules.core.tools.web_search",
        "function": "web_search",
        "default_config": {
            "timeout": 15,
            "max_results": 5,
        },
    },
    # Notion 검색 도구 (레거시 호환)
    "search_notion": {
        "category": "notion",
        "description": "메타데이터 소스(Notion 등)에서 정보를 검색합니다",
        "module": "app.modules.core.tools.notion_search",
        "function": "search_notion",
        "default_config": {
            "timeout": 10,
        },
    },
    # SQL 검색 도구 (레거시 호환)
    "query_sql": {
        "category": "sql",
        "description": "자연어 질문을 SQL로 변환하여 메타데이터 DB를 검색합니다",
        "module": "app.modules.core.tools.sql_search",
        "function": "query_sql",
        "default_config": {
            "timeout": 20,
            "max_rows": 100,
        },
    },
    "get_table_schema": {
        "category": "sql",
        "description": "테이블 스키마(컬럼 정보)를 조회합니다",
        "module": "app.modules.core.tools.sql_search",
        "function": "get_table_schema",
        "default_config": {
            "timeout": 5,
        },
    },
}


class ToolFactory:
    """
    도구 팩토리

    설정 딕셔너리를 기반으로 ToolServer를 생성하고
    활성화된 도구들을 등록합니다.

    RerankerFactory와 동일한 패턴:
    - SUPPORTED_TOOLS 레지스트리
    - create() 정적 메서드
    - get_supported_tools(), get_tool_info() 조회 메서드
    """

    @staticmethod
    def create(config: dict[str, Any]) -> "ToolServer":
        """
        설정 기반 도구 서버 생성

        Args:
            config: 전체 설정 딕셔너리 (mcp 또는 tools 섹션 포함)

        Returns:
            ToolServer: ToolServer 인스턴스

        Raises:
            ValueError: 도구 기능이 비활성화된 경우
        """
        # tools 섹션 우선, 없으면 mcp 섹션 사용 (하위 호환성)
        tools_config = config.get("tools", config.get("mcp", {}))

        if not tools_config.get("enabled", False):
            raise ValueError("도구 기능이 비활성화되어 있습니다 (tools.enabled=false)")

        # 서버 설정 생성
        server_config = ToolServerConfig(
            enabled=True,
            server_name=tools_config.get("server_name", "rag-tools"),
            default_timeout=float(tools_config.get("default_timeout", 30.0)),
            max_concurrent_tools=int(tools_config.get("max_concurrent_tools", 3)),
        )

        # 활성화된 도구 수집
        yaml_tools_config = tools_config.get("tools", {})
        enabled_tools: dict[str, ToolConfig] = {}

        for tool_name, tool_info in SUPPORTED_TOOLS.items():
            tool_yaml = yaml_tools_config.get(tool_name, {})

            # YAML에서 enabled 확인 (기본값: True)
            if not tool_yaml.get("enabled", True):
                logger.debug(f"도구 비활성화: {tool_name}")
                continue

            # 도구 설정 병합 (YAML > 기본값)
            default_config = tool_info.get("default_config", {})
            merged_params = {**default_config, **tool_yaml.get("parameters", {})}

            tool_config = ToolConfig(
                name=tool_name,
                description=tool_yaml.get("description", tool_info["description"]),
                enabled=True,
                timeout=float(tool_yaml.get("timeout", default_config.get("timeout", 30.0))),
                parameters=merged_params,
            )

            enabled_tools[tool_name] = tool_config
            logger.debug(f"도구 활성화: {tool_name}")

        server_config.tools = enabled_tools

        logger.info(
            f"🔧 ToolFactory: {len(enabled_tools)}개 도구 활성화 "
            f"({list(enabled_tools.keys())})"
        )

        # ToolServer 인스턴스 생성
        from .server import ToolServer

        return ToolServer(config=server_config, global_config=config)

    @staticmethod
    def get_supported_tools() -> list[str]:
        """지원하는 모든 도구 이름 반환"""
        return list(SUPPORTED_TOOLS.keys())

    @staticmethod
    def get_tool_info(tool_name: str) -> dict[str, Any] | None:
        """특정 도구의 상세 정보 반환"""
        return SUPPORTED_TOOLS.get(tool_name)

    @staticmethod
    def list_tools_by_category(category: str) -> list[str]:
        """
        카테고리별 도구 목록 반환

        Args:
            category: 도구 카테고리 (vector, graph, web, notion, sql)

        Returns:
            해당 카테고리의 도구 이름 리스트
        """
        return [
            name
            for name, info in SUPPORTED_TOOLS.items()
            if info.get("category") == category
        ]

    @staticmethod
    def register_tool(
        tool_name: str,
        category: str,
        description: str,
        module: str,
        function: str,
        default_config: dict[str, Any] | None = None,
    ) -> None:
        """
        새 도구 동적 등록 (플러그인 방식)

        Args:
            tool_name: 도구 이름
            category: 카테고리
            description: 설명
            module: 모듈 경로
            function: 함수 이름
            default_config: 기본 설정
        """
        SUPPORTED_TOOLS[tool_name] = {
            "category": category,
            "description": description,
            "module": module,
            "function": function,
            "default_config": default_config or {},
        }
        logger.info(f"📦 도구 등록: {tool_name} ({category})")


# ========================================
# 하위 호환성 alias
# ========================================
MCPToolFactory = ToolFactory
