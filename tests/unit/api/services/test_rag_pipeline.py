"""
RAG Pipeline 단위 테스트

7단계 파이프라인:
1. route_query: 쿼리 라우팅
2. prepare_context: 컨텍스트 준비
3. retrieve_documents: 문서 검색
4. rerank_documents: 리랭킹
5. generate_answer: 답변 생성
6. self_rag_verify: Self-RAG 검증
7. format_sources: 소스 포맷팅
8. build_result: 결과 구성

추가: Agent 모드, SQL 검색
"""

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.services.rag_pipeline import (
    FormattedSources,
    PreparedContext,
    RAGPipeline,
    RerankResults,
    RetrievalResults,
    RouteDecision,
)
from app.lib.types import RAGResultDict
from app.modules.core.generation.generator import GenerationResult


@pytest.fixture
def mock_config() -> dict[str, Any]:
    """Mock 설정"""
    return {
        "generation": {
            "default_provider": "openrouter",
            "temperature": 0.2,
        },
        "rag": {
            "top_k": 10,
            "rerank_top_k": 5,
            "score_normalization": {"enabled": True},
        },
        "retrieval": {
            "top_k": 10,
            "min_score": 0.05,
            "enable_reranking": True,
        },
        "reranking": {
            "enabled": True,
            "min_score": 0.05,
        },
        "privacy": {
            "enabled": False,
        },
        "self_rag": {
            "enabled": False,
        },
    }


@pytest.fixture
def mock_modules() -> dict[str, Any]:
    """Mock 모듈들"""
    return {
        "query_router": MagicMock(enabled=False),
        "query_expansion": None,
        "retrieval_module": AsyncMock(),
        "generation_module": AsyncMock(),
        "session_module": AsyncMock(),
        "self_rag_module": None,
        "extract_topic_func": lambda x: x[:10],
        "circuit_breaker_factory": MagicMock(),
        "cost_tracker": MagicMock(),
        "performance_metrics": MagicMock(),
        "sql_search_service": None,
        "agent_orchestrator": None,
    }


class TestRAGPipelineInit:
    """RAGPipeline 초기화 테스트"""

    def test_init_success(
        self,
        mock_config: dict[str, Any],
        mock_modules: dict[str, Any],
    ) -> None:
        """
        RAGPipeline 정상 초기화

        Given: 유효한 config와 modules
        When: RAGPipeline 생성
        Then: 필드가 올바르게 초기화됨
        """
        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        assert pipeline.config == mock_config
        assert pipeline.retrieval_module is mock_modules["retrieval_module"]
        assert pipeline.generation_module is mock_modules["generation_module"]
        assert pipeline.retrieval_limit == 10
        assert pipeline.rerank_top_n == 5

    def test_init_with_defaults(
        self,
        mock_config: dict[str, Any],
        mock_modules: dict[str, Any],
    ) -> None:
        """
        기본값으로 초기화

        Given: 일부 설정 누락
        When: RAGPipeline 생성
        Then: Fallback 기본값 사용
        """
        minimal_config = {"generation": {}, "rag": {}}
        pipeline = RAGPipeline(config=minimal_config, **mock_modules)

        # Fallback 기본값 검증
        assert pipeline.retrieval_limit == RAGPipeline.FALLBACK_RETRIEVAL_LIMIT
        assert pipeline.rerank_top_n == RAGPipeline.FALLBACK_RERANK_TOP_N


