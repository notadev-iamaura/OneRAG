# app/modules/core/tools/interfaces.py
"""
Tools 인터페이스 및 타입 정의

기존 MCP 인터페이스를 Tools로 리네이밍합니다.
하위 호환성을 위해 MCP* alias를 제공합니다.

Attributes:
    ToolResult: 도구 실행 결과 (이전: MCPToolResult)
    ToolConfig: 도구 설정 (이전: MCPToolConfig)
    ToolServerConfig: 서버 전체 설정 (이전: MCPServerConfig)
    ToolFunction: 도구 함수 타입 (이전: MCPToolFunction)
"""
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """
    도구 실행 결과

    Attributes:
        success: 실행 성공 여부
        data: 실행 결과 데이터
        error: 에러 메시지 (실패 시)
        tool_name: 실행된 도구 이름
        execution_time: 실행 시간 (초)
        metadata: 추가 메타데이터
    """

    success: bool
    data: Any
    error: str | None = None
    tool_name: str = ""
    execution_time: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolConfig:
    """
    도구 설정

    YAML 설정에서 로드되어 도구별 동작을 제어합니다.

    Attributes:
        name: 도구 이름 (예: "search_weaviate")
        description: 도구 설명 (LLM이 도구 선택 시 참고)
        enabled: 활성화 여부 (YAML에서 On/Off)
        timeout: 실행 타임아웃 (초)
        retry_count: 재시도 횟수
        parameters: 도구별 추가 파라미터
    """

    name: str
    description: str
    enabled: bool = True
    timeout: float = 30.0
    retry_count: int = 1
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolServerConfig:
    """
    도구 서버 전체 설정

    YAML의 mcp 섹션에서 로드됩니다.

    Attributes:
        enabled: 기능 전체 활성화 여부
        server_name: 서버 이름
        default_timeout: 기본 타임아웃 (초)
        max_concurrent_tools: 동시 실행 가능한 도구 수
        tools: 등록된 도구 설정 (도구명 → ToolConfig)
    """

    enabled: bool = True
    server_name: str = "blank-rag-system"
    default_timeout: float = 30.0
    max_concurrent_tools: int = 3
    tools: dict[str, ToolConfig] = field(default_factory=dict)


# 도구 함수 타입 힌트
# async def tool_func(arguments: dict, config: dict) -> Any
ToolFunction = Callable[..., Coroutine[Any, Any, Any]]


# ========================================
# 하위 호환성 alias (MCP* → Tool*)
# 기존 코드에서 MCP* 이름을 사용하는 경우를 위함
# ========================================
MCPToolResult = ToolResult
MCPToolConfig = ToolConfig
MCPServerConfig = ToolServerConfig
MCPToolFunction = ToolFunction
