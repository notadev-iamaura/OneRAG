# tests/unit/modules/core/tools/test_interfaces.py
"""
tools 모듈 인터페이스 테스트

TDD Red 단계: 새로운 tools 모듈의 인터페이스를 테스트합니다.
- ToolResult, ToolConfig, ToolServerConfig 클래스 테스트
- 하위 호환성 alias (MCPToolResult, MCPToolConfig 등) 테스트
"""


class TestToolInterfacesImport:
    """tools 인터페이스 import 테스트"""

    def test_import_tool_result(self) -> None:
        """ToolResult 클래스 import 테스트"""
        from app.modules.core.tools.interfaces import ToolResult

        # 기본 인스턴스 생성 테스트
        result = ToolResult(
            success=True,
            data={"test": "data"},
            error=None,
            tool_name="test_tool",
            execution_time=0.5,
            metadata={"key": "value"},
        )

        assert result.success is True
        assert result.data == {"test": "data"}
        assert result.error is None
        assert result.tool_name == "test_tool"
        assert result.execution_time == 0.5
        assert result.metadata == {"key": "value"}

    def test_import_tool_config(self) -> None:
        """ToolConfig 클래스 import 테스트"""
        from app.modules.core.tools.interfaces import ToolConfig

        # 기본 인스턴스 생성 테스트
        config = ToolConfig(
            name="search_weaviate",
            description="Weaviate 검색 도구",
            enabled=True,
            timeout=30.0,
            retry_count=3,
            parameters={"top_k": 10},
        )

        assert config.name == "search_weaviate"
        assert config.description == "Weaviate 검색 도구"
        assert config.enabled is True
        assert config.timeout == 30.0
        assert config.retry_count == 3
        assert config.parameters == {"top_k": 10}

    def test_import_tool_server_config(self) -> None:
        """ToolServerConfig 클래스 import 테스트"""
        from app.modules.core.tools.interfaces import ToolServerConfig

        # 기본 인스턴스 생성 테스트
        server_config = ToolServerConfig(
            enabled=True,
            server_name="test-server",
            default_timeout=30.0,
            max_concurrent_tools=5,
        )

        assert server_config.enabled is True
        assert server_config.server_name == "test-server"
        assert server_config.default_timeout == 30.0
        assert server_config.max_concurrent_tools == 5

    def test_import_tool_function_type(self) -> None:
        """ToolFunction 타입 import 테스트"""
        from app.modules.core.tools.interfaces import ToolFunction

        # 타입이 존재하는지 확인
        assert ToolFunction is not None


class TestBackwardCompatibilityAliases:
    """하위 호환성 alias 테스트"""

    def test_mcp_tool_result_alias(self) -> None:
        """MCPToolResult → ToolResult alias 테스트"""
        from app.modules.core.tools.interfaces import MCPToolResult, ToolResult

        # 동일한 클래스인지 확인
        assert MCPToolResult is ToolResult

    def test_mcp_tool_config_alias(self) -> None:
        """MCPToolConfig → ToolConfig alias 테스트"""
        from app.modules.core.tools.interfaces import MCPToolConfig, ToolConfig

        # 동일한 클래스인지 확인
        assert MCPToolConfig is ToolConfig

    def test_mcp_server_config_alias(self) -> None:
        """MCPServerConfig → ToolServerConfig alias 테스트"""
        from app.modules.core.tools.interfaces import MCPServerConfig, ToolServerConfig

        # 동일한 클래스인지 확인
        assert MCPServerConfig is ToolServerConfig

    def test_mcp_tool_function_alias(self) -> None:
        """MCPToolFunction → ToolFunction alias 테스트"""
        from app.modules.core.tools.interfaces import MCPToolFunction, ToolFunction

        # 동일한 타입인지 확인
        assert MCPToolFunction is ToolFunction


class TestToolResultDefaultValues:
    """ToolResult 기본값 테스트"""

    def test_default_values(self) -> None:
        """기본값이 올바르게 설정되는지 테스트"""
        from app.modules.core.tools.interfaces import ToolResult

        # 최소 필수 인자만으로 생성
        result = ToolResult(success=True, data=None)

        assert result.success is True
        assert result.data is None
        assert result.error is None
        assert result.tool_name == ""
        assert result.execution_time == 0.0
        assert result.metadata == {}


class TestToolConfigDefaultValues:
    """ToolConfig 기본값 테스트"""

    def test_default_values(self) -> None:
        """기본값이 올바르게 설정되는지 테스트"""
        from app.modules.core.tools.interfaces import ToolConfig

        # 최소 필수 인자만으로 생성
        config = ToolConfig(
            name="test_tool",
            description="테스트 도구",
        )

        assert config.name == "test_tool"
        assert config.description == "테스트 도구"
        assert config.enabled is True
        assert config.timeout == 30.0
        assert config.retry_count == 1
        assert config.parameters == {}


class TestToolServerConfigDefaultValues:
    """ToolServerConfig 기본값 테스트"""

    def test_default_values(self) -> None:
        """기본값이 올바르게 설정되는지 테스트"""
        from app.modules.core.tools.interfaces import ToolServerConfig

        # 기본값으로 생성
        server_config = ToolServerConfig()

        assert server_config.enabled is True
        assert server_config.server_name == "blank-rag-system"
        assert server_config.default_timeout == 30.0
        assert server_config.max_concurrent_tools == 3
        assert server_config.tools == {}


class TestToolsModuleExports:
    """tools 모듈 __init__ export 테스트"""

    def test_interfaces_exported_from_module(self) -> None:
        """tools 모듈에서 interfaces가 export 되는지 테스트"""
        from app.modules.core.tools import (
            MCPServerConfig,
            MCPToolConfig,
            MCPToolFunction,
            MCPToolResult,
            ToolConfig,
            ToolFunction,
            ToolResult,
            ToolServerConfig,
        )

        # 모든 클래스가 import 가능한지 확인
        assert ToolResult is not None
        assert ToolConfig is not None
        assert ToolServerConfig is not None
        assert ToolFunction is not None

        # 하위 호환성 alias도 확인
        assert MCPToolResult is ToolResult
        assert MCPToolConfig is ToolConfig
        assert MCPServerConfig is ToolServerConfig
        assert MCPToolFunction is ToolFunction