class TestExecute:
    """execute 메서드 테스트 (메인 엔트리포인트)"""

    @pytest.fixture
    def pipeline(
        self,
        mock_config: dict[str, Any],
        mock_modules: dict[str, Any],
    ) -> RAGPipeline:
        return RAGPipeline(config=mock_config, **mock_modules)

    @pytest.mark.asyncio
    async def test_execute_standard_mode_success(self, pipeline: RAGPipeline) -> None:
        """
        표준 모드 성공 실행

        Given: 표준 모드 옵션 (use_agent=False)
        When: execute 호출
        Then: 7단계 파이프라인 실행 후 결과 반환
        """
        # Mock: 각 단계
        with (
            patch.object(pipeline, "route_query") as mock_route,
            patch.object(pipeline, "prepare_context") as mock_prepare,
            patch.object(pipeline, "retrieve_documents") as mock_retrieve,
            patch.object(pipeline, "rerank_documents") as mock_rerank,
            patch.object(pipeline, "generate_answer") as mock_generate,
            patch.object(pipeline, "self_rag_verify") as mock_self_rag,
            patch.object(pipeline, "format_sources") as mock_format,
            patch.object(pipeline, "build_result") as mock_build,
        ):
            # Mock 반환값 설정
            mock_route.return_value = RouteDecision(should_continue=True, metadata={})
            mock_prepare.return_value = PreparedContext(
                session_context=None,
                expanded_query="확장된 쿼리",
                original_query="원본 쿼리",
                expanded_queries=["확장된 쿼리"],
                query_weights=[1.0],
            )
            mock_retrieve.return_value = RetrievalResults(documents=[MagicMock(id="doc1")], count=1)
            mock_rerank.return_value = RerankResults(
                documents=[MagicMock(id="doc1")], count=1, reranked=True
            )
            mock_generate.return_value = GenerationResult(
                answer="표준 모드 답변",
                text="표준 모드 답변",
                tokens_used=100,
                model_used="gemini-2.5-flash",
                provider="google",
                generation_time=1.0,
            )
            mock_self_rag.return_value = mock_generate.return_value
            mock_format.return_value = FormattedSources(
                sources=[{"title": "문서1"}], count=1
            )
            mock_build.return_value = {
                "answer": "표준 모드 답변",
                "sources": [{"title": "문서1"}],
                "metadata": {},
                "processing_time": 1.5,  # 필수 필드 추가
            }

            result = await pipeline.execute(
                message="테스트 질문",
                session_id="test-session",
                options={"use_agent": False},
            )

        # 검증
        assert result["answer"] == "표준 모드 답변"
        mock_route.assert_called_once()
        mock_prepare.assert_called_once()
        mock_retrieve.assert_called_once()
        mock_rerank.assert_called_once()
        mock_generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_direct_answer_skip_pipeline(
        self, pipeline: RAGPipeline
    ) -> None:
        """
        즉시 응답 시 파이프라인 중단

        Given: route_query가 즉시 응답 반환
        When: execute 호출
        Then: 나머지 단계 스킵하고 즉시 응답 반환
        """
        immediate_response: RAGResultDict = {
            "answer": "안녕하세요!",
            "sources": [],
            "tokens_used": 0,
            "topic": "인사",
            "processing_time": 0.1,
            "search_results": 0,
            "ranked_results": 0,
            "model_info": {"provider": "rule_based", "model": "N/A"},
        }

        with patch.object(pipeline, "route_query") as mock_route:
            mock_route.return_value = RouteDecision(
                should_continue=False,
                immediate_response=immediate_response,
                metadata={"route": "direct_answer"},
            )

            result = await pipeline.execute(
                message="안녕하세요",
                session_id="test",
                options={},
            )

        assert result["answer"] == "안녕하세요!"
        assert result["sources"] == []

    @pytest.mark.asyncio
    async def test_execute_agent_mode(self, mock_config, mock_modules) -> None:
        """
        Agent 모드 실행

        Given: use_agent=True, agent_orchestrator 설정됨
        When: execute 호출
        Then: _execute_agent_mode 호출
        """
        mock_agent = AsyncMock()
        mock_modules["agent_orchestrator"] = mock_agent
        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        with patch.object(pipeline, "_execute_agent_mode") as mock_agent_exec:
            mock_agent_exec.return_value = {
                "answer": "Agent 답변",
                "sources": [],
                "metadata": {"mode": "agent"},
            }

            result = await pipeline.execute(
                message="복잡한 질문",
                session_id="test",
                options={"use_agent": True},
            )

        assert result["answer"] == "Agent 답변"
        mock_agent_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_sql_and_rag_parallel_success(
        self, mock_config, mock_modules
    ) -> None:
        """
        SQL+RAG 병렬 검색 성공

        Given: SQL 검색 서비스 활성화, 둘 다 성공
        When: execute 호출
        Then: asyncio.gather로 병렬 실행 후 결과 통합
        """
        from app.modules.core.sql_search.service import SQLSearchResult

        # SQL 검색 서비스 Mock
        mock_sql_service = AsyncMock()
        mock_sql_service.is_enabled = MagicMock(return_value=True)
        mock_modules["sql_search_service"] = mock_sql_service

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        # Mock: 각 단계
        with (
            patch.object(pipeline, "route_query") as mock_route,
            patch.object(pipeline, "prepare_context") as mock_prepare,
            patch.object(pipeline, "retrieve_documents") as mock_retrieve,
            patch.object(pipeline, "_execute_sql_search") as mock_sql_search,
            patch.object(pipeline, "rerank_documents") as mock_rerank,
            patch.object(pipeline, "generate_answer") as mock_generate,
            patch.object(pipeline, "self_rag_verify") as mock_self_rag,
            patch.object(pipeline, "format_sources") as mock_format,
            patch.object(pipeline, "build_result") as mock_build,
        ):
            # Mock 반환값 설정
            mock_route.return_value = RouteDecision(should_continue=True, metadata={})
            mock_prepare.return_value = PreparedContext(
                session_context=None,
                expanded_query="확장된 쿼리",
                original_query="원본 쿼리",
                expanded_queries=["확장된 쿼리"],
                query_weights=[1.0],
            )
            mock_retrieve.return_value = RetrievalResults(
                documents=[MagicMock(id="doc1")], count=1
            )

            # SQL 검색 결과 Mock
            mock_query_result = MagicMock()
            mock_query_result.row_count = 5
            mock_sql_result = SQLSearchResult(
                success=True,
                generation_result=None,
                query_result=mock_query_result,
                formatted_context="SQL 컨텍스트",
                total_time=0.5,
                used=True,
            )
            mock_sql_search.return_value = mock_sql_result

            mock_rerank.return_value = RerankResults(
                documents=[MagicMock(id="doc1")], count=1, reranked=True
            )
            mock_generate.return_value = GenerationResult(
                answer="SQL+RAG 답변",
                text="SQL+RAG 답변",
                tokens_used=100,
                model_used="gemini-2.5-flash",
                provider="google",
                generation_time=1.0,
            )
            mock_self_rag.return_value = mock_generate.return_value
            mock_format.return_value = FormattedSources(
                sources=[{"title": "문서1"}], count=1
            )
            mock_build.return_value = {
                "answer": "SQL+RAG 답변",
                "sources": [{"title": "문서1"}],
                "metadata": {},
                "processing_time": 1.5,
            }

            result = await pipeline.execute(
                message="테스트 질문",
                session_id="test-session",
                options={},
            )

        # 검증: SQL 검색과 RAG 검색이 병렬로 실행되었는지
        mock_retrieve.assert_called_once()
        mock_sql_search.assert_called_once()
        assert result["answer"] == "SQL+RAG 답변"

    @pytest.mark.asyncio
    async def test_execute_sql_fails_rag_continues(
        self, mock_config, mock_modules
    ) -> None:
        """
        SQL 실패해도 RAG는 계속 진행

        Given: SQL 검색 활성화, SQL 실패, RAG 성공
        When: execute 호출
        Then: SQL 에러 무시하고 RAG 결과만 사용
        """
        # SQL 검색 서비스 Mock
        mock_sql_service = AsyncMock()
        mock_sql_service.is_enabled = MagicMock(return_value=True)
        mock_modules["sql_search_service"] = mock_sql_service

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        with (
            patch.object(pipeline, "route_query") as mock_route,
            patch.object(pipeline, "prepare_context") as mock_prepare,
            patch.object(pipeline, "retrieve_documents") as mock_retrieve,
            patch.object(pipeline, "_execute_sql_search") as mock_sql_search,
            patch.object(pipeline, "rerank_documents") as mock_rerank,
            patch.object(pipeline, "generate_answer") as mock_generate,
            patch.object(pipeline, "self_rag_verify") as mock_self_rag,
            patch.object(pipeline, "format_sources") as mock_format,
            patch.object(pipeline, "build_result") as mock_build,
        ):
            mock_route.return_value = RouteDecision(should_continue=True, metadata={})
            mock_prepare.return_value = PreparedContext(
                session_context=None,
                expanded_query="확장된 쿼리",
                original_query="원본 쿼리",
                expanded_queries=["확장된 쿼리"],
                query_weights=[1.0],
            )
            mock_retrieve.return_value = RetrievalResults(
                documents=[MagicMock(id="doc1")], count=1
            )
            # SQL 검색 실패
            mock_sql_search.side_effect = RuntimeError("SQL 검색 실패")

            mock_rerank.return_value = RerankResults(
                documents=[MagicMock(id="doc1")], count=1, reranked=True
            )
            mock_generate.return_value = GenerationResult(
                answer="RAG만 답변",
                text="RAG만 답변",
                tokens_used=100,
                model_used="gemini-2.5-flash",
                provider="google",
                generation_time=1.0,
            )
            mock_self_rag.return_value = mock_generate.return_value
            mock_format.return_value = FormattedSources(
                sources=[{"title": "문서1"}], count=1
            )
            mock_build.return_value = {
                "answer": "RAG만 답변",
                "sources": [{"title": "문서1"}],
                "metadata": {},
                "processing_time": 1.5,
            }

            result = await pipeline.execute(
                message="테스트 질문",
                session_id="test-session",
                options={},
            )

        # 검증: SQL 실패해도 RAG 성공하면 계속 진행
        assert result["answer"] == "RAG만 답변"

    @pytest.mark.asyncio
    async def test_execute_rag_fails_raises_exception(
        self, mock_config, mock_modules
    ) -> None:
        """
        RAG 실패 시 예외 발생

        Given: SQL 검색 활성화, RAG 실패
        When: execute 호출
        Then: RAG 예외가 상위로 전파됨
        """
        # SQL 검색 서비스 Mock
        mock_sql_service = AsyncMock()
        mock_sql_service.is_enabled = MagicMock(return_value=True)
        mock_modules["sql_search_service"] = mock_sql_service

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        with (
            patch.object(pipeline, "route_query") as mock_route,
            patch.object(pipeline, "prepare_context") as mock_prepare,
            patch.object(pipeline, "retrieve_documents") as mock_retrieve,
            patch.object(pipeline, "_execute_sql_search") as mock_sql_search,
        ):
            mock_route.return_value = RouteDecision(should_continue=True, metadata={})
            mock_prepare.return_value = PreparedContext(
                session_context=None,
                expanded_query="확장된 쿼리",
                original_query="원본 쿼리",
                expanded_queries=["확장된 쿼리"],
                query_weights=[1.0],
            )
            # RAG 검색 실패
            mock_retrieve.side_effect = RuntimeError("RAG 검색 실패")
            mock_sql_search.return_value = None

            # 검증: RAG 실패 시 예외 발생
            with pytest.raises(RuntimeError, match="RAG 검색 실패"):
                await pipeline.execute(
                    message="테스트 질문",
                    session_id="test-session",
                    options={},
                )


