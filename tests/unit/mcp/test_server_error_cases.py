"""
Tool Server 에러 케이스 테스트 (MCP 하위 호환성)

현재 커버리지: 62.50%
목표 커버리지: 85-90%

미스된 라인:
- Line 98, 188, 196-200: FastMCP 임포트 에러 핸들링
- Line 216-239: 도구 함수 로딩 실패 케이스
- Line 274-319: 도구 실행 에러 케이스 (비활성화, 미등록, 타임아웃, 예외)
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


class TestToolServerInitialization:
    """Tool Server 초기화 테스트"""

    @pytest.mark.asyncio
    async def test_fastmcp_import_error_fallback(self) -> None:
        """
        FastMCP 임포트 에러 시 폴백 테스트

        Given: FastMCP 라이브러리가 설치되지 않음
        When: ToolServer 초기화
        Then: 경고 로그, 기본 모드로 동작
        """
        from app.modules.core.tools import ToolConfig, ToolServer, ToolServerConfig

        # ToolServerConfig 객체 생성
        config = ToolServerConfig(
            enabled=True,
            server_name="test-server",
            tools={
                "search_weaviate": ToolConfig(
                    name="search_weaviate",
                    description="Test tool",
                    enabled=True,
                    timeout=15,
                ),
            },
        )

        with patch.dict("sys.modules", {"fastmcp": None}):
            with patch("app.modules.core.tools.server.logger") as mock_logger:
                server = ToolServer(config=config, global_config={})
                await server.initialize()

                # 검증: FastMCP 없이도 초기화 성공
                assert server._initialized is True
                assert server._fastmcp is None  # FastMCP 미사용
                mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_tool_function_load_failure(self) -> None:
        """
        도구 함수 로딩 실패 테스트

        Given: 도구 모듈이 존재하지 않음
        When: 도구 함수 로딩 시도
        Then: 경고 로그, 스킵
        """
        from app.modules.core.tools import ToolConfig, ToolServer, ToolServerConfig

        # 존재하지 않는 도구 추가
        config = ToolServerConfig(
            enabled=True,
            server_name="test-server",
            tools={
                "nonexistent_tool": ToolConfig(
                    name="nonexistent_tool",
                    description="Nonexistent tool",
                    enabled=True,
                    timeout=10,
                ),
            },
        )

        server = ToolServer(config=config, global_config={})
        await server.initialize()

        # 검증: 존재하는 도구만 로딩됨
        assert "nonexistent_tool" not in server._tool_functions


class TestToolServerToolExecution:
    """Tool Server 도구 실행 테스트"""

    @pytest.fixture
    def initialized_server(self) -> Any:
        """초기화된 Tool Server (수동 설정)"""
        from app.modules.core.tools import ToolConfig, ToolServer, ToolServerConfig

        config = ToolServerConfig(
            enabled=True,
            server_name="test-server",
            tools={
                "search_weaviate": ToolConfig(
                    name="search_weaviate",
                    description="Test tool",
                    enabled=True,
                    timeout=15,
                ),
            },
        )

        server = ToolServer(config=config, global_config={})
        # 도구 함수 직접 추가 (초기화 없이)
        server._initialized = True
        server._tool_functions = {
            "search_weaviate": AsyncMock(
                return_value={"documents": ["doc1", "doc2"]}
            )
        }
        return server

    @pytest.mark.asyncio
    async def test_tool_disabled_execution(self) -> None:
        """
        비활성화된 도구 실행 시도 테스트

        Given: 도구가 비활성화됨 (enabled=False)
        When: 도구 실행 시도
        Then: 실패 결과 반환
        """
        from app.modules.core.tools import ToolConfig, ToolServer, ToolServerConfig

        # 도구 비활성화
        config = ToolServerConfig(
            enabled=True,
            server_name="test-server",
            tools={
                "search_weaviate": ToolConfig(
                    name="search_weaviate",
                    description="Test tool",
                    enabled=False,  # 비활성화
                    timeout=15,
                ),
            },
        )

        server = ToolServer(config=config, global_config={})
        await server.initialize()

        result = await server.execute_tool(
            tool_name="search_weaviate",
            arguments={"query": "test"},
        )

        # 검증: 실패 결과
        assert result.success is False
        assert "비활성화" in result.error or "disabled" in result.error.lower()

    @pytest.mark.asyncio
    async def test_tool_not_registered(self) -> None:
        """
        미등록 도구 실행 시도 테스트

        Given: 도구 설정은 있지만 함수가 등록되지 않음
        When: 도구 실행 시도
        Then: 실패 결과 반환
        """
        from app.modules.core.tools import ToolConfig, ToolServer, ToolServerConfig

        config = ToolServerConfig(
            enabled=True,
            server_name="test-server",
            tools={
                "unknown_tool": ToolConfig(
                    name="unknown_tool",
                    description="Unknown tool",
                    enabled=True,
                    timeout=15,
                ),
            },
        )

        server = ToolServer(config=config, global_config={})
        server._initialized = True
        server._tool_functions = {}  # 도구 함수 미등록

        result = await server.execute_tool(
            tool_name="unknown_tool",
            arguments={"key": "value"},
        )

        # 검증: 실패 결과
        assert result.success is False
        assert "미등록" in result.error or "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_tool_timeout(self) -> None:
        """
        도구 실행 타임아웃 테스트

        Given: 도구 실행 시간이 timeout 초과
        When: 도구 실행
        Then: 타임아웃 에러 반환
        """
        import asyncio

        from app.modules.core.tools import ToolConfig, ToolServer, ToolServerConfig

        # 타임아웃 발생하는 도구 함수
        async def slow_function(args, config):
            await asyncio.sleep(100)  # 매우 느림
            return {"result": "success"}

        config = ToolServerConfig(
            enabled=True,
            server_name="test-server",
            tools={
                "slow_tool": ToolConfig(
                    name="slow_tool",
                    description="Slow tool",
                    enabled=True,
                    timeout=0.1,  # 짧은 타임아웃
                ),
            },
        )

        server = ToolServer(config=config, global_config={})
        server._initialized = True

        # 도구 함수 직접 추가
        server._tool_functions["slow_tool"] = slow_function

        result = await server.execute_tool(
            tool_name="slow_tool",
            arguments={},
        )

        # 검증: 타임아웃 에러
        assert result.success is False
        assert "타임아웃" in result.error or "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_tool_execution_exception(self) -> None:
        """
        도구 실행 중 예외 발생 테스트

        Given: 도구 함수가 예외 발생
        When: 도구 실행
        Then: 실패 결과 반환
        """
        from app.modules.core.tools import ToolConfig, ToolServer, ToolServerConfig

        # 예외 발생하는 도구 함수
        async def error_function(args, config):
            raise ValueError("Invalid argument")

        config = ToolServerConfig(
            enabled=True,
            server_name="test-server",
            tools={
                "error_tool": ToolConfig(
                    name="error_tool",
                    description="Error tool",
                    enabled=True,
                    timeout=10.0,
                ),
            },
        )

        server = ToolServer(config=config, global_config={})
        server._initialized = True

        # 도구 함수 직접 추가
        server._tool_functions["error_tool"] = error_function

        result = await server.execute_tool(
            tool_name="error_tool",
            arguments={"key": "value"},
        )

        # 검증: 실패 결과
        assert result.success is False
        assert "Invalid argument" in result.error or "error" in result.error.lower()

    @pytest.mark.asyncio
    async def test_module_not_found_graceful_skip(self) -> None:
        """
        모듈 미발견 시 graceful skip 테스트

        Given: 도구 모듈 파일이 존재하지 않음
        When: 도구 함수 로딩
        Then: 경고 로그, 스킵 (에러 없음)
        """
        from app.modules.core.tools import ToolConfig, ToolServer, ToolServerConfig

        with patch("importlib.import_module") as mock_import:
            mock_import.side_effect = ModuleNotFoundError("No module")

            config = ToolServerConfig(
                enabled=True,
                server_name="test-server",
                tools={
                    "search_weaviate": ToolConfig(
                        name="search_weaviate",
                        description="Test tool",
                        enabled=True,
                        timeout=15,
                    ),
                },
            )

            server = ToolServer(config=config, global_config={})
            await server.initialize()

            # 검증: 초기화 성공 (에러 없음)
            assert server._initialized is True
