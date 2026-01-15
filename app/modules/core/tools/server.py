# app/modules/core/tools/server.py
"""
ToolServer - 도구 서버 래퍼 클래스

기존 팩토리 패턴과 통합하면서 FastMCP 기능을 제공.
DI Container에서 Singleton으로 관리.

사용 예시:
    # ToolFactory를 통해 생성 (권장)
    server = ToolFactory.create(config)

    # 도구 실행
    result = await server.execute_tool("search_weaviate", {"query": "검색어"})

하위 호환성:
    MCPServer는 ToolServer의 alias입니다.
"""
import asyncio
import time
from typing import Any

from ....lib.logger import get_logger
from .interfaces import ToolConfig, ToolResult, ToolServerConfig

logger = get_logger(__name__)


class ToolServer:
    """
    도구 서버 래퍼 클래스

    FastMCP를 내부적으로 사용하면서 기존 아키텍처와 호환되는
    인터페이스를 제공합니다.

    주요 기능:
    - 설정 기반 도구 활성화/비활성화
    - OpenAI Function Calling 형식 스키마 제공
    - 도구 실행 및 결과 추적
    """

    def __init__(
        self,
        config: ToolServerConfig,
        global_config: dict[str, Any],
    ):
        """
        ToolServer 초기화

        Args:
            config: 도구 서버 설정
            global_config: 전체 앱 설정 (retriever, generation 등 접근용)
        """
        self._config = config
        self._global_config = global_config
        self._fastmcp = None  # Lazy initialization
        self._tool_functions: dict[str, Any] = {}
        self._initialized = False

        # 통계
        self._stats: dict[str, Any] = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "calls_by_tool": {},
        }

        logger.info(f"ToolServer 생성: {config.server_name}")

    @property
    def server_name(self) -> str:
        """서버 이름"""
        return self._config.server_name

    @property
    def is_enabled(self) -> bool:
        """서버 활성화 여부"""
        return self._config.enabled

    def get_enabled_tools(self) -> list[str]:
        """활성화된 도구 이름 목록"""
        return [
            name
            for name, config in self._config.tools.items()
            if config.enabled
        ]

    def get_tool_config(self, tool_name: str) -> ToolConfig | None:
        """특정 도구 설정 조회"""
        return self._config.tools.get(tool_name)

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """
        OpenAI Function Calling 형식의 도구 스키마 반환

        LLM에 전달하여 도구 선택에 사용
        """
        schemas = []

        for tool_name, tool_config in self._config.tools.items():
            if not tool_config.enabled:
                continue

            schema = {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_config.description,
                    "parameters": {
                        "type": "object",
                        "properties": self._build_parameter_schema(tool_config),
                        "required": self._get_required_params(tool_name),
                    },
                },
            }
            schemas.append(schema)

        return schemas

    def _build_parameter_schema(self, tool_config: ToolConfig) -> dict[str, Any]:
        """도구 파라미터 JSON Schema 생성"""
        # 기본 파라미터 스키마 (도구별로 다름)
        base_schemas: dict[str, dict[str, Any]] = {
            "search_weaviate": {
                "query": {"type": "string", "description": "검색 쿼리"},
                "top_k": {"type": "integer", "description": "반환할 결과 수", "default": 10},
            },
            "get_document_by_id": {
                "document_id": {"type": "string", "description": "문서 UUID"},
            },
            "search_notion": {
                "query": {"type": "string", "description": "검색 쿼리"},
                "category": {"type": "string", "description": "업체 카테고리 필터"},
            },
            "query_sql": {
                "question": {"type": "string", "description": "자연어 질문"},
            },
            "get_table_schema": {
                "table_name": {"type": "string", "description": "테이블 이름"},
            },
            "search_graph": {
                "query": {"type": "string", "description": "검색 쿼리"},
                "entity_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "필터링할 엔티티 타입",
                },
                "top_k": {
                    "type": "integer",
                    "description": "반환할 최대 결과 수",
                    "default": 10,
                },
            },
            "get_neighbors": {
                "entity_id": {"type": "string", "description": "시작 엔티티 ID"},
                "relation_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "필터링할 관계 타입",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "최대 탐색 깊이",
                    "default": 1,
                },
            },
            "web_search": {
                "query": {"type": "string", "description": "검색 쿼리"},
                "max_results": {
                    "type": "integer",
                    "description": "반환할 최대 결과 수",
                    "default": 5,
                },
            },
        }

        return base_schemas.get(tool_config.name, {})

    def _get_required_params(self, tool_name: str) -> list[str]:
        """도구별 필수 파라미터 목록"""
        required_params: dict[str, list[str]] = {
            "search_weaviate": ["query"],
            "get_document_by_id": ["document_id"],
            "search_notion": ["query"],
            "query_sql": ["question"],
            "get_table_schema": ["table_name"],
            "search_graph": ["query"],
            "get_neighbors": ["entity_id"],
            "web_search": ["query"],
        }

        return required_params.get(tool_name, [])

    async def initialize(self) -> None:
        """
        서버 초기화 (도구 함수 등록)

        DI Container의 initialize_async_resources()에서 호출
        """
        if self._initialized:
            return

        logger.info(f"ToolServer 초기화 시작: {self.server_name}")

        # FastMCP 인스턴스 생성 (lazy) - 선택적
        try:
            from fastmcp import FastMCP

            self._fastmcp = FastMCP(
                name=self.server_name,
                description="RAG Chatbot Tool Server",
            )
            logger.debug("FastMCP 인스턴스 생성됨")
        except ImportError:
            logger.warning("FastMCP 미설치, 기본 모드로 동작")
            self._fastmcp = None

        # 도구 함수 로딩
        await self._load_tool_functions()

        self._initialized = True
        logger.info(f"✅ ToolServer 초기화 완료: {len(self._tool_functions)}개 도구")

    async def _load_tool_functions(self) -> None:
        """도구 함수 동적 로딩"""
        from .factory import SUPPORTED_TOOLS

        for tool_name in self.get_enabled_tools():
            tool_info = SUPPORTED_TOOLS.get(tool_name)
            if not tool_info:
                continue

            try:
                # 모듈 동적 임포트
                module_path = tool_info["module"]
                function_name = tool_info["function"]

                # 모듈이 존재하는지 확인 후 로딩
                import importlib

                try:
                    module = importlib.import_module(module_path)
                    func = getattr(module, function_name, None)

                    if func:
                        self._tool_functions[tool_name] = func
                        logger.debug(f"도구 함수 로딩: {tool_name}")
                except ModuleNotFoundError:
                    logger.debug(f"도구 모듈 미구현 (스킵): {module_path}")

            except Exception as e:
                logger.warning(f"도구 함수 로딩 실패: {tool_name} - {e}")

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """
        도구 실행

        Args:
            tool_name: 도구 이름
            arguments: 도구 인자

        Returns:
            ToolResult: 실행 결과
        """
        start_time = time.time()
        self._stats["total_calls"] += 1
        self._stats["calls_by_tool"][tool_name] = (
            self._stats["calls_by_tool"].get(tool_name, 0) + 1
        )

        # 도구 활성화 확인
        tool_config = self.get_tool_config(tool_name)
        if not tool_config or not tool_config.enabled:
            self._stats["failed_calls"] += 1
            return ToolResult(
                success=False,
                data=None,
                error=f"비활성화된 도구: {tool_name}",
                tool_name=tool_name,
            )

        # 도구 함수 확인
        func = self._tool_functions.get(tool_name)
        if not func:
            self._stats["failed_calls"] += 1
            return ToolResult(
                success=False,
                data=None,
                error=f"도구 함수 미등록: {tool_name}",
                tool_name=tool_name,
            )

        try:
            # 타임아웃 적용
            timeout = tool_config.timeout

            result = await asyncio.wait_for(
                func(arguments, self._global_config),
                timeout=timeout,
            )

            execution_time = time.time() - start_time
            self._stats["successful_calls"] += 1

            logger.info(f"✅ 도구 실행 성공: {tool_name} ({execution_time:.2f}s)")

            return ToolResult(
                success=True,
                data=result,
                tool_name=tool_name,
                execution_time=execution_time,
            )

        except TimeoutError:
            self._stats["failed_calls"] += 1
            return ToolResult(
                success=False,
                data=None,
                error=f"타임아웃: {tool_config.timeout}초 초과",
                tool_name=tool_name,
                execution_time=time.time() - start_time,
            )

        except Exception as e:
            self._stats["failed_calls"] += 1
            logger.error(f"❌ 도구 실행 실패: {tool_name} - {e}")

            return ToolResult(
                success=False,
                data=None,
                error=str(e),
                tool_name=tool_name,
                execution_time=time.time() - start_time,
            )

    def get_stats(self) -> dict[str, Any]:
        """서버 통계 반환"""
        return {
            **self._stats,
            "enabled_tools": self.get_enabled_tools(),
            "initialized": self._initialized,
        }

    async def shutdown(self) -> None:
        """서버 종료"""
        self._tool_functions.clear()
        self._initialized = False
        logger.info(f"ToolServer 종료: {self.server_name}")


# ========================================
# 하위 호환성 alias
# ========================================
MCPServer = ToolServer