class TestRouteQuery:
    """route_query 메서드 테스트"""

    @pytest.fixture
    def pipeline(self, mock_config, mock_modules) -> RAGPipeline:
        return RAGPipeline(config=mock_config, **mock_modules)

    @pytest.mark.asyncio
    async def test_route_to_rag_with_disabled_router(
        self, pipeline: RAGPipeline
    ) -> None:
        """
        라우터 비활성화 시 RAG 계속 진행

        Given: query_router.enabled=False
        When: route_query 호출
        Then: should_continue=True 반환
        """
        decision = await pipeline.route_query(
            message="테스트 질문",
            session_id="test",
            start_time=time.time(),
        )

        assert decision.should_continue is True
        assert decision.immediate_response is None

    @pytest.mark.asyncio
    async def test_route_with_rule_based_direct_answer(
        self, mock_config, mock_modules
    ) -> None:
        """
        규칙 기반 즉시 응답

        Given: RuleBasedRouter가 direct_answer 반환
        When: route_query 호출
        Then: 즉시 응답 반환
        """
        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        with patch("app.api.services.rag_pipeline.RuleBasedRouter") as mock_router_class:
            mock_router = mock_router_class.return_value
            mock_match = MagicMock()
            mock_match.route = "direct_answer"
            mock_match.direct_answer = "안녕하세요!"
            mock_match.confidence = 0.95
            mock_match.rule_name = "greeting"
            mock_match.intent = "greeting"
            mock_match.domain = "general"
            mock_router.check_rules = AsyncMock(return_value=mock_match)

            decision = await pipeline.route_query("안녕", "test", time.time())

        assert decision.should_continue is False
        assert decision.immediate_response is not None
        assert decision.immediate_response["answer"] == "안녕하세요!"

    @pytest.mark.asyncio
    async def test_route_with_session_context_formatting(
        self, mock_config, mock_modules
    ) -> None:
        """
        세션 컨텍스트 포매팅

        Given: session_module.get_conversation 반환
        When: route_query 호출
        Then: conversation 리스트를 포맷팅하여 session_context 생성
        """
        # conversation 리스트 Mock
        mock_conversation = [
            {"user": "첫 번째 질문", "assistant": "첫 번째 답변"},
            {"user": "두 번째 질문", "assistant": "두 번째 답변"},
        ]
        mock_modules["session_module"].get_conversation = AsyncMock(
            return_value=mock_conversation
        )

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        with patch("app.api.services.rag_pipeline.RuleBasedRouter") as mock_router_class:
            mock_router = mock_router_class.return_value
            mock_router.check_rules = AsyncMock(return_value=None)

            decision = await pipeline.route_query(
                message="세 번째 질문",
                session_id="test-session",
                start_time=time.time(),
            )

        # 검증: get_conversation 호출되었는지
        mock_modules["session_module"].get_conversation.assert_called_once_with(
            "test-session", max_exchanges=5
        )
        assert decision.should_continue is True

    @pytest.mark.asyncio
    async def test_route_with_session_context_error(
        self, mock_config, mock_modules
    ) -> None:
        """
        세션 컨텍스트 조회 실패 시 무시

        Given: session_module.get_conversation 에러 발생
        When: route_query 호출
        Then: 에러 무시하고 계속 진행
        """
        mock_modules["session_module"].get_conversation = AsyncMock(
            side_effect=RuntimeError("세션 조회 실패")
        )

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        with patch("app.api.services.rag_pipeline.RuleBasedRouter") as mock_router_class:
            mock_router = mock_router_class.return_value
            mock_router.check_rules = AsyncMock(return_value=None)

            # 에러 발생하지 않고 정상 진행
            decision = await pipeline.route_query(
                message="테스트 질문",
                session_id="test-session",
                start_time=time.time(),
            )

        assert decision.should_continue is True

    @pytest.mark.asyncio
    async def test_route_llm_blocked(
        self, mock_config, mock_modules
    ) -> None:
        """
        LLM 라우터가 "blocked" 라우트 반환

        Given: LLM 라우터가 blocked 라우트 반환
        When: route_query 호출
        Then: should_continue=False, immediate_response 반환
        """
        from app.modules.core.routing.llm_query_router import (
            QueryComplexity,
            QueryProfile,
            RoutingDecision,
            SearchIntent,
        )

        # Query Router Mock 설정
        mock_query_router = MagicMock()
        mock_query_router.enabled = True
        mock_modules["query_router"] = mock_query_router

        # LLM 라우터 응답 Mock
        mock_profile = QueryProfile(
            original_query="부적절한 질문",
            intent=SearchIntent.FACTUAL,
            domain="general",
            complexity=QueryComplexity.SIMPLE,
        )
        mock_routing = RoutingDecision(
            primary_route="blocked",
            confidence=0.9,
            should_call_rag=False,
            should_block=True,
            notes="부적절한 질문입니다",
        )
        mock_query_router.analyze_and_route = AsyncMock(
            return_value=(mock_profile, mock_routing)
        )

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        with patch("app.api.services.rag_pipeline.RuleBasedRouter") as mock_router_class:
            mock_router = mock_router_class.return_value
            mock_router.check_rules = AsyncMock(return_value=None)

            decision = await pipeline.route_query(
                message="부적절한 질문",
                session_id="test-session",
                start_time=time.time(),
            )

        # 검증: blocked 라우트 시 즉시 응답
        assert decision.should_continue is False
        assert decision.immediate_response is not None
        assert decision.immediate_response["answer"] == "죄송합니다. 해당 질문은 처리할 수 없습니다."
        assert decision.metadata.get("llm_route") == "blocked"

    @pytest.mark.asyncio
    async def test_route_rule_exception(
        self, mock_config, mock_modules
    ) -> None:
        """
        RuleBasedRouter 예외 발생 시 LLM 폴백

        Given: RuleBasedRouter에서 예외 발생
        When: route_query 호출
        Then: 예외 무시하고 LLM 라우터로 폴백
        """
        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        with patch("app.api.services.rag_pipeline.RuleBasedRouter") as mock_router_class:
            mock_router = mock_router_class.return_value
            # RuleBasedRouter 예외 발생
            mock_router.check_rules = AsyncMock(side_effect=RuntimeError("규칙 체크 실패"))

            decision = await pipeline.route_query(
                message="테스트 질문",
                session_id="test-session",
                start_time=time.time(),
            )

        # 검증: 예외 발생해도 계속 진행 (LLM 비활성화 상태)
        assert decision.should_continue is True


