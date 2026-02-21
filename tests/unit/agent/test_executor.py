"""
AgentExecutor 테스트 - 도구 실행

ReAct 패턴의 "Acting" 담당 컴포넌트를 테스트합니다.
AgentExecutor는 ToolCall 리스트를 받아 MCPServer를 통해
실제 도구를 실행하고 ToolResult로 변환합니다.

테스트 케이스:
- 단일 도구 실행
- 복수 도구 병렬 실행
- 동시성 제한 (max_concurrent_tools)
- 도구 실행 실패 처리
- 타임아웃 처리
- 빈 리스트 처리
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.core.agent.executor import AgentExecutor
from app.modules.core.agent.interfaces import AgentConfig, ToolCall
from app.modules.core.tools import MCPToolResult


class TestAgentExecutorSingleTool:
    """단일 도구 실행 테스트"""

    @pytest.fixture
    def mock_mcp_server(self):
        """Mock MCP 서버"""
        server = MagicMock()
        server.execute_tool = AsyncMock()
        return server

    @pytest.fixture
    def agent_config(self):
        """에이전트 설정"""
        return AgentConfig(
            tool_timeout=15.0,
            parallel_execution=True,
        )

    @pytest.fixture
    def executor(self, mock_mcp_server, agent_config):
        """AgentExecutor 인스턴스"""
        return AgentExecutor(
            mcp_server=mock_mcp_server,
            config=agent_config,
        )

    @pytest.mark.asyncio
    async def test_executor_executes_single_tool(
        self, executor, mock_mcp_server
    ):
        """단일 도구 실행 테스트"""
        # Given: MCP 서버가 성공 결과를 반환하도록 설정
        mock_mcp_server.execute_tool.return_value = MCPToolResult(
            success=True,
            data={"documents": [{"content": "검색 결과"}]},
            tool_name="search_weaviate",
            execution_time=0.5,
        )

        tool_call = ToolCall(
            tool_name="search_weaviate",
            arguments={"query": "테스트 검색", "top_k": 5},
        )

        # When: 도구 실행
        results = await executor.execute([tool_call])

        # Then: 결과 검증
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].tool_name == "search_weaviate"
        assert results[0].call_id == tool_call.call_id
        assert results[0].data == {"documents": [{"content": "검색 결과"}]}
        mock_mcp_server.execute_tool.assert_called_once_with(
            tool_name="search_weaviate",
            arguments={"query": "테스트 검색", "top_k": 5},
        )


class TestAgentExecutorMultipleTools:
    """복수 도구 실행 테스트"""

    @pytest.fixture
    def mock_mcp_server(self):
        """Mock MCP 서버"""
        server = MagicMock()
        server.execute_tool = AsyncMock()
        return server

    @pytest.fixture
    def agent_config(self):
        """에이전트 설정 (병렬 실행 활성화)"""
        return AgentConfig(
            tool_timeout=15.0,
            parallel_execution=True,
        )

    @pytest.fixture
    def executor(self, mock_mcp_server, agent_config):
        """AgentExecutor 인스턴스"""
        return AgentExecutor(
            mcp_server=mock_mcp_server,
            config=agent_config,
        )

    @pytest.mark.asyncio
    async def test_executor_executes_multiple_tools(
        self, executor, mock_mcp_server
    ):
        """복수 도구 병렬 실행 테스트"""
        # Given: 2개의 도구 결과 설정
        mock_mcp_server.execute_tool.side_effect = [
            MCPToolResult(
                success=True,
                data={"result": "검색 결과"},
                tool_name="search_weaviate",
            ),
            MCPToolResult(
                success=True,
                data={"result": "SQL 결과"},
                tool_name="query_sql",
            ),
        ]

        tool_calls = [
            ToolCall(
                tool_name="search_weaviate", arguments={"query": "검색어"}
            ),
            ToolCall(tool_name="query_sql", arguments={"question": "질문"}),
        ]

        # When: 도구 실행
        results = await executor.execute(tool_calls)

        # Then: 결과 검증
        assert len(results) == 2
        assert mock_mcp_server.execute_tool.call_count == 2

        # 순서 보장 확인
        assert results[0].tool_name == "search_weaviate"
        assert results[1].tool_name == "query_sql"


class TestAgentExecutorConcurrencyLimit:
    """동시성 제한 테스트"""

    @pytest.fixture
    def mock_mcp_server(self):
        """Mock MCP 서버 (지연 있음)"""
        server = MagicMock()

        async def delayed_execute(tool_name: str, arguments: dict):
            """실행 시간을 추적하기 위한 지연 함수"""
            await asyncio.sleep(0.1)  # 100ms 지연
            return MCPToolResult(
                success=True,
                data={"tool": tool_name},
                tool_name=tool_name,
            )

        server.execute_tool = AsyncMock(side_effect=delayed_execute)
        return server

    @pytest.fixture
    def agent_config(self):
        """에이전트 설정 (동시 실행 2개로 제한)"""
        return AgentConfig(
            tool_timeout=15.0,
            parallel_execution=True,
            max_concurrent_tools=2,  # 동시 실행 2개 제한
        )

    @pytest.fixture
    def executor(self, mock_mcp_server, agent_config):
        """AgentExecutor 인스턴스"""
        return AgentExecutor(
            mcp_server=mock_mcp_server,
            config=agent_config,
        )

    @pytest.mark.asyncio
    async def test_executor_respects_concurrency_limit(
        self, executor, mock_mcp_server
    ):
        """동시 실행 제한 테스트"""
        # Given: 4개의 도구 호출
        tool_calls = [
            ToolCall(tool_name=f"tool_{i}", arguments={})
            for i in range(4)
        ]

        # When: 도구 실행
        results = await executor.execute(tool_calls)

        # Then: 모든 도구가 실행되었는지 확인
        assert len(results) == 4
        assert mock_mcp_server.execute_tool.call_count == 4

        # 모든 결과가 성공인지 확인
        for result in results:
            assert result.success is True


class TestAgentExecutorFailureHandling:
    """실패 처리 테스트"""

    @pytest.fixture
    def mock_mcp_server(self):
        """Mock MCP 서버"""
        server = MagicMock()
        server.execute_tool = AsyncMock()
        return server

    @pytest.fixture
    def agent_config(self):
        """에이전트 설정"""
        return AgentConfig(
            tool_timeout=15.0,
            parallel_execution=True,
        )

    @pytest.fixture
    def executor(self, mock_mcp_server, agent_config):
        """AgentExecutor 인스턴스"""
        return AgentExecutor(
            mcp_server=mock_mcp_server,
            config=agent_config,
        )

    @pytest.mark.asyncio
    async def test_executor_handles_tool_failure(
        self, executor, mock_mcp_server
    ):
        """도구 실행 실패 처리 테스트"""
        # Given: MCP 서버가 실패 결과를 반환
        mock_mcp_server.execute_tool.return_value = MCPToolResult(
            success=False,
            data=None,
            error="도구 실행 중 에러 발생",
            tool_name="search_weaviate",
        )

        tool_call = ToolCall(
            tool_name="search_weaviate",
            arguments={"query": "테스트"},
        )

        # When: 도구 실행
        results = await executor.execute([tool_call])

        # Then: 실패 결과 검증
        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error == "도구 실행 중 에러 발생"
        assert results[0].data is None

    @pytest.mark.asyncio
    async def test_executor_handles_exception(
        self, executor, mock_mcp_server
    ):
        """예외 발생 처리 테스트"""
        # Given: MCP 서버가 예외를 발생
        mock_mcp_server.execute_tool.side_effect = Exception("네트워크 에러")

        tool_call = ToolCall(
            tool_name="search_weaviate",
            arguments={"query": "테스트"},
        )

        # When: 도구 실행
        results = await executor.execute([tool_call])

        # Then: 예외가 ToolResult로 변환되었는지 확인
        assert len(results) == 1
        assert results[0].success is False
        assert "네트워크 에러" in results[0].error

    @pytest.mark.asyncio
    async def test_executor_handles_timeout(
        self, executor, mock_mcp_server, agent_config
    ):
        """타임아웃 처리 테스트"""
        # Given: MCP 서버가 타임아웃 발생
        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(2)  # 타임아웃 유발용 (0.1초 타임아웃 대비 충분)
            return MCPToolResult(success=True, data={}, tool_name="slow_tool")

        mock_mcp_server.execute_tool.side_effect = slow_execute

        # 타임아웃을 매우 짧게 설정
        agent_config.tool_timeout = 0.1  # 100ms

        tool_call = ToolCall(
            tool_name="slow_tool",
            arguments={},
        )

        # When: 도구 실행 (타임아웃 발생)
        executor_with_short_timeout = AgentExecutor(
            mcp_server=mock_mcp_server,
            config=agent_config,
        )
        results = await executor_with_short_timeout.execute([tool_call])

        # Then: 타임아웃 결과 검증
        assert len(results) == 1
        assert results[0].success is False
        assert "타임아웃" in results[0].error or "Timeout" in results[0].error


class TestAgentExecutorEdgeCases:
    """엣지 케이스 테스트"""

    @pytest.fixture
    def mock_mcp_server(self):
        """Mock MCP 서버"""
        server = MagicMock()
        server.execute_tool = AsyncMock()
        return server

    @pytest.fixture
    def agent_config(self):
        """에이전트 설정"""
        return AgentConfig(
            tool_timeout=15.0,
            parallel_execution=True,
        )

    @pytest.fixture
    def executor(self, mock_mcp_server, agent_config):
        """AgentExecutor 인스턴스"""
        return AgentExecutor(
            mcp_server=mock_mcp_server,
            config=agent_config,
        )

    @pytest.mark.asyncio
    async def test_executor_handles_empty_list(self, executor):
        """빈 리스트 처리 테스트"""
        # When: 빈 리스트로 실행
        results = await executor.execute([])

        # Then: 빈 결과 반환
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_executor_sequential_mode(self, mock_mcp_server):
        """순차 실행 모드 테스트"""
        # Given: 순차 실행 설정
        config = AgentConfig(
            tool_timeout=15.0,
            parallel_execution=False,  # 순차 실행
        )
        executor = AgentExecutor(
            mcp_server=mock_mcp_server,
            config=config,
        )

        mock_mcp_server.execute_tool.side_effect = [
            MCPToolResult(success=True, data={"n": 1}, tool_name="tool_1"),
            MCPToolResult(success=True, data={"n": 2}, tool_name="tool_2"),
        ]

        tool_calls = [
            ToolCall(tool_name="tool_1", arguments={}),
            ToolCall(tool_name="tool_2", arguments={}),
        ]

        # When: 순차 실행
        results = await executor.execute(tool_calls)

        # Then: 순서대로 실행되었는지 확인
        assert len(results) == 2
        assert results[0].data["n"] == 1
        assert results[1].data["n"] == 2

    @pytest.mark.asyncio
    async def test_executor_partial_failure(
        self, executor, mock_mcp_server
    ):
        """일부 도구만 실패하는 경우 테스트"""
        # Given: 첫 번째는 성공, 두 번째는 실패
        mock_mcp_server.execute_tool.side_effect = [
            MCPToolResult(
                success=True,
                data={"result": "성공"},
                tool_name="tool_1",
            ),
            MCPToolResult(
                success=False,
                data=None,
                error="실패",
                tool_name="tool_2",
            ),
        ]

        tool_calls = [
            ToolCall(tool_name="tool_1", arguments={}),
            ToolCall(tool_name="tool_2", arguments={}),
        ]

        # When: 도구 실행
        results = await executor.execute(tool_calls)

        # Then: 각각의 결과가 올바르게 반환되었는지 확인
        assert len(results) == 2
        assert results[0].success is True
        assert results[1].success is False

    @pytest.mark.asyncio
    async def test_executor_result_has_execution_time(
        self, executor, mock_mcp_server
    ):
        """실행 시간이 기록되는지 테스트"""
        # Given: 실행 시간이 포함된 결과
        mock_mcp_server.execute_tool.return_value = MCPToolResult(
            success=True,
            data={},
            tool_name="test_tool",
            execution_time=0.5,
        )

        tool_call = ToolCall(tool_name="test_tool", arguments={})

        # When: 도구 실행
        results = await executor.execute([tool_call])

        # Then: 실행 시간이 기록되었는지 확인
        assert len(results) == 1
        assert results[0].execution_time >= 0

    @pytest.mark.asyncio
    async def test_executor_preserves_call_id(
        self, executor, mock_mcp_server
    ):
        """call_id가 보존되는지 테스트"""
        # Given
        mock_mcp_server.execute_tool.return_value = MCPToolResult(
            success=True,
            data={},
            tool_name="test_tool",
        )

        tool_call = ToolCall(
            tool_name="test_tool",
            arguments={},
            call_id="custom-call-id",
        )

        # When: 도구 실행
        results = await executor.execute([tool_call])

        # Then: call_id가 보존되었는지 확인
        assert results[0].call_id == "custom-call-id"
