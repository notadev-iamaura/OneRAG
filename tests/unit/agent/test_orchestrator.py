"""
AgentOrchestrator 테스트 - 메인 에이전트 루프

ReAct 패턴 기반 에이전트 루프를 검증하는 단위 테스트.
Plan -> Execute -> Observe -> Synthesize 사이클을 테스트합니다.

테스트 케이스:
- 단일 스텝 성공
- 다중 스텝 실행
- 최대 반복 횟수 제한
- 도구 없이 직접 답변
- 에러 처리
- AgentResult 반환 형식
"""

from unittest.mock import AsyncMock

import pytest

from app.modules.core.agent.interfaces import (
    AgentConfig,
    AgentResult,
    ToolCall,
    ToolResult,
)
from app.modules.core.agent.orchestrator import AgentOrchestrator


class TestAgentOrchestrator:
    """AgentOrchestrator 단위 테스트"""

    @pytest.fixture
    def mock_planner(self) -> AsyncMock:
        """Mock AgentPlanner"""
        planner = AsyncMock()
        planner.plan = AsyncMock()
        return planner

    @pytest.fixture
    def mock_executor(self) -> AsyncMock:
        """Mock AgentExecutor"""
        executor = AsyncMock()
        executor.execute = AsyncMock()
        return executor

    @pytest.fixture
    def mock_synthesizer(self) -> AsyncMock:
        """Mock AgentSynthesizer"""
        synthesizer = AsyncMock()
        synthesizer.synthesize = AsyncMock()
        return synthesizer

    @pytest.fixture
    def agent_config(self) -> AgentConfig:
        """에이전트 설정"""
        return AgentConfig(
            max_iterations=5,
            timeout=60.0,
            tool_timeout=15.0,
            parallel_execution=True,
        )

    @pytest.fixture
    def orchestrator(
        self,
        mock_planner: AsyncMock,
        mock_executor: AsyncMock,
        mock_synthesizer: AsyncMock,
        agent_config: AgentConfig,
    ) -> AgentOrchestrator:
        """AgentOrchestrator 인스턴스"""
        return AgentOrchestrator(
            planner=mock_planner,
            executor=mock_executor,
            synthesizer=mock_synthesizer,
            config=agent_config,
        )

    @pytest.mark.asyncio
    async def test_orchestrator_single_iteration(
        self,
        orchestrator: AgentOrchestrator,
        mock_planner: AsyncMock,
        mock_executor: AsyncMock,
        mock_synthesizer: AsyncMock,
    ) -> None:
        """
        단일 반복 실행 테스트

        검색 -> 결과 -> 종료 흐름을 검증합니다.
        """
        # Planner: 도구 선택 후 종료 (should_continue=False)
        tool_call = ToolCall(
            tool_name="search_weaviate",
            arguments={"query": "테스트 검색", "top_k": 5},
        )
        mock_planner.plan.return_value = (
            [tool_call],
            "검색이 필요합니다",
            False,  # should_continue = False (종료)
        )

        # Executor: 도구 실행 결과
        mock_executor.execute.return_value = [
            ToolResult(
                call_id=tool_call.call_id,
                tool_name="search_weaviate",
                success=True,
                data={"documents": [{"content": "검색 결과입니다"}]},
            )
        ]

        # Synthesizer: 최종 답변 생성
        mock_synthesizer.synthesize.return_value = (
            "검색 결과를 찾았습니다.",
            [{"source": "doc1.md", "title": "문서 1"}],
        )

        # 실행
        result = await orchestrator.run("테스트 질문")

        # 검증
        assert result.success is True
        assert result.answer == "검색 결과를 찾았습니다."
        assert result.steps_taken == 1
        assert len(result.sources) == 1
        assert "search_weaviate" in result.tools_used

        # 호출 검증
        mock_planner.plan.assert_called_once()
        mock_executor.execute.assert_called_once()
        mock_synthesizer.synthesize.assert_called_once()

    @pytest.mark.asyncio
    async def test_orchestrator_multiple_iterations(
        self,
        orchestrator: AgentOrchestrator,
        mock_planner: AsyncMock,
        mock_executor: AsyncMock,
        mock_synthesizer: AsyncMock,
    ) -> None:
        """
        다중 반복 실행 테스트

        첫 번째 스텝: 검색 -> 계속
        두 번째 스텝: 상세 조회 -> 종료
        """
        # 첫 번째 스텝: 계속 진행
        first_tool = ToolCall(
            tool_name="search_weaviate",
            arguments={"query": "테스트"},
        )
        # 두 번째 스텝: 종료
        second_tool = ToolCall(
            tool_name="get_document_by_id",
            arguments={"document_id": "doc-123"},
        )

        mock_planner.plan.side_effect = [
            ([first_tool], "먼저 검색합니다", True),  # 계속
            ([second_tool], "상세 조회합니다", False),  # 종료
        ]

        mock_executor.execute.side_effect = [
            [ToolResult(
                call_id=first_tool.call_id,
                tool_name="search_weaviate",
                success=True,
                data={"documents": [{"id": "doc-123"}]},
            )],
            [ToolResult(
                call_id=second_tool.call_id,
                tool_name="get_document_by_id",
                success=True,
                data={"content": "상세 내용"},
            )],
        ]

        mock_synthesizer.synthesize.return_value = (
            "최종 답변입니다.",
            [],
        )

        # 실행
        result = await orchestrator.run("복잡한 질문")

        # 검증
        assert result.success is True
        assert result.steps_taken == 2
        assert mock_planner.plan.call_count == 2
        assert mock_executor.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_orchestrator_respects_max_iterations(
        self,
        orchestrator: AgentOrchestrator,
        mock_planner: AsyncMock,
        mock_executor: AsyncMock,
        mock_synthesizer: AsyncMock,
    ) -> None:
        """
        최대 반복 횟수 제한 테스트

        should_continue가 계속 True여도 max_iterations에서 멈춰야 합니다.
        """
        # max_iterations를 3으로 설정
        orchestrator._config.max_iterations = 3

        # 항상 계속하도록 설정
        mock_planner.plan.return_value = (
            [ToolCall(tool_name="search_weaviate", arguments={"query": "q"})],
            "계속 검색합니다",
            True,  # 항상 계속
        )

        mock_executor.execute.return_value = [
            ToolResult(
                call_id="test",
                tool_name="search_weaviate",
                success=True,
                data={"documents": []},
            )
        ]

        mock_synthesizer.synthesize.return_value = (
            "반복 결과입니다.",
            [],
        )

        # 실행
        result = await orchestrator.run("무한 루프 테스트")

        # 검증: max_iterations(3)에서 멈춰야 함
        assert result.steps_taken == 3
        assert mock_planner.plan.call_count == 3
        assert mock_executor.execute.call_count == 3

    @pytest.mark.asyncio
    async def test_orchestrator_completes_when_done(
        self,
        orchestrator: AgentOrchestrator,
        mock_planner: AsyncMock,
        mock_synthesizer: AsyncMock,
    ) -> None:
        """
        완료 조건 테스트 (도구 없이 직접 답변)

        도구 호출 없이 직접 답변 가능한 경우를 검증합니다.
        """
        # 도구 없이 바로 종료
        mock_planner.plan.return_value = (
            [],  # 도구 호출 없음
            "간단한 인사말이므로 직접 답변합니다",
            False,  # 종료
        )

        mock_synthesizer.synthesize.return_value = (
            "안녕하세요! 무엇을 도와드릴까요?",
            [],
        )

        # 실행
        result = await orchestrator.run("안녕하세요")

        # 검증
        assert result.success is True
        assert result.answer == "안녕하세요! 무엇을 도와드릴까요?"
        assert result.steps_taken == 1
        assert len(result.tools_used) == 0

    @pytest.mark.asyncio
    async def test_orchestrator_handles_errors(
        self,
        orchestrator: AgentOrchestrator,
        mock_planner: AsyncMock,
        mock_executor: AsyncMock,
        mock_synthesizer: AsyncMock,
    ) -> None:
        """
        에러 처리 테스트

        예외 발생 시 실패 결과를 반환해야 합니다.
        """
        # Planner에서 예외 발생
        mock_planner.plan.side_effect = Exception("LLM 호출 실패")

        # 실행
        result = await orchestrator.run("에러 테스트")

        # 검증
        assert result.success is False
        assert result.error is not None
        assert "LLM 호출 실패" in result.error or "오류" in result.answer

    @pytest.mark.asyncio
    async def test_orchestrator_returns_agent_result(
        self,
        orchestrator: AgentOrchestrator,
        mock_planner: AsyncMock,
        mock_executor: AsyncMock,
        mock_synthesizer: AsyncMock,
    ) -> None:
        """
        AgentResult 반환 형식 테스트

        모든 필드가 올바르게 설정되어야 합니다.
        """
        tool_call = ToolCall(
            tool_name="search_weaviate",
            arguments={"query": "테스트"},
        )

        mock_planner.plan.return_value = (
            [tool_call],
            "검색 수행",
            False,
        )

        mock_executor.execute.return_value = [
            ToolResult(
                call_id=tool_call.call_id,
                tool_name="search_weaviate",
                success=True,
                data={"documents": [{"content": "내용"}]},
            )
        ]

        mock_synthesizer.synthesize.return_value = (
            "답변입니다.",
            [{"source": "test.md"}],
        )

        # 실행
        result = await orchestrator.run("테스트")

        # AgentResult 타입 검증
        assert isinstance(result, AgentResult)

        # 필수 필드 검증
        assert hasattr(result, "success")
        assert hasattr(result, "answer")
        assert hasattr(result, "sources")
        assert hasattr(result, "steps_taken")
        assert hasattr(result, "total_time")
        assert hasattr(result, "tools_used")

        # 값 검증
        assert isinstance(result.success, bool)
        assert isinstance(result.answer, str)
        assert isinstance(result.sources, list)
        assert isinstance(result.steps_taken, int)
        assert isinstance(result.total_time, float)
        assert isinstance(result.tools_used, list)
        assert result.total_time >= 0

    @pytest.mark.asyncio
    async def test_orchestrator_with_tool_failure(
        self,
        orchestrator: AgentOrchestrator,
        mock_planner: AsyncMock,
        mock_executor: AsyncMock,
        mock_synthesizer: AsyncMock,
    ) -> None:
        """
        도구 실패 처리 테스트

        도구 실행이 실패해도 답변은 생성되어야 합니다.
        """
        tool_call = ToolCall(
            tool_name="search_weaviate",
            arguments={"query": "테스트"},
        )

        mock_planner.plan.return_value = (
            [tool_call],
            "검색 시도",
            False,
        )

        # 도구 실행 실패
        mock_executor.execute.return_value = [
            ToolResult(
                call_id=tool_call.call_id,
                tool_name="search_weaviate",
                success=False,
                error="타임아웃 발생",
            )
        ]

        mock_synthesizer.synthesize.return_value = (
            "검색에 실패했습니다. 다시 시도해주세요.",
            [],
        )

        # 실행
        result = await orchestrator.run("테스트")

        # 검증: 도구 실패해도 답변은 생성
        assert result.success is True  # 전체 프로세스는 성공
        assert result.answer is not None
        assert len(result.answer) > 0

    @pytest.mark.asyncio
    async def test_orchestrator_tracks_tools_used(
        self,
        orchestrator: AgentOrchestrator,
        mock_planner: AsyncMock,
        mock_executor: AsyncMock,
        mock_synthesizer: AsyncMock,
    ) -> None:
        """
        사용된 도구 추적 테스트

        여러 스텝에서 사용된 모든 도구가 기록되어야 합니다.
        """
        tool1 = ToolCall(tool_name="search_weaviate", arguments={})
        tool2 = ToolCall(tool_name="query_sql", arguments={})

        mock_planner.plan.side_effect = [
            ([tool1], "검색", True),
            ([tool2], "SQL", False),
        ]

        mock_executor.execute.side_effect = [
            [ToolResult(call_id=tool1.call_id, tool_name="search_weaviate", success=True, data={})],
            [ToolResult(call_id=tool2.call_id, tool_name="query_sql", success=True, data={})],
        ]

        mock_synthesizer.synthesize.return_value = ("답변", [])

        # 실행
        result = await orchestrator.run("테스트")

        # 검증: 두 도구 모두 기록
        assert "search_weaviate" in result.tools_used
        assert "query_sql" in result.tools_used

    @pytest.mark.asyncio
    async def test_orchestrator_with_session_context(
        self,
        orchestrator: AgentOrchestrator,
        mock_planner: AsyncMock,
        mock_executor: AsyncMock,
        mock_synthesizer: AsyncMock,
    ) -> None:
        """
        세션 컨텍스트 전달 테스트

        session_context 파라미터가 올바르게 처리되어야 합니다.
        """
        mock_planner.plan.return_value = (
            [],
            "이전 대화 참조",
            False,
        )

        mock_synthesizer.synthesize.return_value = (
            "이전 대화를 참조한 답변입니다.",
            [],
        )

        # 세션 컨텍스트와 함께 실행
        result = await orchestrator.run(
            query="이전에 말한 내용 뭐였지?",
            session_context="이전 대화: 파이썬에 대해 이야기했습니다.",
        )

        # 검증
        assert result.success is True
        # Planner가 호출될 때 state에 컨텍스트가 포함되었는지는
        # AgentState의 get_context_for_llm에서 처리됨