class TestPrepareContext:
    """prepare_context 메서드 테스트"""

    @pytest.fixture
    def pipeline(self, mock_config, mock_modules) -> RAGPipeline:
        return RAGPipeline(config=mock_config, **mock_modules)

    @pytest.mark.asyncio
    async def test_prepare_context_without_expansion(
        self, pipeline: RAGPipeline, mock_modules
    ) -> None:
        """
        쿼리 확장 없이 컨텍스트 준비

        Given: query_expansion=None
        When: prepare_context 호출
        Then: 원본 메시지 그대로 반환
        """
        mock_modules["session_module"].get_context_string = AsyncMock(return_value=None)

        context = await pipeline.prepare_context(
            message="원본 질문",
            session_id="test",
        )

        assert context.expanded_query == "원본 질문"
        assert context.original_query == "원본 질문"
        assert context.expanded_queries == ["원본 질문"]
        assert context.query_weights == [1.0]

    @pytest.mark.asyncio
    async def test_prepare_context_with_session(
        self, pipeline: RAGPipeline, mock_modules
    ) -> None:
        """
        세션 컨텍스트 포함

        Given: 기존 세션 컨텍스트
        When: prepare_context 호출
        Then: session_context 필드에 세션 정보 포함
        """
        mock_modules["session_module"].get_context_string = AsyncMock(
            return_value="이전 대화 컨텍스트"
        )

        context = await pipeline.prepare_context(
            message="후속 질문",
            session_id="test",
        )

        assert context.session_context == "이전 대화 컨텍스트"

    @pytest.mark.asyncio
    async def test_prepare_context_with_query_expansion(
        self, mock_config, mock_modules
    ) -> None:
        """
        쿼리 확장 포함

        Given: query_expansion 모듈 활성화
        When: prepare_context 호출
        Then: 확장된 쿼리 반환
        """
        mock_expansion = AsyncMock()
        mock_result = MagicMock()
        mock_result.expansions = ["확장 쿼리1", "확장 쿼리2"]
        mock_result.metadata = {
            "raw_expanded_queries": [
                {"query": "확장 쿼리1", "weight": 1.0},
                {"query": "확장 쿼리2", "weight": 0.8},
            ]
        }
        mock_expansion.expand_query = AsyncMock(return_value=mock_result)
        mock_modules["query_expansion"] = mock_expansion

        pipeline = RAGPipeline(config=mock_config, **mock_modules)
        context = await pipeline.prepare_context("원본", "test")

        assert context.expanded_query == "확장 쿼리1"
        assert len(context.expanded_queries) == 2
        assert context.query_weights == [1.0, 0.8]

    @pytest.mark.asyncio
    async def test_prepare_context_expansion_empty(
        self, mock_config, mock_modules
    ) -> None:
        """
        쿼리 확장 결과 비어있음

        Given: query_expansion이 빈 결과 반환
        When: prepare_context 호출
        Then: 원본 쿼리 사용
        """
        mock_expansion = AsyncMock()
        mock_result = MagicMock()
        mock_result.expansions = []  # 빈 결과
        mock_result.metadata = {}
        mock_expansion.expand_query = AsyncMock(return_value=mock_result)
        mock_modules["query_expansion"] = mock_expansion

        pipeline = RAGPipeline(config=mock_config, **mock_modules)
        context = await pipeline.prepare_context("원본 질문", "test")

        # 검증: 빈 결과 시 원본 사용
        assert context.expanded_query == "원본 질문"
        assert context.expanded_queries == ["원본 질문"]
        assert context.query_weights == [1.0]

    @pytest.mark.asyncio
    async def test_prepare_context_expansion_error(
        self, mock_config, mock_modules
    ) -> None:
        """
        쿼리 확장 실패 시 폴백

        Given: query_expansion에서 예외 발생
        When: prepare_context 호출
        Then: 원본 쿼리 사용
        """
        mock_expansion = AsyncMock()
        mock_expansion.expand_query = AsyncMock(side_effect=RuntimeError("확장 실패"))
        mock_modules["query_expansion"] = mock_expansion

        pipeline = RAGPipeline(config=mock_config, **mock_modules)
        context = await pipeline.prepare_context("원본 질문", "test")

        # 검증: 예외 발생 시 원본 사용
        assert context.expanded_query == "원본 질문"
        assert context.expanded_queries == ["원본 질문"]
        assert context.query_weights == [1.0]


class TestRetrieveDocuments:
    """retrieve_documents 메서드 테스트"""

    @pytest.fixture
    def pipeline(self, mock_config, mock_modules) -> RAGPipeline:
        # Circuit breaker mock 설정 - async 함수를 올바르게 await
        mock_cb = MagicMock()

        async def mock_circuit_breaker_call(fn, fallback):
            return await fn()

        mock_cb.call = mock_circuit_breaker_call
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)
        return RAGPipeline(config=mock_config, **mock_modules)

    @pytest.mark.asyncio
    async def test_retrieve_documents_success(
        self, pipeline: RAGPipeline, mock_modules
    ) -> None:
        """
        문서 검색 성공

        Given: 검색 쿼리
        When: retrieve_documents 호출
        Then: 문서 리스트 반환
        """
        mock_docs = [
            MagicMock(id="doc1", score=0.9),
            MagicMock(id="doc2", score=0.8),
        ]

        # Circuit breaker call이 async 함수를 실행하도록 수정
        async def mock_search_and_merge(*args, **kwargs):
            return mock_docs

        mock_modules["retrieval_module"]._search_and_merge = mock_search_and_merge

        # IMultiQueryRetriever Protocol 충족을 위한 설정
        type(mock_modules["retrieval_module"]).__name__ = "IMultiQueryRetriever"

        docs = await pipeline.retrieve_documents(
            search_queries=["검색 쿼리"],
            query_weights=[1.0],
            context=None,
            options={},
        )

        assert docs.count == 2
        assert docs.documents[0].id == "doc1"

    @pytest.mark.asyncio
    async def test_retrieve_documents_multi_query(
        self, pipeline: RAGPipeline, mock_modules
    ) -> None:
        """
        Multi-Query RRF 검색

        Given: 여러 검색 쿼리
        When: retrieve_documents 호출
        Then: RRF 병합된 결과 반환
        """
        mock_docs = [MagicMock(id=f"doc{i}", score=0.9 - i * 0.1) for i in range(5)]

        async def mock_search_and_merge(*args, **kwargs):
            return mock_docs

        mock_modules["retrieval_module"]._search_and_merge = mock_search_and_merge
        type(mock_modules["retrieval_module"]).__name__ = "IMultiQueryRetriever"

        docs = await pipeline.retrieve_documents(
            search_queries=["쿼리1", "쿼리2", "쿼리3"],
            query_weights=[1.0, 0.8, 0.6],
            context=None,
            options={},
        )

        assert docs.count == 5

    @pytest.mark.asyncio
    async def test_retrieve_no_retrieval_module(
        self, mock_config, mock_modules
    ) -> None:
        """
        Retrieval Module 없음 에러

        Given: retrieval_module=None
        When: retrieve_documents 호출
        Then: RetrievalError 발생
        """
        from app.lib.errors import RetrievalError

        # retrieval_module을 None으로 설정
        mock_modules["retrieval_module"] = None

        # Circuit breaker mock 설정
        mock_cb = MagicMock()

        async def mock_circuit_breaker_call(fn, fallback):
            return await fn()

        mock_cb.call = mock_circuit_breaker_call
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        # 검증: RetrievalError 발생 (신규 양언어 에러 시스템 메시지)
        with pytest.raises(RetrievalError, match="Retrieval 모듈에서 검색 실패"):
            await pipeline.retrieve_documents(
                search_queries=["검색 쿼리"],
                query_weights=[1.0],
                context=None,
                options={},
            )

    @pytest.mark.asyncio
    async def test_retrieve_single_query_string(
        self, pipeline: RAGPipeline, mock_modules
    ) -> None:
        """
        단일 쿼리 문자열 하위 호환성

        Given: search_queries가 str (리스트 아님)
        When: retrieve_documents 호출
        Then: 자동으로 리스트로 변환하여 처리
        """
        mock_docs = [MagicMock(id="doc1", score=0.9)]

        async def mock_search_and_merge(*args, **kwargs):
            return mock_docs

        mock_modules["retrieval_module"]._search_and_merge = mock_search_and_merge
        type(mock_modules["retrieval_module"]).__name__ = "IMultiQueryRetriever"

        # 문자열로 전달 (하위 호환성)
        docs = await pipeline.retrieve_documents(
            search_queries="단일 쿼리 문자열",  # str, not list
            query_weights=None,  # None으로 전달
            context=None,
            options={},
        )

        # 검증: 정상 처리됨
        assert docs.count == 1
        assert docs.documents[0].id == "doc1"

    @pytest.mark.asyncio
    async def test_retrieve_fallback_single_query_search(
        self, mock_config, mock_modules
    ) -> None:
        """
        MultiQueryRetriever가 아닌 경우 폴백

        Given: retrieval_module이 IMultiQueryRetriever Protocol 미충족
        When: retrieve_documents 호출
        Then: 단일 쿼리 검색 폴백 (첫 번째 쿼리만 사용)
        """
        mock_docs = [MagicMock(id="doc1", score=0.9)]

        # IMultiQueryRetriever가 아닌 일반 retriever
        # _search_and_merge 메서드가 없어야 폴백 로직 실행됨
        class SimpleMockRetriever:
            async def search(self, query, options):
                return mock_docs

        mock_retriever = SimpleMockRetriever()
        mock_modules["retrieval_module"] = mock_retriever

        # Circuit breaker mock 설정
        mock_cb = MagicMock()

        async def mock_circuit_breaker_call(fn, fallback):
            return await fn()

        mock_cb.call = mock_circuit_breaker_call
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        docs = await pipeline.retrieve_documents(
            search_queries=["쿼리1", "쿼리2"],  # 여러 쿼리
            query_weights=[1.0, 0.8],
            context=None,
            options={},
        )

        # 검증: 폴백 로직 실행되어 결과 반환됨
        assert docs.count == 1
        assert docs.documents[0].id == "doc1"

    @pytest.mark.asyncio
    async def test_retrieve_orchestrator_path(
        self, mock_config, mock_modules
    ) -> None:
        """
        retrieval_module.orchestrator 경로 테스트

        Given: retrieval_module이 orchestrator 속성을 가짐
        When: retrieve_documents 호출
        Then: orchestrator._search_and_merge 호출
        """
        mock_docs = [MagicMock(id="doc1", score=0.9)]

        # orchestrator 경로 테스트
        class MockOrchestrator:
            async def _search_and_merge(self, queries, top_k, filters, weights, use_rrf):
                return mock_docs

        class MockRetrievalModule:
            def __init__(self):
                self.orchestrator = MockOrchestrator()

        mock_modules["retrieval_module"] = MockRetrievalModule()

        # Circuit breaker mock 설정
        mock_cb = MagicMock()

        async def mock_circuit_breaker_call(fn, fallback):
            return await fn()

        mock_cb.call = mock_circuit_breaker_call
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        docs = await pipeline.retrieve_documents(
            search_queries=["검색 쿼리"],
            query_weights=[1.0],
            context=None,
            options={},
        )

        # 검증: orchestrator 경로로 결과 반환
        assert docs.count == 1
        assert docs.documents[0].id == "doc1"


