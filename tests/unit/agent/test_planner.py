"""
AgentPlanner 테스트 - LLM 기반 도구 선택

ReAct 패턴에서 "Reasoning" 담당 컴포넌트.
현재 상태(AgentState)를 분석하여 다음에 사용할 도구를 결정합니다.

테스트 케이스:
- 기본 도구 선택 동작
- 컨텍스트 활용
- 도구 불필요 케이스
- 스키마 준수
- 에러 처리 및 폴백
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.core.agent.interfaces import (
    AgentConfig,
    AgentState,
    AgentStep,
    ToolCall,
    ToolResult,
)
from app.modules.core.agent.planner import (
    PLANNER_SYSTEM_PROMPT_TEMPLATE,
    AgentPlanner,
)


class TestAgentPlanner:
    """AgentPlanner 테스트"""

    @pytest.fixture
    def mock_llm_client(self) -> AsyncMock:
        """Mock LLM 클라이언트"""
        client = AsyncMock()
        # generate_text 메서드를 Mock으로 설정
        client.generate_text = AsyncMock()
        return client

    @pytest.fixture
    def mock_mcp_server(self) -> MagicMock:
        """Mock MCP 서버"""
        server = MagicMock()
        # 도구 스키마 반환 설정
        server.get_tool_schemas = MagicMock(
            return_value=[
                {
                    "type": "function",
                    "function": {
                        "name": "search_weaviate",
                        "description": "벡터 DB에서 문서 검색",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "검색 쿼리"},
                                "top_k": {
                                    "type": "integer",
                                    "description": "반환할 결과 수",
                                    "default": 10,
                                },
                            },
                            "required": ["query"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "query_sql",
                        "description": "SQL로 메타데이터 검색",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "question": {
                                    "type": "string",
                                    "description": "자연어 질문",
                                },
                            },
                            "required": ["question"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "get_document_by_id",
                        "description": "ID로 특정 문서 조회",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "document_id": {
                                    "type": "string",
                                    "description": "문서 UUID",
                                },
                            },
                            "required": ["document_id"],
                        },
                    },
                },
            ]
        )
        return server

    @pytest.fixture
    def agent_config(self) -> AgentConfig:
        """에이전트 설정"""
        return AgentConfig(
            tool_selection="llm",
            selector_model="google/gemini-2.5-flash-lite",
            max_iterations=5,
            fallback_tool="search_weaviate",
        )

    @pytest.fixture
    def planner(
        self,
        mock_llm_client: AsyncMock,
        mock_mcp_server: MagicMock,
        agent_config: AgentConfig,
    ) -> AgentPlanner:
        """AgentPlanner 인스턴스"""
        return AgentPlanner(
            llm_client=mock_llm_client,
            mcp_server=mock_mcp_server,
            config=agent_config,
        )

    @pytest.mark.asyncio
    async def test_planner_returns_tool_calls(
        self,
        planner: AgentPlanner,
        mock_llm_client: AsyncMock,
    ) -> None:
        """기본 도구 선택 테스트 - 정상적인 LLM 응답에서 도구 호출 추출"""
        # LLM 응답 설정 (JSON 형식)
        mock_llm_client.generate_text.return_value = """
        {
            "reasoning": "사용자가 파이썬 튜토리얼을 검색하려고 합니다",
            "tool_calls": [
                {
                    "tool_name": "search_weaviate",
                    "arguments": {"query": "파이썬 튜토리얼", "top_k": 5}
                }
            ],
            "should_continue": true
        }
        """

        state = AgentState(original_query="파이썬 튜토리얼 찾아줘")

        tool_calls, reasoning, should_continue = await planner.plan(state)

        # 검증
        assert len(tool_calls) == 1
        assert tool_calls[0].tool_name == "search_weaviate"
        assert tool_calls[0].arguments["query"] == "파이썬 튜토리얼"
        assert tool_calls[0].arguments["top_k"] == 5
        assert "검색" in reasoning or "파이썬" in reasoning
        assert should_continue is True

    @pytest.mark.asyncio
    async def test_planner_handles_no_tools_needed(
        self,
        planner: AgentPlanner,
        mock_llm_client: AsyncMock,
    ) -> None:
        """도구 없이 직접 답변 가능한 케이스"""
        mock_llm_client.generate_text.return_value = """
        {
            "reasoning": "간단한 인사말이므로 도구가 필요 없습니다",
            "tool_calls": [],
            "should_continue": false,
            "direct_answer": "안녕하세요! 무엇을 도와드릴까요?"
        }
        """

        state = AgentState(original_query="안녕하세요")

        tool_calls, reasoning, should_continue = await planner.plan(state)

        # 검증
        assert len(tool_calls) == 0
        assert should_continue is False
        assert "인사" in reasoning or "도구" in reasoning

    @pytest.mark.asyncio
    async def test_planner_selects_multiple_tools(
        self,
        planner: AgentPlanner,
        mock_llm_client: AsyncMock,
    ) -> None:
        """복수 도구 선택 테스트"""
        mock_llm_client.generate_text.return_value = """
        {
            "reasoning": "문서 검색과 메타데이터 조회가 모두 필요합니다",
            "tool_calls": [
                {"tool_name": "search_weaviate", "arguments": {"query": "2024년 매출"}},
                {"tool_name": "query_sql", "arguments": {"question": "2024년 총 매출액은?"}}
            ],
            "should_continue": true
        }
        """

        state = AgentState(original_query="2024년 매출 정보와 성장률 알려줘")

        tool_calls, reasoning, should_continue = await planner.plan(state)

        # 검증
        assert len(tool_calls) == 2
        assert tool_calls[0].tool_name == "search_weaviate"
        assert tool_calls[1].tool_name == "query_sql"

    @pytest.mark.asyncio
    async def test_planner_uses_previous_context(
        self,
        planner: AgentPlanner,
        mock_llm_client: AsyncMock,
    ) -> None:
        """이전 스텝 컨텍스트 포함 테스트"""
        mock_llm_client.generate_text.return_value = """
        {
            "reasoning": "이전 검색 결과에서 발견한 문서를 상세 조회합니다",
            "tool_calls": [
                {"tool_name": "get_document_by_id", "arguments": {"document_id": "abc-123"}}
            ],
            "should_continue": true
        }
        """

        # 이전 스텝이 있는 상태 생성
        state = AgentState(original_query="문서 자세히 보여줘")
        previous_tool_call = ToolCall(
            tool_name="search_weaviate",
            arguments={"query": "테스트"},
        )
        previous_result = ToolResult(
            call_id=previous_tool_call.call_id,
            tool_name="search_weaviate",
            success=True,
            data={"documents": [{"id": "abc-123", "content": "테스트 문서"}]},
        )
        state.steps.append(
            AgentStep(
                step_number=1,
                reasoning="검색 수행",
                tool_calls=[previous_tool_call],
                tool_results=[previous_result],
            )
        )

        tool_calls, reasoning, should_continue = await planner.plan(state)

        # LLM 호출 시 이전 컨텍스트가 포함되었는지 확인
        call_args = mock_llm_client.generate_text.call_args
        # call_args[1]은 kwargs, call_args[0]은 positional args
        # prompt 파라미터에 이전 스텝 정보가 포함되어야 함
        prompt_text = call_args.kwargs.get("prompt", "") or str(call_args)
        assert "Step 1" in prompt_text or "search_weaviate" in prompt_text

    @pytest.mark.asyncio
    async def test_planner_fallback_on_json_parse_error(
        self,
        planner: AgentPlanner,
        mock_llm_client: AsyncMock,
        agent_config: AgentConfig,
    ) -> None:
        """JSON 파싱 에러 시 폴백 도구 사용"""
        mock_llm_client.generate_text.return_value = "유효하지 않은 JSON 응답입니다"

        state = AgentState(original_query="검색해줘")

        tool_calls, reasoning, should_continue = await planner.plan(state)

        # 폴백 도구 (search_weaviate) 사용
        assert len(tool_calls) == 1
        assert tool_calls[0].tool_name == agent_config.fallback_tool
        assert "폴백" in reasoning or "fallback" in reasoning.lower()

    @pytest.mark.asyncio
    async def test_planner_fallback_on_llm_exception(
        self,
        planner: AgentPlanner,
        mock_llm_client: AsyncMock,
        agent_config: AgentConfig,
    ) -> None:
        """LLM 호출 예외 시 폴백 도구 사용"""
        mock_llm_client.generate_text.side_effect = Exception("LLM 서비스 연결 실패")

        state = AgentState(original_query="검색해줘")

        tool_calls, reasoning, should_continue = await planner.plan(state)

        # 폴백 도구 사용
        assert len(tool_calls) == 1
        assert tool_calls[0].tool_name == agent_config.fallback_tool

    @pytest.mark.asyncio
    async def test_planner_respects_tool_schemas(
        self,
        planner: AgentPlanner,
        mock_mcp_server: MagicMock,
        mock_llm_client: AsyncMock,
    ) -> None:
        """도구 스키마가 LLM 프롬프트에 포함되는지 확인"""
        mock_llm_client.generate_text.return_value = """
        {
            "reasoning": "검색 수행",
            "tool_calls": [{"tool_name": "search_weaviate", "arguments": {"query": "test"}}],
            "should_continue": false
        }
        """

        state = AgentState(original_query="테스트")

        await planner.plan(state)

        # MCP 서버에서 스키마를 조회했는지 확인
        mock_mcp_server.get_tool_schemas.assert_called_once()

        # LLM 호출 시 스키마가 프롬프트에 포함되었는지 확인
        call_args = mock_llm_client.generate_text.call_args
        prompt_text = str(call_args)
        assert "search_weaviate" in prompt_text

    @pytest.mark.asyncio
    async def test_planner_handles_markdown_json_response(
        self,
        planner: AgentPlanner,
        mock_llm_client: AsyncMock,
    ) -> None:
        """마크다운 코드 블록으로 감싸진 JSON 응답 처리"""
        mock_llm_client.generate_text.return_value = """```json
        {
            "reasoning": "검색이 필요합니다",
            "tool_calls": [
                {"tool_name": "search_weaviate", "arguments": {"query": "테스트"}}
            ],
            "should_continue": true
        }
        ```"""

        state = AgentState(original_query="테스트 검색")

        tool_calls, reasoning, should_continue = await planner.plan(state)

        # 마크다운 코드 블록이 정상적으로 파싱되어야 함
        assert len(tool_calls) == 1
        assert tool_calls[0].tool_name == "search_weaviate"

    @pytest.mark.asyncio
    async def test_planner_generates_unique_call_ids(
        self,
        planner: AgentPlanner,
        mock_llm_client: AsyncMock,
    ) -> None:
        """각 도구 호출에 고유한 call_id가 생성되는지 확인"""
        mock_llm_client.generate_text.return_value = """
        {
            "reasoning": "여러 도구 호출",
            "tool_calls": [
                {"tool_name": "search_weaviate", "arguments": {"query": "a"}},
                {"tool_name": "query_sql", "arguments": {"question": "b"}}
            ],
            "should_continue": true
        }
        """

        state = AgentState(original_query="테스트")

        tool_calls, _, _ = await planner.plan(state)

        # 각 도구 호출에 고유한 call_id가 있어야 함
        assert len(tool_calls) == 2
        assert tool_calls[0].call_id != tool_calls[1].call_id
        assert tool_calls[0].call_id is not None
        assert tool_calls[1].call_id is not None


class TestAgentPlannerEdgeCases:
    """AgentPlanner 엣지 케이스 테스트"""

    @pytest.fixture
    def mock_llm_client(self) -> AsyncMock:
        """Mock LLM 클라이언트"""
        client = AsyncMock()
        client.generate_text = AsyncMock()
        return client

    @pytest.fixture
    def mock_mcp_server(self) -> MagicMock:
        """Mock MCP 서버"""
        server = MagicMock()
        server.get_tool_schemas = MagicMock(return_value=[])
        return server

    @pytest.fixture
    def planner(
        self,
        mock_llm_client: AsyncMock,
        mock_mcp_server: MagicMock,
    ) -> AgentPlanner:
        """AgentPlanner 인스턴스"""
        config = AgentConfig(fallback_tool="search_weaviate")
        return AgentPlanner(
            llm_client=mock_llm_client,
            mcp_server=mock_mcp_server,
            config=config,
        )

    @pytest.mark.asyncio
    async def test_empty_tool_calls_in_response(
        self,
        planner: AgentPlanner,
        mock_llm_client: AsyncMock,
    ) -> None:
        """tool_calls가 빈 배열일 때 정상 처리"""
        mock_llm_client.generate_text.return_value = """
        {
            "reasoning": "추가 도구 필요 없음",
            "tool_calls": [],
            "should_continue": false
        }
        """

        state = AgentState(original_query="완료되었나요?")

        tool_calls, reasoning, should_continue = await planner.plan(state)

        assert len(tool_calls) == 0
        assert should_continue is False

    @pytest.mark.asyncio
    async def test_missing_should_continue_defaults_to_true(
        self,
        planner: AgentPlanner,
        mock_llm_client: AsyncMock,
    ) -> None:
        """should_continue 필드 누락 시 기본값 True"""
        mock_llm_client.generate_text.return_value = """
        {
            "reasoning": "검색 수행",
            "tool_calls": [{"tool_name": "search_weaviate", "arguments": {"query": "test"}}]
        }
        """

        state = AgentState(original_query="테스트")

        tool_calls, reasoning, should_continue = await planner.plan(state)

        assert len(tool_calls) == 1
        assert should_continue is True  # 기본값

    @pytest.mark.asyncio
    async def test_incomplete_tool_call_skipped(
        self,
        planner: AgentPlanner,
        mock_llm_client: AsyncMock,
    ) -> None:
        """불완전한 도구 호출은 건너뜀"""
        mock_llm_client.generate_text.return_value = """
        {
            "reasoning": "일부 도구 정보 누락",
            "tool_calls": [
                {"tool_name": "search_weaviate", "arguments": {"query": "valid"}},
                {"arguments": {"query": "missing tool_name"}},
                {"tool_name": "query_sql"}
            ],
            "should_continue": true
        }
        """

        state = AgentState(original_query="테스트")

        tool_calls, reasoning, should_continue = await planner.plan(state)

        # 유효한 도구 호출만 반환 (tool_name 있는 것만)
        # 두 번째는 tool_name 없음, 세 번째는 arguments 없음 (빈 dict로 처리 가능)
        assert len(tool_calls) >= 1
        assert tool_calls[0].tool_name == "search_weaviate"


class TestPlannerPromptDomainNeutrality:
    """Planner 코드 기본 시스템 프롬프트의 도메인/로케일 중립성 검증.

    few-shot 예시가 한국 특정 지명·도메인(강남/맛집/노트북/매출 등)을 누출하지 않고
    도메인 중립 플레이스홀더(<주제>/<지역> 등)만 사용하는지 단언한다.
    """

    def test_no_specific_place_names_or_domains(self) -> None:
        """특정 지명·도메인 예시 부재 단언"""
        # 한국 특정 지명/도메인 누출 토큰이 코드 기본 템플릿에 없어야 한다.
        leaking_tokens = ["강남", "맛집", "노트북", "매출", "협력사", "파트너사"]
        for token in leaking_tokens:
            assert token not in PLANNER_SYSTEM_PROMPT_TEMPLATE, (
                f"도메인/로케일 누출 토큰 발견: {token}"
            )

    def test_uses_neutral_placeholders(self) -> None:
        """도메인 중립 플레이스홀더 사용 단언(예시가 일반화됨)"""
        # 일반화된 예시는 꺾쇠 플레이스홀더(<주제>/<지역> 등)를 사용한다.
        assert "<주제>" in PLANNER_SYSTEM_PROMPT_TEMPLATE
        assert "<지역>" in PLANNER_SYSTEM_PROMPT_TEMPLATE
