"""
Tool Use 모듈

LLM Tool Use (Function Calling) 기능 구현.
MCP(Model Context Protocol) 관련 인터페이스도 포함합니다.

하위 호환성을 위해 MCP* alias를 제공합니다.

사용 예시:
    from app.modules.core.tools import ToolResult, ToolConfig, ToolServer, ToolFactory

    # 하위 호환성 alias
    from app.modules.core.tools import MCPToolResult  # ToolResult와 동일
    from app.modules.core.tools import MCPServer  # ToolServer와 동일
    from app.modules.core.tools import MCPToolFactory  # ToolFactory와 동일
"""
from .external_api_caller import APICallResult, BackoffStrategy, ExternalAPICaller, get_api_caller
from .factory import SUPPORTED_TOOLS, MCPToolFactory, ToolFactory
from .graph_search import get_neighbors, search_graph
from .interfaces import (
    # 하위 호환성 alias (deprecated, 기존 코드 호환용)
    MCPServerConfig,
    MCPToolConfig,
    MCPToolFunction,
    MCPToolResult,
    # 새로운 이름 (권장)
    ToolConfig,
    ToolFunction,
    ToolResult,
    ToolServerConfig,
)
from .server import MCPServer, ToolServer
from .tool_executor import ToolExecutionResult, ToolExecutor
from .tool_loader import ToolDefinition, ToolLoader, get_tool_loader
from .vector_search import get_document_by_id, search_weaviate
from .web_search import (
    BraveProvider,
    DuckDuckGoProvider,
    TavilyProvider,
    WebSearchProvider,
    WebSearchResponse,
    WebSearchResult,
    WebSearchService,
    web_search,
)

__all__ = [
    # Tool Server & Factory (권장)
    "ToolServer",
    "ToolFactory",
    "SUPPORTED_TOOLS",
    # 하위 호환성 alias (MCP*)
    "MCPServer",
    "MCPToolFactory",
    # Tool Loader
    "ToolDefinition",
    "ToolLoader",
    "get_tool_loader",
    # External API Caller
    "APICallResult",
    "BackoffStrategy",
    "ExternalAPICaller",
    "get_api_caller",
    # Tool Executor
    "ToolExecutionResult",
    "ToolExecutor",
    # 새로운 인터페이스 (권장)
    "ToolResult",
    "ToolConfig",
    "ToolServerConfig",
    "ToolFunction",
    # 하위 호환성 alias
    "MCPToolResult",
    "MCPToolConfig",
    "MCPServerConfig",
    "MCPToolFunction",
    # 도구 함수들
    "search_weaviate",
    "get_document_by_id",
    "search_graph",
    "get_neighbors",
    # 웹 검색
    "web_search",
    "WebSearchService",
    "WebSearchProvider",
    "WebSearchResult",
    "WebSearchResponse",
    "TavilyProvider",
    "BraveProvider",
    "DuckDuckGoProvider",
]