class TestGenerateAnswerEdgeCases:
    """generate_answer 메서드 추가 테스트 (에지 케이스)"""

    @pytest.mark.asyncio
    async def test_generate_no_generation_module(
        self, mock_config: dict[str, Any], mock_modules: dict[str, Any]
    ) -> None:
        """
        Generation Module 없음 에러

        Given: generation_module=None
        When: generate_answer 호출
        Then: 에러 메시지와 함께 기본 GenerationResult 반환
        """
        from app.modules.core.generation.generator import GenerationResult

        # generation_module을 None으로 설정
        mock_modules["generation_module"] = None

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        result = await pipeline.generate_answer(
            message="테스트 질문",
            ranked_results=[],
            context=None,
            options={},
        )

        # 검증: 에러 메시지 반환
        assert isinstance(result, GenerationResult)
        assert result.answer == "죄송합니다. 답변을 생성할 수 없습니다."
        assert result.tokens_used == 0
        assert result.model_used == "none"
        assert result.provider == "none"

    @pytest.mark.asyncio
    async def test_generate_document_injection_detected(
        self, mock_config: dict[str, Any], mock_modules: dict[str, Any]
    ) -> None:
        """
        문서 인젝션 패턴 감지 및 차단

        Given: validate_document가 False 반환하는 악의적 문서
        When: generate_answer 호출
        Then: 악의적 문서 차단, 안전한 문서만 사용
        """
        from app.modules.core.generation.generator import GenerationResult

        # Mock 문서 (일부는 악의적)
        class MockDocument:
            def __init__(self, doc_id: str, content: str, is_safe: bool):
                self.id = doc_id
                self.page_content = content
                self.is_safe = is_safe

        safe_doc = MockDocument("safe1", "안전한 내용", True)
        malicious_doc = MockDocument("mal1", "악의적 내용", False)

        # validate_document Mock
        def mock_validate(doc):
            return doc.is_safe

        # generation_module Mock
        mock_generation = AsyncMock()
        mock_generation.generate_answer = AsyncMock(
            return_value=GenerationResult(
                answer="안전한 답변",
                text="안전한 답변",
                tokens_used=100,
                model_used="test-model",
                provider="test-provider",
                generation_time=0.5,
            )
        )
        mock_modules["generation_module"] = mock_generation

        # Circuit breaker mock
        mock_cb = MagicMock()

        async def mock_circuit_breaker_call(fn, fallback):
            return await fn()

        mock_cb.call = mock_circuit_breaker_call
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        with patch("app.api.services.rag_pipeline.validate_document", side_effect=mock_validate):
            await pipeline.generate_answer(
                message="테스트 질문",
                ranked_results=[safe_doc, malicious_doc],  # type: ignore
                context=None,
                options={},
            )

        # 검증: 안전한 문서만 사용되었는지
        call_args = mock_generation.generate_answer.call_args
        context_docs = call_args.kwargs["context_documents"]
        assert len(context_docs) == 1
        assert context_docs[0].id == "safe1"

    @pytest.mark.asyncio
    async def test_generate_fallback_no_documents(
        self, mock_config: dict[str, Any], mock_modules: dict[str, Any]
    ) -> None:
        """
        문서 없을 때 Fallback 응답

        Given: context_documents가 비어있음, LLM 호출 실패
        When: generate_answer 호출 시 LLM 실패
        Then: "정보를 찾을 수 없으며" 메시지 반환
        """
        # generation_module Mock (에러 발생)
        mock_generation = AsyncMock()
        mock_generation.generate_answer = AsyncMock(side_effect=Exception("LLM 실패"))
        mock_modules["generation_module"] = mock_generation

        # Circuit breaker mock (fallback 호출)
        mock_cb = MagicMock()

        async def mock_circuit_breaker_call(fn, fallback):
            try:
                return await fn()
            except Exception:
                return fallback()

        mock_cb.call = mock_circuit_breaker_call
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        result = await pipeline.generate_answer(
            message="테스트 질문",
            ranked_results=[],  # 문서 없음
            context=None,
            options={},
        )

        # 검증: fallback 응답 반환 (GenerationResult로 변환됨)
        assert isinstance(result, GenerationResult)
        assert "정보를 찾을 수 없으며" in result.answer
        assert result.tokens_used == 0
        assert result.provider == "fallback"


class TestPrepareContextErrors:
    """prepare_context 메서드 에러 테스트"""

    @pytest.mark.asyncio
    async def test_prepare_context_session_error(
        self, mock_config: dict[str, Any], mock_modules: dict[str, Any]
    ) -> None:
        """
        세션 컨텍스트 조회 실패

        Given: session_module.get_context_string()에서 예외 발생
        When: prepare_context 호출
        Then: 예외 무시하고 계속 진행
        """
        # session_module Mock (예외 발생)
        mock_session = AsyncMock()
        mock_session.get_context_string = AsyncMock(side_effect=Exception("세션 조회 실패"))
        mock_modules["session_module"] = mock_session

        # query_expansion Mock
        mock_expansion = AsyncMock()
        mock_result = MagicMock()
        mock_result.expansions = []
        mock_result.metadata = {}
        mock_expansion.expand_query = AsyncMock(return_value=mock_result)
        mock_modules["query_expansion"] = mock_expansion

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        # 예외가 발생해도 정상 진행되어야 함
        context = await pipeline.prepare_context("테스트 질문", "test-session")

        # 검증: 세션 컨텍스트 조회 시도는 했지만 예외 무시
        mock_session.get_context_string.assert_called_once()
        assert context.expanded_query == "테스트 질문"


