"""Tool 인터페이스 테스트 (MCP 하위 호환성)"""

from dataclasses import is_dataclass


def test_tool_result_is_dataclass():
    """ToolResult가 dataclass인지 확인"""
    from app.modules.core.tools import ToolResult

    assert is_dataclass(ToolResult)


def test_tool_result_fields():
    """ToolResult 필드 확인"""
    from app.modules.core.tools import ToolResult

    result = ToolResult(
        success=True,
        data={"key": "value"},
        error=None,
        tool_name="test_tool",
        execution_time=0.5,
    )

    assert result.success is True
    assert result.data == {"key": "value"}
    assert result.error is None
    assert result.tool_name == "test_tool"
    assert result.execution_time == 0.5


def test_tool_result_default_values():
    """ToolResult 기본값 확인"""
    from app.modules.core.tools import ToolResult

    result = ToolResult(
        success=False,
        data=None,
    )

    assert result.success is False
    assert result.data is None
    assert result.error is None
    assert result.tool_name == ""
    assert result.execution_time == 0.0


def test_tool_config_fields():
    """ToolConfig 필드 확인"""
    from app.modules.core.tools import ToolConfig

    config = ToolConfig(
        name="search_weaviate",
        description="Weaviate 검색",
        enabled=True,
        timeout=30.0,
    )

    assert config.name == "search_weaviate"
    assert config.description == "Weaviate 검색"
    assert config.enabled is True
    assert config.timeout == 30.0


def test_tool_config_default_values():
    """ToolConfig 기본값 확인"""
    from app.modules.core.tools import ToolConfig

    config = ToolConfig(
        name="test_tool",
        description="테스트 도구",
    )

    assert config.enabled is True  # 기본값 True
    assert config.timeout == 30.0  # 기본값 30초
    assert config.retry_count == 1  # 기본값 1회


def test_tool_server_config_fields():
    """ToolServerConfig 필드 확인"""
    from app.modules.core.tools import ToolServerConfig

    config = ToolServerConfig(
        enabled=True,
        server_name="test-server",
        default_timeout=60.0,
        max_concurrent_tools=5,
    )

    assert config.enabled is True
    assert config.server_name == "test-server"
    assert config.default_timeout == 60.0
    assert config.max_concurrent_tools == 5


def test_tool_server_config_default_values():
    """ToolServerConfig 기본값 확인"""
    from app.modules.core.tools import ToolServerConfig

    config = ToolServerConfig()

    assert config.enabled is True
    # 범용화: 도메인 특화 이름에서 일반 이름으로 변경됨
    assert config.server_name == "blank-rag-system"
    assert config.default_timeout == 30.0
    assert config.max_concurrent_tools == 3


def test_mcp_alias_compatibility():
    """MCP* 하위 호환성 alias 테스트"""
    from app.modules.core.tools import (
        MCPServerConfig,
        MCPToolConfig,
        MCPToolResult,
        ToolConfig,
        ToolResult,
        ToolServerConfig,
    )

    # alias 확인
    assert MCPToolResult is ToolResult
    assert MCPToolConfig is ToolConfig
    assert MCPServerConfig is ToolServerConfig