class TestOrchestratorMessageExternalization:
    """Orchestrator 사용자노출 메시지/내부 컨텍스트 대체어 외부화 회귀/오버라이드 테스트.

    (a) config 미설정 시 코드 내장 한국어 기본값 사용 (회귀 0)
    (b) config 오버라이드 시 코드 변경 없이 메시지가 바뀜 (데드 키 아님)
    """

    @pytest.fixture
    def mock_planner(self) -> AsyncMock:
        planner = AsyncMock()
        planner.plan = AsyncMock()
        return planner

    @pytest.fixture
    def mock_executor(self) -> AsyncMock:
        executor = AsyncMock()
        executor.execute = AsyncMock()
        return executor

    @pytest.fixture
    def mock_synthesizer(self) -> AsyncMock:
        synthesizer = AsyncMock()
        synthesizer.synthesize = AsyncMock()
        return synthesizer

    def _orchestrator(
        self,
        planner: AsyncMock,
        executor: AsyncMock,
        synthesizer: AsyncMock,
        config: AgentConfig,
    ) -> AgentOrchestrator:
        return AgentOrchestrator(
            planner=planner,
            executor=executor,
            synthesizer=synthesizer,
            config=config,
        )

    @pytest.mark.asyncio
    async def test_default_error_message_is_builtin_korean(
        self,
        mock_planner: AsyncMock,
        mock_executor: AsyncMock,
        mock_synthesizer: AsyncMock,
    ) -> None:
        """(a) 미설정 시 최상위 예외 답변 = 코드 내장 한국어 기본값"""
        from app.modules.core.agent.orchestrator import ORCHESTRATOR_ERROR_MESSAGE

        orch = self._orchestrator(
            mock_planner, mock_executor, mock_synthesizer, AgentConfig()
        )
        # Planner가 예외를 던지게 해서 최상위 catch 경로를 탄다
        mock_planner.plan.side_effect = RuntimeError("boom")

        result = await orch.run("질문")
        assert result.success is False
        assert result.answer == ORCHESTRATOR_ERROR_MESSAGE
        assert result.answer == "죄송합니다. 처리 중 오류가 발생했습니다."

    @pytest.mark.asyncio
    async def test_override_error_message(
        self,
        mock_planner: AsyncMock,
        mock_executor: AsyncMock,
        mock_synthesizer: AsyncMock,
    ) -> None:
        """(b) config 오버라이드 시 최상위 예외 답변이 교체됨"""
        config = AgentConfig(orchestrator_error_message="Sorry, an error occurred.")
        orch = self._orchestrator(
            mock_planner, mock_executor, mock_synthesizer, config
        )
        mock_planner.plan.side_effect = RuntimeError("boom")

        result = await orch.run("query")
        assert result.success is False
        assert result.answer == "Sorry, an error occurred."

    def test_default_empty_context_is_builtin_korean(
        self,
        mock_planner: AsyncMock,
        mock_executor: AsyncMock,
        mock_synthesizer: AsyncMock,
    ) -> None:
        """(a) 미설정 시 빈 컨텍스트 대체어 = 코드 내장 한국어 기본값"""
        from app.modules.core.agent.interfaces import AgentState
        from app.modules.core.agent.orchestrator import ORCHESTRATOR_EMPTY_CONTEXT

        orch = self._orchestrator(
            mock_planner, mock_executor, mock_synthesizer, AgentConfig()
        )
        # 스텝 없음 → 도구 결과 없음 → 대체어 반환
        ctx = orch._extract_context_for_reflection(AgentState(original_query="q"))
        assert ctx == ORCHESTRATOR_EMPTY_CONTEXT
        assert ctx == "검색 결과 없음"

    def test_override_empty_context(
        self,
        mock_planner: AsyncMock,
        mock_executor: AsyncMock,
        mock_synthesizer: AsyncMock,
    ) -> None:
        """(b) config 오버라이드 시 빈 컨텍스트 대체어가 교체됨"""
        from app.modules.core.agent.interfaces import AgentState

        config = AgentConfig(orchestrator_empty_context="(no results)")
        orch = self._orchestrator(
            mock_planner, mock_executor, mock_synthesizer, config
        )
        ctx = orch._extract_context_for_reflection(AgentState(original_query="q"))
        assert ctx == "(no results)"