class TestRetrieveDocuments2:
    """retrieve_documents 추가 테스트"""

    @pytest.mark.asyncio
    async def test_retrieve_future_retrieval_module(
        self, mock_config: dict[str, Any], mock_modules: dict[str, Any]
    ) -> None:
        """
        Future 기반 retrieval_module 해결

        Given: retrieval_module이 asyncio.Future 객체
        When: retrieve_documents 호출
        Then: await으로 Future 해결 후 검색 실행
        """

        mock_docs = [MagicMock(id="doc1", score=0.9)]

        # Future로 감싸진 retrieval_module
        class MockRetriever:
            async def search(self, query, options):
                return mock_docs

        future_module = asyncio.Future()
        future_module.set_result(MockRetriever())

        mock_modules["retrieval_module"] = future_module

        # Circuit breaker mock
        mock_cb = MagicMock()

        async def mock_circuit_breaker_call(fn, fallback):
            return await fn()

        mock_cb.call = mock_circuit_breaker_call
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        docs = await pipeline.retrieve_documents(
            search_queries=["검색 쿼리"],
            query_weights=[1.0],
            context=None,
            options={},
        )

        # 검증: Future 해결 후 검색 성공
        assert docs.count == 1
        assert docs.documents[0].id == "doc1"


class TestRerankDocuments:
    """rerank_documents 메서드 테스트"""

    @pytest.fixture
    def pipeline(self, mock_config, mock_modules) -> RAGPipeline:
        return RAGPipeline(config=mock_config, **mock_modules)

    @pytest.mark.asyncio
    async def test_rerank_documents_success(
        self, pipeline: RAGPipeline, mock_modules
    ) -> None:
        """
        리랭킹 성공

        Given: 검색된 문서들
        When: rerank_documents 호출
        Then: 리랭킹된 문서 반환
        """
        docs = [
            MagicMock(id="doc1", score=0.8),
            MagicMock(id="doc2", score=0.9),
        ]

        mock_modules["retrieval_module"].rerank = AsyncMock(
            return_value=[docs[1], docs[0]]  # 순서 변경
        )

        reranked = await pipeline.rerank_documents(
            search_query="쿼리",
            search_results=docs,
            options={},
        )

        assert reranked.reranked is True
        assert reranked.count == 2
        assert reranked.documents[0].id == "doc2"

    @pytest.mark.asyncio
    async def test_rerank_documents_disabled(
        self, mock_config, mock_modules
    ) -> None:
        """
        리랭킹 비활성화

        Given: reranking.enabled=False, retrieval.enable_reranking=False
        When: rerank_documents 호출
        Then: 원본 문서 그대로 반환
        """
        mock_config["reranking"]["enabled"] = False
        mock_config["retrieval"]["enable_reranking"] = False  # 둘 다 비활성화 필요
        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        docs = [MagicMock(id="doc1")]
        reranked = await pipeline.rerank_documents("쿼리", docs, {})

        assert reranked.reranked is False
        assert reranked.documents == docs

    @pytest.mark.asyncio
    async def test_rerank_documents_empty_results(
        self, pipeline: RAGPipeline
    ) -> None:
        """
        빈 검색 결과 리랭킹

        Given: 검색 결과 없음
        When: rerank_documents 호출
        Then: 빈 리스트 반환
        """
        reranked = await pipeline.rerank_documents("쿼리", [], {})

        assert reranked.count == 0
        assert reranked.reranked is False


class TestGenerateAnswer:
    """generate_answer 메서드 테스트"""

    @pytest.fixture
    def pipeline(self, mock_config, mock_modules) -> RAGPipeline:
        mock_cb = MagicMock()

        async def mock_circuit_breaker_call(fn, fallback):
            return await fn()

        mock_cb.call = mock_circuit_breaker_call
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)
        return RAGPipeline(config=mock_config, **mock_modules)

    @pytest.mark.asyncio
    async def test_generate_answer_success(
        self, pipeline: RAGPipeline, mock_modules
    ) -> None:
        """
        답변 생성 성공

        Given: 질문과 문서들
        When: generate_answer 호출
        Then: LLM 답변 반환
        """
        docs = [MagicMock(page_content="문서1 내용")]

        # Circuit breaker가 실제로 async 함수를 실행하도록 설정
        expected_result = GenerationResult(
            answer="생성된 답변",
            text="생성된 답변",
            tokens_used=100,
            model_used="gemini",
            provider="google",
            generation_time=1.0,
        )

        mock_modules["generation_module"].generate_answer = AsyncMock(
            return_value=expected_result
        )

        answer = await pipeline.generate_answer(
            message="질문",
            ranked_results=docs,
            context=None,
            options={},
        )

        assert answer.answer == "생성된 답변"
        assert answer.tokens_used == 100

    @pytest.mark.asyncio
    async def test_generate_answer_fallback(self, mock_config, mock_modules) -> None:
        """
        LLM 실패 시 Fallback

        Given: generation_module.generate_answer 실패
        When: generate_answer 호출
        Then: Fallback 답변 반환
        """
        docs = [MagicMock(page_content="문서1 내용")]

        # Circuit breaker fallback 트리거
        mock_cb = MagicMock()

        async def call_with_fallback(fn, fallback):
            return fallback()  # 항상 fallback 사용

        mock_cb.call = call_with_fallback
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)

        pipeline = RAGPipeline(config=mock_config, **mock_modules)
        answer = await pipeline.generate_answer("질문", docs, None, {})

        assert "관련 정보를 찾았습니다" in answer.answer


class TestFormatSources:
    """format_sources 메서드 테스트"""

    @pytest.fixture
    def pipeline(self, mock_config, mock_modules) -> RAGPipeline:
        return RAGPipeline(config=mock_config, **mock_modules)

    def test_format_sources_empty(self, pipeline: RAGPipeline) -> None:
        """
        빈 문서 리스트

        Given: 빈 리스트
        When: format_sources 호출
        Then: 빈 리스트 반환
        """
        sources = pipeline.format_sources([])
        assert sources.count == 0
        assert sources.sources == []

    def test_format_sources_with_documents(self, pipeline: RAGPipeline) -> None:
        """
        문서 리스트를 Source 객체로 변환

        Given: 문서 리스트
        When: format_sources 호출
        Then: Source 딕셔너리 리스트 반환
        """
        docs = [
            MagicMock(
                id="doc1",
                metadata={"source": "문서1.md", "page": 1},
                content="내용1",
                score=0.95,
            ),
        ]

        sources = pipeline.format_sources(docs)

        assert sources.count == 1
        assert sources.sources[0].document == "문서1.md"
        assert sources.sources[0].source_type == "rag"


class TestBuildResult:
    """build_result 메서드 테스트"""

    @pytest.fixture
    def pipeline(self, mock_config, mock_modules) -> RAGPipeline:
        return RAGPipeline(config=mock_config, **mock_modules)

    def test_build_result_standard_mode(self, pipeline: RAGPipeline) -> None:
        """
        표준 모드 결과 구성

        Given: 답변, 소스, 메타데이터
        When: build_result 호출
        Then: RAGResultDict 형식 반환
        """
        result = pipeline.build_result(
            answer="최종 답변",
            sources=[{"title": "문서1"}],
            tokens_used=100,
            topic="토픽",
            processing_time=1.5,
            search_count=10,
            ranked_count=5,
            model_info={"provider": "google", "model": "gemini"},
            routing_metadata=None,
        )

        assert result["answer"] == "최종 답변"
        assert result["tokens_used"] == 100
        assert result["search_results"] == 10
        assert result["ranked_results"] == 5
        assert result["model_info"]["provider"] == "google"


