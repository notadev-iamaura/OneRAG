"""Tool 서버 테스트 (MCP 하위 호환성)"""

import pytest


def test_tool_server_init():
    """ToolServer 초기화 테스트"""
    from app.modules.core.tools import ToolServer, ToolServerConfig

    config = ToolServerConfig(
        enabled=True,
        server_name="test-server",
    )

    server = ToolServer(config=config, global_config={})

    assert server.server_name == "test-server"
    assert server.is_enabled is True


def test_tool_server_get_enabled_tools():
    """활성화된 도구 목록 조회"""
    from app.modules.core.tools import ToolConfig, ToolServer, ToolServerConfig

    config = ToolServerConfig(
        enabled=True,
        server_name="test-server",
        tools={
            "tool1": ToolConfig(name="tool1", description="Tool 1", enabled=True),
            "tool2": ToolConfig(name="tool2", description="Tool 2", enabled=False),
        },
    )

    server = ToolServer(config=config, global_config={})
    enabled = server.get_enabled_tools()

    assert "tool1" in enabled
    assert "tool2" not in enabled


def test_tool_server_get_tool_schemas():
    """도구 스키마 반환 테스트 (OpenAI Function Calling 형식)"""
    from app.modules.core.tools import ToolConfig, ToolServer, ToolServerConfig

    config = ToolServerConfig(
        enabled=True,
        server_name="test-server",
        tools={
            "search_weaviate": ToolConfig(
                name="search_weaviate",
                description="검색 도구",
                enabled=True,
                parameters={"default_top_k": 10},
            ),
        },
    )

    server = ToolServer(config=config, global_config={})
    schemas = server.get_tool_schemas()

    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "search_weaviate"


def test_tool_server_get_tool_config():
    """특정 도구 설정 조회"""
    from app.modules.core.tools import ToolConfig, ToolServer, ToolServerConfig

    config = ToolServerConfig(
        enabled=True,
        server_name="test-server",
        tools={
            "search_weaviate": ToolConfig(
                name="search_weaviate",
                description="검색 도구",
                enabled=True,
                timeout=15.0,
            ),
        },
    )

    server = ToolServer(config=config, global_config={})
    tool_config = server.get_tool_config("search_weaviate")

    assert tool_config is not None
    assert tool_config.name == "search_weaviate"
    assert tool_config.timeout == 15.0


def test_tool_server_get_tool_config_unknown():
    """알 수 없는 도구 설정 조회 시 None 반환"""
    from app.modules.core.tools import ToolServer, ToolServerConfig

    config = ToolServerConfig(
        enabled=True,
        server_name="test-server",
    )

    server = ToolServer(config=config, global_config={})
    tool_config = server.get_tool_config("unknown_tool")

    assert tool_config is None


def test_tool_server_get_stats():
    """서버 통계 조회"""
    from app.modules.core.tools import ToolServer, ToolServerConfig

    config = ToolServerConfig(
        enabled=True,
        server_name="test-server",
    )

    server = ToolServer(config=config, global_config={})
    stats = server.get_stats()

    assert "total_calls" in stats
    assert "successful_calls" in stats
    assert "failed_calls" in stats
    assert "initialized" in stats


@pytest.mark.asyncio
async def test_tool_server_initialize():
    """서버 초기화 테스트"""
    from app.modules.core.tools import ToolServer, ToolServerConfig

    config = ToolServerConfig(
        enabled=True,
        server_name="test-server",
    )

    server = ToolServer(config=config, global_config={})

    assert server._initialized is False

    await server.initialize()

    assert server._initialized is True


@pytest.mark.asyncio
async def test_tool_server_shutdown():
    """서버 종료 테스트"""
    from app.modules.core.tools import ToolServer, ToolServerConfig

    config = ToolServerConfig(
        enabled=True,
        server_name="test-server",
    )

    server = ToolServer(config=config, global_config={})
    await server.initialize()

    assert server._initialized is True

    await server.shutdown()

    assert server._initialized is False


@pytest.mark.asyncio
async def test_tool_server_execute_tool_disabled():
    """비활성화된 도구 실행 시 에러"""
    from app.modules.core.tools import ToolConfig, ToolServer, ToolServerConfig

    config = ToolServerConfig(
        enabled=True,
        server_name="test-server",
        tools={
            "disabled_tool": ToolConfig(
                name="disabled_tool",
                description="비활성화된 도구",
                enabled=False,
            ),
        },
    )

    server = ToolServer(config=config, global_config={})
    await server.initialize()

    result = await server.execute_tool("disabled_tool", {})

    assert result.success is False
    assert "비활성화" in result.error


def test_mcp_server_alias_compatibility():
    """MCPServer 하위 호환성 alias 테스트"""
    from app.modules.core.tools import MCPServer, ToolServer

    # MCPServer는 ToolServer의 alias
    assert MCPServer is ToolServer


