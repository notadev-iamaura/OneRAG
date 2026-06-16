"""
에이전트 프롬프트 외부화 회귀/오버라이드 테스트

코드에 하드코딩됐던 planner/synthesizer/reflector 프롬프트를 config(AgentConfig)로
외부화한 것이 다음을 만족하는지 검증한다:

(a) config 미설정 시 LLM에 전달되는 프롬프트 = 코드 내장 한국어 기본값 (회귀 0)
(b) config 오버라이드 시 코드 변경 없이 프롬프트가 실제로 바뀜
(c) 변수 치환({output_language}/{tool_schemas}/{query} 등) 보존

검증 방식: Mock LLM 클라이언트의 generate_text 호출 인자(system_prompt/prompt)를
직접 단언하여 "프롬프트가 LLM 호출에 전달된 내용"을 확인한다.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.core.agent.interfaces import AgentConfig, AgentState
from app.modules.core.agent.planner import (
    PLANNER_SYSTEM_PROMPT_TEMPLATE,
    PLANNER_USER_PROMPT,
    AgentPlanner,
)
from app.modules.core.agent.reflector import (
    REFLECTOR_SYSTEM_PROMPT_TEMPLATE,
    AgentReflector,
)
from app.modules.core.agent.synthesizer import (
    SYNTHESIZER_ERROR_MESSAGE,
    SYNTHESIZER_SYSTEM_PROMPT_TEMPLATE,
    AgentSynthesizer,
)


@pytest.fixture
def mock_llm_client() -> AsyncMock:
    """generate_text를 가진 Mock LLM 클라이언트"""
    client = AsyncMock()
    client.generate_text = AsyncMock(return_value='{"reasoning": "x", "tool_calls": [], "should_continue": false}')
    return client


@pytest.fixture
def mock_mcp_server() -> MagicMock:
    """빈 도구 스키마를 반환하는 Mock MCP 서버"""
    server = MagicMock()
    server.get_tool_schemas = MagicMock(return_value=[])
    return server


class TestPlannerPromptExternalization:
    """Planner 프롬프트 외부화"""

    @pytest.mark.asyncio
    async def test_default_uses_builtin_korean_prompt(
        self, mock_llm_client: AsyncMock, mock_mcp_server: MagicMock
    ) -> None:
        """(a) 미설정 시 코드 내장 한국어 프롬프트 사용 (회귀 0)"""
        planner = AgentPlanner(
            llm_client=mock_llm_client,
            mcp_server=mock_mcp_server,
            config=AgentConfig(),  # 프롬프트 오버라이드 없음
        )
        # 미설정 시 시스템 프롬프트 템플릿 = 내장 템플릿에 output_language만 치환된 것
        expected = PLANNER_SYSTEM_PROMPT_TEMPLATE.replace("{output_language}", "한국어")
        assert planner._system_prompt_template == expected
        assert planner._user_prompt_template == PLANNER_USER_PROMPT

        await planner.plan(AgentState(original_query="테스트"))
        system_prompt = mock_llm_client.generate_text.call_args.kwargs["system_prompt"]
        # 내장 프롬프트의 한국어 가이드라인이 그대로 LLM에 전달됨
        assert "도구 선택 에이전트" in system_prompt
        assert "도구별 사용 가이드라인" in system_prompt

    @pytest.mark.asyncio
    async def test_override_changes_prompt_without_code_change(
        self, mock_llm_client: AsyncMock, mock_mcp_server: MagicMock
    ) -> None:
        """(b) 오버라이드 시 코드 변경 없이 프롬프트가 바뀜 + (c) 변수 치환 보존"""
        custom_system = (
            "You are a tool-selection agent. Tools:\n{tool_schemas}\n"
            "Reasoning language: {output_language}."
        )
        custom_user = "Question: {query}\nContext: {context}\nDecide."
        config = AgentConfig(
            output_language="English",
            planner_system_prompt=custom_system,
            planner_user_prompt=custom_user,
        )
        planner = AgentPlanner(
            llm_client=mock_llm_client, mcp_server=mock_mcp_server, config=config
        )

        await planner.plan(AgentState(original_query="hello"))
        kwargs = mock_llm_client.generate_text.call_args.kwargs
        system_prompt = kwargs["system_prompt"]
        user_prompt = kwargs["prompt"]

        # 한국어 내장 문구가 사라지고 영어 커스텀 프롬프트가 전달됨
        assert "You are a tool-selection agent" in system_prompt
        assert "도구 선택 에이전트" not in system_prompt
        # (c) 변수 치환 보존: {output_language}→English, {tool_schemas} 치환 완료
        assert "Reasoning language: English." in system_prompt
        assert "{tool_schemas}" not in system_prompt
        # 사용자 프롬프트 변수 치환 보존
        assert "Question: hello" in user_prompt


class TestSynthesizerPromptExternalization:
    """Synthesizer 프롬프트 외부화"""

    @pytest.mark.asyncio
    async def test_default_uses_builtin_korean_prompt(
        self, mock_llm_client: AsyncMock
    ) -> None:
        """(a) 미설정 시 코드 내장 한국어 프롬프트 사용"""
        mock_llm_client.generate_text.return_value = "답변"
        synth = AgentSynthesizer(llm_client=mock_llm_client, config=AgentConfig())
        expected = SYNTHESIZER_SYSTEM_PROMPT_TEMPLATE.replace("{output_language}", "한국어")
        assert synth._system_prompt == expected
        assert synth._error_message == SYNTHESIZER_ERROR_MESSAGE

        await synth.synthesize(AgentState(original_query="질문"))
        kwargs = mock_llm_client.generate_text.call_args.kwargs
        assert "답변 생성 에이전트" in kwargs["system_prompt"]

    @pytest.mark.asyncio
    async def test_override_changes_prompt_and_error_message(
        self, mock_llm_client: AsyncMock
    ) -> None:
        """(b)(c) 오버라이드 시 시스템/사용자 프롬프트 + 에러 메시지 교체"""
        config = AgentConfig(
            output_language="English",
            synthesizer_system_prompt="Answer agent. Language: {output_language}.",
            synthesizer_user_prompt="Q: {query}\nResults: {tool_results}",
            synthesizer_error_message="Sorry, an error occurred.",
        )
        mock_llm_client.generate_text.return_value = "answer"
        synth = AgentSynthesizer(llm_client=mock_llm_client, config=config)

        await synth.synthesize(AgentState(original_query="hi"))
        kwargs = mock_llm_client.generate_text.call_args.kwargs
        assert kwargs["system_prompt"] == "Answer agent. Language: English."
        assert "Q: hi" in kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_override_error_message_returned_on_failure(
        self, mock_llm_client: AsyncMock
    ) -> None:
        """에러 폴백 메시지가 오버라이드 값으로 반환됨"""
        config = AgentConfig(synthesizer_error_message="Custom error.")
        mock_llm_client.generate_text.side_effect = Exception("boom")
        synth = AgentSynthesizer(llm_client=mock_llm_client, config=config)

        answer, sources = await synth.synthesize(AgentState(original_query="x"))
        assert answer == "Custom error."
        assert sources == []


class TestReflectorPromptExternalization:
    """Reflector 프롬프트 외부화"""

    @pytest.mark.asyncio
    async def test_default_uses_builtin_korean_prompt(
        self, mock_llm_client: AsyncMock
    ) -> None:
        """(a) 미설정 시 코드 내장 한국어 프롬프트 + 빈 컨텍스트 기본값"""
        mock_llm_client.generate_text.return_value = '{"score": 8.0}'
        reflector = AgentReflector(llm_client=mock_llm_client, config=AgentConfig())
        expected = REFLECTOR_SYSTEM_PROMPT_TEMPLATE.replace("{output_language}", "한국어")
        assert reflector._system_prompt == expected

        # context를 빈 문자열로 전달 → 내장 "컨텍스트 없음" 대체어가 프롬프트에 들어감
        await reflector.reflect(query="질문", answer="답변", context="")
        user_prompt = mock_llm_client.generate_text.call_args.kwargs["prompt"]
        assert "컨텍스트 없음" in user_prompt

    @pytest.mark.asyncio
    async def test_override_changes_prompt_and_empty_context(
        self, mock_llm_client: AsyncMock
    ) -> None:
        """(b)(c) 오버라이드 시 시스템/사용자 프롬프트 + 빈 컨텍스트 대체어 교체"""
        config = AgentConfig(
            output_language="English",
            reflector_system_prompt="Evaluator. Language: {output_language}.",
            reflector_user_prompt="Q:{query} A:{answer} C:{context}",
            reflector_empty_context="No context",
        )
        mock_llm_client.generate_text.return_value = '{"score": 9.0}'
        reflector = AgentReflector(llm_client=mock_llm_client, config=config)
        assert reflector._system_prompt == "Evaluator. Language: English."

        await reflector.reflect(query="q", answer="a", context="")
        user_prompt = mock_llm_client.generate_text.call_args.kwargs["prompt"]
        assert "Q:q A:a C:No context" in user_prompt
        assert "컨텍스트 없음" not in user_prompt


class TestAgentFactoryPromptWiring:
    """AgentFactory가 mcp.agent.prompts.* 를 AgentConfig로 매핑하는지"""

    def test_factory_default_has_none_prompts(self) -> None:
        """(a) prompts 섹션 없으면 모든 오버라이드 필드 None (회귀 0)"""
        from app.modules.core.agent.factory import AgentFactory

        cfg = AgentFactory.create_config({"mcp": {"agent": {}}})
        assert cfg.planner_system_prompt is None
        assert cfg.synthesizer_error_message is None
        assert cfg.reflector_empty_context is None

    def test_factory_reads_prompts_section(self) -> None:
        """(b) mcp.agent.prompts.* 가 AgentConfig 필드로 전달됨 (데드 키 아님)"""
        from app.modules.core.agent.factory import AgentFactory

        cfg = AgentFactory.create_config(
            {
                "mcp": {
                    "agent": {
                        "prompts": {
                            "planner_system": "P-SYS",
                            "synthesizer_error_message": "ERR",
                            "reflector_empty_context": "NOCTX",
                        }
                    }
                }
            }
        )
        assert cfg.planner_system_prompt == "P-SYS"
        assert cfg.synthesizer_error_message == "ERR"
        assert cfg.reflector_empty_context == "NOCTX"