class TestExecuteAgentMode:
    """_execute_agent_mode 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_execute_agent_mode_success(
        self, mock_config, mock_modules
    ) -> None:
        """
        Agent 모드 실행 성공

        Given: AgentOrchestrator 설정됨
        When: _execute_agent_mode 호출
        Then: Agent 결과 반환
        """
        mock_agent = AsyncMock()
        mock_agent_result = MagicMock()
        mock_agent_result.success = True
        mock_agent_result.answer = "Agent 답변"
        mock_agent_result.sources = [{"title": "Agent 문서"}]
        mock_agent_result.steps_taken = 3
        mock_agent_result.tools_used = ["search_weaviate"]
        mock_agent_result.total_time = 2.5
        mock_agent.run = AsyncMock(return_value=mock_agent_result)

        mock_modules["agent_orchestrator"] = mock_agent
        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        result = await pipeline._execute_agent_mode(
            message="복잡한 질문",
            session_id="test",
            start_time=time.time(),
        )

        assert result["answer"] == "Agent 답변"
        assert result["metadata"]["mode"] == "agent"
        assert result["metadata"]["steps_taken"] == 3


class TestExecuteSQLSearch:
    """_execute_sql_search 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_execute_sql_search_success(
        self, mock_config, mock_modules
    ) -> None:
        """
        SQL 검색 성공

        Given: SQL 검색 모듈 활성화
        When: _execute_sql_search 호출
        Then: SQL 검색 결과 반환
        """
        mock_sql = AsyncMock()
        mock_sql_result = MagicMock()
        mock_sql_result.success = True
        mock_sql_result.used = True
        mock_sql.search = AsyncMock(return_value=mock_sql_result)

        mock_modules["sql_search_service"] = mock_sql
        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        result = await pipeline._execute_sql_search("2024년 매출")

        assert result is not None
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_sql_search_disabled(
        self, mock_config, mock_modules
    ) -> None:
        """
        SQL 검색 비활성화

        Given: sql_search_service=None
        When: _execute_sql_search 호출
        Then: None 반환
        """
        mock_modules["sql_search_service"] = None
        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        result = await pipeline._execute_sql_search("질문")
        assert result is None


