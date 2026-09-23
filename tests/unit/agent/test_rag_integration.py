"""
RAG Pipeline + Agent Orchestrator 통합 테스트

Task 7: RAG Pipeline에 Agent 모드 통합 테스트
- use_agent=True일 때 AgentOrchestrator 사용
- use_agent=False일 때 기존 7단계 파이프라인 사용
- Agent 비활성화 시 폴백 동작 확인

작성일: 2026-01-01
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestRAGPipelineAgentIntegration:
    """RAG Pipeline + Agent 통합 테스트"""

    @pytest.fixture
    def mock_config(self) -> dict[str, Any]:
        """테스트용 설정"""
        return {
            "mcp": {
                "enabled": True,
                "server_name": "test-server",
                "tools": {
                    "search_vector_db": {"enabled": True},
                    "query_sql": {"enabled": True},
                },
                "agent": {
                    "tool_selection": "llm",
                    "max_tool_calls": 5,
                    "fallback_tool": "search_vector_db",
                },
            },
            "rag": {
                "top_k": 10,
                "rerank_top_k": 5,
            },
            "retrieval": {
                "min_score": 0.05,
            },
            "reranking": {
                "enabled": False,
            },
            "self_rag": {
                "enabled": False,
            },
            "privacy": {
                "enabled": False,
            },
            "generation": {
                "default_provider": "openrouter",
                "temperature": 0.2,
            },
        }

    @pytest.fixture
    def mock_agent_orchestrator(self) -> AsyncMock:
        """Mock AgentOrchestrator"""
        from app.modules.core.agent.interfaces import AgentResult

        orchestrator = AsyncMock()
        orchestrator.run = AsyncMock(
            return_value=AgentResult(
                success=True,
                answer="Agent 모드 답변입니다.",
                sources=[{"source": "agent_doc.md", "title": "Agent 문서"}],
                steps_taken=2,
                total_time=1.5,
                tools_used=["search_vector_db"],
            )
        )
        return orchestrator

    @pytest.fixture
    def mock_modules(self) -> dict[str, Any]:
        """Mock 모듈들"""
        # query_router Mock
        query_router = MagicMock()
        query_router.enabled = False

        # retrieval_module Mock
        retrieval_module = AsyncMock()
        retrieval_module.search = AsyncMock(return_value=[])

        # generation_module Mock
        from app.modules.core.generation.generator import GenerationResult

        generation_module = AsyncMock()
        generation_module.generate_answer = AsyncMock(
            return_value=GenerationResult(
                answer="기존 파이프라인 답변입니다.",
                text="기존 파이프라인 답변입니다.",
                tokens_used=100,
                model_used="test-model",
                provider="test-provider",
                generation_time=0.5,
            )
        )

        # session_module Mock
        session_module = AsyncMock()
        session_module.get_context_string = AsyncMock(return_value=None)
        session_module.get_conversation = AsyncMock(return_value=[])

        # circuit_breaker_factory Mock (async 함수를 올바르게 처리)
        async def async_call(func, fallback):
            """Circuit breaker의 call 메서드를 async로 처리"""
            result = func()
            if asyncio.iscoroutine(result):
                return await result
            return result

        import asyncio

        circuit_breaker = MagicMock()
        circuit_breaker.call = async_call  # AsyncMock 대신 async 함수 직접 사용
        circuit_breaker_factory = MagicMock()
        circuit_breaker_factory.get = MagicMock(return_value=circuit_breaker)

        # cost_tracker Mock
        cost_tracker = MagicMock()
        cost_tracker.track_usage = MagicMock()

        # performance_metrics Mock
        performance_metrics = MagicMock()
        performance_metrics.record_latency = MagicMock()
        performance_metrics.record_error = MagicMock()

        return {
            "query_router": query_router,
            "query_expansion": None,
            "retrieval_module": retrieval_module,
            "generation_module": generation_module,
            "session_module": session_module,
            "self_rag_module": None,
            "circuit_breaker_factory": circuit_breaker_factory,
            "cost_tracker": cost_tracker,
            "performance_metrics": performance_metrics,
        }

    @pytest.mark.asyncio
    async def test_pipeline_with_agent_mode(
        self,
        mock_config: dict[str, Any],
        mock_agent_orchestrator: AsyncMock,
        mock_modules: dict[str, Any],
    ) -> None:
        """
        Agent 모드 활성화 테스트

        use_agent=True일 때:
        - AgentOrchestrator.run()이 호출되어야 함
        - 기존 retrieve_documents/generate_answer는 호출되지 않아야 함
        - 결과에 agent 관련 메타데이터가 포함되어야 함
        """
        from app.api.services.rag_pipeline import RAGPipeline

        # RAGPipeline 생성 (Agent 포함)
        pipeline = RAGPipeline(
            config=mock_config,
            agent_orchestrator=mock_agent_orchestrator,
            extract_topic_func=lambda x: "테스트 토픽",
            **mock_modules,
        )

        # use_agent=True로 실행
        result = await pipeline.execute(
            message="테스트 질문입니다",
            session_id="test-session",
            options={"use_agent": True},
        )

        # 검증: Agent가 호출되었는지
        mock_agent_orchestrator.run.assert_called_once()
        call_args = mock_agent_orchestrator.run.call_args
        assert "테스트 질문" in call_args.kwargs.get("query", "") or "테스트 질문" in str(call_args)

        # 검증: 결과가 Agent 모드 형식인지
        assert result["answer"] == "Agent 모드 답변입니다."
        assert result.get("metadata", {}).get("mode") == "agent"

    @pytest.mark.asyncio
    async def test_pipeline_agent_mode_blocked_by_rule(
        self,
        mock_config: dict[str, Any],
        mock_agent_orchestrator: AsyncMock,
        mock_modules: dict[str, Any],
    ) -> None:
        from app.api.services.rag_pipeline import RAGPipeline
        from app.modules.core.routing.rule_based_router import RuleMatch

        pipeline = RAGPipeline(
            config=mock_config,
            agent_orchestrator=mock_agent_orchestrator,
            extract_topic_func=lambda x: "테스트 토픽",
            **mock_modules,
        )
        pipeline.rule_based_router.check_rules = AsyncMock(
            return_value=RuleMatch(
                rule_name="security", route="blocked", domain="general",
                intent="security", confidence=1.0, direct_answer="차단됨",
            )
        )

        result = await pipeline.execute("차단 질문", "test-session", {"use_agent": True})

        assert result["answer"] == "차단됨"
        mock_agent_orchestrator.run.assert_not_called()
        mock_modules["retrieval_module"].search.assert_not_called()

    @pytest.mark.asyncio
    async def test_pipeline_without_agent_mode(
        self,
        mock_config: dict[str, Any],
        mock_agent_orchestrator: AsyncMock,
        mock_modules: dict[str, Any],
    ) -> None:
        """
        기존 모드 유지 테스트

        use_agent=False (기본값)일 때:
        - 기존 7단계 파이프라인이 실행되어야 함
        - AgentOrchestrator.run()은 호출되지 않아야 함
        """
        from app.api.services.rag_pipeline import RAGPipeline

        # RAGPipeline 생성 (Agent 포함하지만 사용 안 함)
        pipeline = RAGPipeline(
            config=mock_config,
            agent_orchestrator=mock_agent_orchestrator,
            extract_topic_func=lambda x: "테스트 토픽",
            **mock_modules,
        )

        # use_agent=False (기본값)로 실행
        result = await pipeline.execute(
            message="테스트 질문입니다",
            session_id="test-session",
            options={},  # use_agent 없음 = False
        )

        # 검증: Agent가 호출되지 않았는지
        mock_agent_orchestrator.run.assert_not_called()

        # 검증: 기존 파이프라인이 실행되었는지
        mock_modules["generation_module"].generate_answer.assert_called_once()

        # 검증: 기존 파이프라인 응답 확인
        assert result["answer"] == "기존 파이프라인 답변입니다."
        assert result.get("metadata", {}).get("mode") != "agent"

    @pytest.mark.asyncio
    async def test_pipeline_agent_disabled_fallback(
        self,
        mock_config: dict[str, Any],
        mock_modules: dict[str, Any],
    ) -> None:
        """
        Agent 비활성화 시 폴백 테스트

        agent_orchestrator=None일 때:
        - use_agent=True여도 기존 파이프라인 사용
        - 에러 없이 정상 동작
        """
        from app.api.services.rag_pipeline import RAGPipeline

        # RAGPipeline 생성 (Agent 없음)
        pipeline = RAGPipeline(
            config=mock_config,
            agent_orchestrator=None,  # Agent 없음
            extract_topic_func=lambda x: "테스트 토픽",
            **mock_modules,
        )

        # use_agent=True지만 Agent 없음
        result = await pipeline.execute(
            message="테스트 질문입니다",
            session_id="test-session",
            options={"use_agent": True},  # Agent 요청하지만 없음
        )

        # 검증: 기존 파이프라인이 실행되었는지 (폴백)
        mock_modules["generation_module"].generate_answer.assert_called_once()

        # 검증: 에러 없이 정상 응답
        assert result["answer"] is not None

    @pytest.mark.asyncio
    async def test_pipeline_agent_result_format(
        self,
        mock_config: dict[str, Any],
        mock_agent_orchestrator: AsyncMock,
        mock_modules: dict[str, Any],
    ) -> None:
        """
        Agent 결과 포맷 테스트

        Agent 모드 결과에 포함되어야 하는 필드:
        - answer: 최종 답변
        - sources: 소스 목록
        - metadata.mode: "agent"
        - metadata.steps_taken: 실행된 스텝 수
        - metadata.tools_used: 사용된 도구 목록
        """
        from app.api.services.rag_pipeline import RAGPipeline

        # RAGPipeline 생성
        pipeline = RAGPipeline(
            config=mock_config,
            agent_orchestrator=mock_agent_orchestrator,
            extract_topic_func=lambda x: "테스트 토픽",
            **mock_modules,
        )

        # Agent 모드로 실행
        result = await pipeline.execute(
            message="테스트",
            session_id="test",
            options={"use_agent": True},
        )

        # 필수 필드 검증
        assert "answer" in result
        assert "sources" in result
        assert result.get("metadata", {}).get("mode") == "agent"
        assert result.get("metadata", {}).get("steps_taken") is not None
        assert result.get("metadata", {}).get("tools_used") is not None


class TestChatRequestWithUseAgent:
    """ChatRequest use_agent 필드 테스트"""

    def test_chat_request_use_agent_default_false(self) -> None:
        """use_agent 기본값이 False인지 확인"""
        from app.api.schemas.chat_schemas import ChatRequest

        request = ChatRequest(message="테스트 메시지")

        assert hasattr(request, "use_agent")
        assert request.use_agent is False

    def test_chat_request_use_agent_true(self) -> None:
        """use_agent=True 설정 가능한지 확인"""
        from app.api.schemas.chat_schemas import ChatRequest

        request = ChatRequest(
            message="테스트 메시지",
            use_agent=True,
        )

        assert request.use_agent is True

    def test_chat_request_use_agent_in_options(self) -> None:
        """options에서 use_agent 추출 가능한지 확인"""
        from app.api.schemas.chat_schemas import ChatRequest

        request = ChatRequest(
            message="테스트 메시지",
            options={"use_agent": True},
        )

        # options에서 use_agent 추출
        use_agent = request.options.get("use_agent", False) if request.options else False
        assert use_agent is True
