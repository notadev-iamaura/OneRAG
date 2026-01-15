"""Tool Server DI Container 통합 테스트 (MCP 하위 호환성)"""

from unittest.mock import AsyncMock

import pytest


def test_mcp_server_provider_exists():
    """AppContainer에 mcp_server provider가 있는지 확인"""
    from app.core.di_container import AppContainer

    assert hasattr(AppContainer, "mcp_server")


def test_create_mcp_server_helper_exists():
    """create_mcp_server_instance 헬퍼 함수 존재 확인"""
    from app.core.di_container import create_mcp_server_instance

    assert callable(create_mcp_server_instance)


@pytest.mark.asyncio
async def test_create_mcp_server_disabled():
    """MCP/Tools 비활성화 시 None 반환"""
    from app.core.di_container import create_mcp_server_instance

    config = {
        "mcp": {
            "enabled": False,
        }
    }

    result = await create_mcp_server_instance(config, retriever=None)

    assert result is None


@pytest.mark.asyncio
async def test_create_mcp_server_enabled():
    """MCP/Tools 활성화 시 ToolServer(MCPServer alias) 인스턴스 반환"""
    from app.core.di_container import create_mcp_server_instance
    from app.modules.core.tools import ToolServer

    mock_retriever = AsyncMock()

    config = {
        "mcp": {
            "enabled": True,
            "server_name": "test-server",
            "default_timeout": 30,
            "max_concurrent_tools": 3,
            "tools": {
                "search_weaviate": {
                    "enabled": True,
                    "description": "Weaviate 검색",
                    "timeout": 15,
                },
            },
        }
    }

    result = await create_mcp_server_instance(config, retriever=mock_retriever)

    assert result is not None
    assert isinstance(result, ToolServer)
    assert result.server_name == "test-server"


@pytest.mark.asyncio
async def test_create_mcp_server_injects_retriever():
    """Tool 서버에 retriever가 주입되는지 확인"""
    from app.core.di_container import create_mcp_server_instance

    mock_retriever = AsyncMock()

    config = {
        "mcp": {
            "enabled": True,
            "server_name": "test-server",
            "tools": {},
        }
    }

    result = await create_mcp_server_instance(config, retriever=mock_retriever)

    # global_config에 retriever가 포함되어 있는지 확인
    assert result._global_config.get("retriever") is mock_retriever