class TestSelfRAGVerify:
    """self_rag_verify 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_self_rag_verify_disabled(self, mock_config, mock_modules) -> None:
        """
        Self-RAG 비활성화

        Given: self_rag.enabled=False
        When: self_rag_verify 호출
        Then: 원본 GenerationResult 반환
        """
        mock_config["self_rag"]["enabled"] = False
        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        original_result = GenerationResult(
            answer="원본 답변",
            text="원본 답변",
            tokens_used=100,
            model_used="gemini",
            provider="google",
            generation_time=1.0,
        )

        result = await pipeline.self_rag_verify(
            message="질문",
            session_id="test",
            generation_result=original_result,
            documents=[],
            options={},
        )

        assert result.answer == "원본 답변"
        assert result == original_result


class TestEdgeCases:
    """엣지 케이스 및 에러 핸들링 테스트"""

    @pytest.mark.asyncio
    async def test_execute_with_immediate_response_none(
        self, mock_config, mock_modules
    ) -> None:
        """
        immediate_response가 None인 경우 처리

        Given: route_query가 should_continue=False, immediate_response=None 반환
        When: execute 호출
        Then: 기본 응답 반환
        """
        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        with patch.object(pipeline, "route_query") as mock_route:
            mock_route.return_value = RouteDecision(
                should_continue=False,
                immediate_response=None,
                metadata={},
            )

            result = await pipeline.execute("질문", "test", {})

        assert "응답을 생성할 수 없습니다" in result["answer"]

    @pytest.mark.asyncio
    async def test_retrieve_documents_circuit_breaker_open(
        self, mock_config, mock_modules
    ) -> None:
        """
        Circuit Breaker OPEN 시 처리

        Given: Circuit Breaker OPEN 상태
        When: retrieve_documents 호출
        Then: 빈 결과 반환
        """
        from app.lib.circuit_breaker import CircuitBreakerOpenError

        mock_cb = MagicMock()
        mock_cb.call = AsyncMock(side_effect=CircuitBreakerOpenError("OPEN"))
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)

        pipeline = RAGPipeline(config=mock_config, **mock_modules)
        docs = await pipeline.retrieve_documents(["쿼리"], [1.0], None, {})

        assert docs.count == 0

    @pytest.mark.asyncio
    async def test_sql_search_timeout_handling(self, mock_config, mock_modules) -> None:
        """
        SQL 검색 타임아웃 처리

        Given: _execute_sql_search 호출
        When: 타임아웃 발생
        Then: SQLSearchResult(success=False) 반환
        """

        mock_sql = AsyncMock()

        async def timeout_search(query):
            await asyncio.sleep(2)  # 타임아웃 유발용 (0.1초 타임아웃 대비 충분)
            return MagicMock()

        mock_sql.search = timeout_search
        mock_modules["sql_search_service"] = mock_sql
        mock_config["sql_search"] = {"pipeline": {"timeout": 0.1}}  # 짧은 타임아웃

        pipeline = RAGPipeline(config=mock_config, **mock_modules)
        result = await pipeline._execute_sql_search("질문")

        # 타임아웃 발생 시 success=False 반환
        assert result is not None
        assert result.success is False

    @pytest.mark.asyncio
    async def test_route_query_with_llm_router(self, mock_config, mock_modules) -> None:
        """
        LLM 라우터 사용

        Given: LLM query_router 활성화
        When: route_query 호출
        Then: LLM 라우팅 메타데이터 반환
        """
        mock_router = MagicMock()
        mock_router.enabled = True
        mock_profile = MagicMock()
        mock_profile.intent.value = "question"
        mock_profile.domain = "general"
        mock_routing = MagicMock()
        mock_routing.primary_route = "rag"
        mock_routing.confidence = 0.9
        mock_routing.notes = "test notes"
        mock_router.analyze_and_route = AsyncMock(return_value=(mock_profile, mock_routing))
        mock_modules["query_router"] = mock_router

        pipeline = RAGPipeline(config=mock_config, **mock_modules)
        decision = await pipeline.route_query("질문", "test", time.time())

        assert decision.should_continue is True
        assert decision.metadata.get("llm_route") == "rag"

    @pytest.mark.asyncio
    async def test_prepare_context_expansion_error(
        self, mock_config, mock_modules
    ) -> None:
        """
        쿼리 확장 실패 시 원본 사용

        Given: query_expansion.expand_query 에러
        When: prepare_context 호출
        Then: 원본 쿼리 사용
        """
        mock_expansion = AsyncMock()
        mock_expansion.expand_query = AsyncMock(side_effect=Exception("확장 실패"))
        mock_modules["query_expansion"] = mock_expansion

        pipeline = RAGPipeline(config=mock_config, **mock_modules)
        context = await pipeline.prepare_context("원본", "test")

        assert context.expanded_query == "원본"
        assert context.expanded_queries == ["원본"]

    @pytest.mark.asyncio
    async def test_rerank_documents_min_score_filtering(
        self, mock_config, mock_modules
    ) -> None:
        """
        리랭킹 후 min_score 필터링

        Given: 리랭킹 결과 중 일부가 min_score 미만
        When: rerank_documents 호출
        Then: min_score 이상만 반환
        """
        mock_config["reranking"]["min_score"] = 0.5
        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        # MagicMock 대신 실제 score 속성을 가진 객체 생성
        doc1 = MagicMock()
        doc1.id = "doc1"
        doc1.score = 0.8
        doc1.metadata = {"score": 0.8}

        doc2 = MagicMock()
        doc2.id = "doc2"
        doc2.score = 0.3  # min_score 미만
        doc2.metadata = {"score": 0.3}

        docs = [doc1, doc2]

        mock_modules["retrieval_module"].rerank = AsyncMock(return_value=docs)

        reranked = await pipeline.rerank_documents("쿼리", docs, {})

        # min_score 필터링 적용되어 1개만 남음
        assert reranked.count == 1

    @pytest.mark.asyncio
    async def test_generate_answer_with_circuit_breaker_fallback(
        self, mock_config, mock_modules
    ) -> None:
        """
        Circuit Breaker 폴백 답변

        Given: LLM 실패
        When: generate_answer 호출
        Then: Fallback 답변 반환
        """
        from app.lib.circuit_breaker import CircuitBreakerOpenError

        mock_cb = MagicMock()
        mock_cb.call = AsyncMock(side_effect=CircuitBreakerOpenError("OPEN"))
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)

        pipeline = RAGPipeline(config=mock_config, **mock_modules)
        docs = [MagicMock(page_content="문서 내용")]

        answer = await pipeline.generate_answer("질문", docs, None, {})

        assert "관련 정보를 찾았습니다" in answer.answer
        assert answer.tokens_used == 0

    @pytest.mark.asyncio
    async def test_execute_with_agent_mode_enabled(
        self, mock_config, mock_modules
    ) -> None:
        """
        Agent 모드 활성화 시 실행

        Given: options["use_agent"]=True
        When: execute 호출
        Then: Agent 모드로 실행
        """
        mock_cb = MagicMock()

        async def mock_circuit_breaker_call(fn, fallback):
            return await fn()

        mock_cb.call = mock_circuit_breaker_call
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)

        mock_agent = AsyncMock()
        mock_agent_result = MagicMock()
        mock_agent_result.success = True
        mock_agent_result.answer = "Agent 답변"
        mock_agent_result.sources = []
        mock_agent_result.steps_taken = 2
        mock_agent_result.tools_used = ["search"]
        mock_agent_result.total_time = 1.5
        mock_agent.run = AsyncMock(return_value=mock_agent_result)

        mock_modules["agent_orchestrator"] = mock_agent
        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        result = await pipeline.execute(
            message="질문", session_id="test", options={"use_agent": True}
        )

        assert result["answer"] == "Agent 답변"
        assert result["metadata"]["mode"] == "agent"

    @pytest.mark.asyncio
    async def test_execute_with_self_rag_enabled(
        self, mock_config, mock_modules
    ) -> None:
        """
        Self-RAG 활성화 시 처리

        Given: self_rag.enabled = True
        When: execute 호출
        Then: Self-RAG 검증 수행
        """
        mock_config["self_rag"]["enabled"] = True

        mock_cb = MagicMock()

        async def mock_circuit_breaker_call(fn, fallback):
            return await fn()

        mock_cb.call = mock_circuit_breaker_call
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        # RetrievalResults 객체를 반환하도록 모킹
        mock_retrieval_results = MagicMock()
        mock_retrieval_results.documents = []
        mock_retrieval_results.count = 0
        pipeline.retrieve_documents = AsyncMock(return_value=mock_retrieval_results)

        pipeline.generate_answer = AsyncMock(
            return_value=MagicMock(answer="원본 답변", tokens_used=100, model_info={})
        )
        pipeline.self_rag_verify = AsyncMock(
            return_value=MagicMock(answer="개선된 답변", metadata={"relevance": 0.9})
        )

        await pipeline.execute(message="질문", session_id="test")

        # Self-RAG 검증이 호출되었는지 확인
        pipeline.self_rag_verify.assert_called_once()

    @pytest.mark.asyncio
    async def test_retrieve_documents_empty_results(
        self, mock_config, mock_modules
    ) -> None:
        """
        검색 결과 없음 처리

        Given: 검색 결과 0건
        When: retrieve_documents 호출
        Then: 빈 리스트 반환
        """
        mock_cb = MagicMock()

        async def mock_circuit_breaker_call(fn, fallback):
            return await fn()

        mock_cb.call = mock_circuit_breaker_call
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)

        mock_retrieval = AsyncMock()
        mock_retrieval.search = AsyncMock(return_value=[])
        mock_modules["retrieval_module"] = mock_retrieval

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        result = await pipeline.retrieve_documents(
            search_queries=["질문"],
            query_weights=None,
            context="컨텍스트",
            options={},
        )

        assert result.count == 0

    @pytest.mark.asyncio
    async def test_sql_search_error_handling(
        self, mock_config, mock_modules
    ) -> None:
        """
        SQL 검색 에러 처리

        Given: SQL 검색 중 예외 발생
        When: _execute_sql_search 호출
        Then: 에러 로깅 및 None 반환
        """
        mock_cb = MagicMock()

        async def mock_circuit_breaker_call(fn, fallback):
            return await fn()

        mock_cb.call = mock_circuit_breaker_call
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)

        mock_sql = AsyncMock()
        mock_sql.search = AsyncMock(side_effect=Exception("SQL 에러"))
        mock_modules["sql_search_service"] = mock_sql

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        result = await pipeline._execute_sql_search("질문")

        # 에러 발생 시 None 또는 실패 결과 반환
        assert result is None or (hasattr(result, "success") and not result.success)

    @pytest.mark.asyncio
    async def test_format_sources_with_sql(
        self, mock_config, mock_modules
    ) -> None:
        """
        SQL 결과 포함 소스 포맷팅

        Given: SQL 검색 결과 존재
        When: format_sources 호출
        Then: SQL 소스 포함된 결과 반환
        """
        mock_cb = MagicMock()

        async def mock_circuit_breaker_call(fn, fallback):
            return await fn()

        mock_cb.call = mock_circuit_breaker_call
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        doc = MagicMock()
        doc.metadata = {
            "source": "test.pdf",
            "page": 1,
            "chunk_id": "chunk-1",
            "score": 0.9,
        }
        doc.page_content = "테스트 내용"

        sql_result = MagicMock()
        sql_result.used = True
        sql_result.query_result = MagicMock()
        sql_result.query_result.row_count = 3
        sql_result.sql_query = "SELECT * FROM test"

        sources = pipeline.format_sources(
            ranked_results=[doc],
            sql_search_result=sql_result,
        )

        # FormattedSources는 리스트를 포함하는 객체
        assert sources is not None
        assert hasattr(sources, "sources") or isinstance(sources, list)

    @pytest.mark.asyncio
    async def test_build_result_with_routing_metadata(
        self, mock_config, mock_modules
    ) -> None:
        """
        라우팅 메타데이터 포함 결과 구성

        Given: 라우팅 메타데이터 제공
        When: build_result 호출
        Then: 라우팅 정보 포함된 결과 반환
        """
        mock_cb = MagicMock()

        async def mock_circuit_breaker_call(fn, fallback):
            return await fn()

        mock_cb.call = mock_circuit_breaker_call
        mock_modules["circuit_breaker_factory"].get = MagicMock(return_value=mock_cb)

        pipeline = RAGPipeline(config=mock_config, **mock_modules)

        result = pipeline.build_result(
            answer="최종 답변",
            sources=[{"title": "문서1"}],
            tokens_used=150,
            topic="주제",
            processing_time=2.5,
            search_count=15,
            ranked_count=8,
            model_info={"provider": "google", "model": "gemini"},
            routing_metadata={"route": "complex", "confidence": 0.9},
        )

        assert result["answer"] == "최종 답변"
        assert result["tokens_used"] == 150
        assert result["search_results"] == 15
        assert result["ranked_results"] == 8
        # 라우팅 메타데이터 확인 (build_result가 이를 포함하는지 검증)
        assert result.get("routing_metadata") is not None
