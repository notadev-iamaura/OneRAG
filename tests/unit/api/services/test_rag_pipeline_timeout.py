"""파이프라인 timeout budget 단위 테스트.

검증 대상:
1. stage가 deadline을 초과하면 무한 대기 없이 PipelineTimeoutError(PIPE-001)로 실패.
2. 정상(빠른) 요청은 timeout에 걸리지 않고 정상 통과(회귀 가드).
3. enabled=false면 wait_for 래핑을 건너뛰어 기존(무제한) 동작 유지.
4. 총 budget 초과 시 PIPE-002로 실패.
5. 스트리밍 전용 총 예산(_remaining_stream_budget) 로드·계산 검증.

각 stage는 execute() 내부에서 asyncio.wait_for로 감싸지므로,
stage 메서드를 느린 코루틴/빠른 코루틴으로 patch하여 동작을 검증한다.
"""

from __future__ import annotations

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
from app.lib.errors import ErrorCode, PipelineTimeoutError
from app.modules.core.generation.generator import GenerationResult


@pytest.fixture
def mock_modules() -> dict[str, Any]:
    """timeout 테스트용 Mock 모듈."""
    return {
        "query_router": MagicMock(enabled=False),
        "query_expansion": None,
        "retrieval_module": AsyncMock(),
        "generation_module": AsyncMock(),
        "session_module": None,
        "self_rag_module": None,
        "extract_topic_func": lambda x: x[:10],
        "circuit_breaker_factory": MagicMock(),
        "cost_tracker": MagicMock(),
        "performance_metrics": MagicMock(),
        "sql_search_service": None,
        "agent_orchestrator": None,
    }


def _base_config(
    *,
    enabled: bool = True,
    stages: dict[str, float] | None = None,
    total_budget: float = 270.0,
) -> dict[str, Any]:
    """pipeline_timeout 설정을 포함한 기본 config."""
    return {
        "generation": {"default_provider": "openrouter", "temperature": 0.2},
        "rag": {
            "top_k": 10,
            "rerank_top_k": 5,
            "score_normalization": {"enabled": True},
            "pipeline_timeout": {
                "enabled": enabled,
                "total_budget_seconds": total_budget,
                "stages": stages
                or {
                    "route_query": 30,
                    "prepare_context": 30,
                    "retrieve_documents": 60,
                    "rerank_documents": 30,
                    "generate_answer": 180,
                    "self_rag_verify": 60,
                },
                "stream_first_chunk_seconds": 90,
            },
        },
        "retrieval": {"top_k": 10, "min_score": 0.05, "enable_reranking": True},
        "reranking": {"enabled": True, "min_score": 0.05},
        "privacy": {"enabled": False},
        "self_rag": {"enabled": False},
    }


def _patch_fast_stages(pipeline: RAGPipeline) -> Any:
    """모든 stage를 빠르게 반환하도록 patch하는 컨텍스트 매니저 묶음 생성용 헬퍼."""
    return (
        patch.object(pipeline, "route_query"),
        patch.object(pipeline, "prepare_context"),
        patch.object(pipeline, "_execute_parallel_search"),
        patch.object(pipeline, "rerank_documents"),
        patch.object(pipeline, "expand_context_documents"),
        patch.object(pipeline, "generate_answer"),
        patch.object(pipeline, "self_rag_verify"),
        patch.object(pipeline, "format_sources"),
        patch.object(pipeline, "build_result"),
    )


def _wire_stage_mocks(
    mock_route: Any,
    mock_prepare: Any,
    mock_search: Any,
    mock_rerank: Any,
    mock_expand: Any,
    mock_generate: Any,
    mock_self_rag: Any,
    mock_format: Any,
    mock_build: Any,
) -> None:
    """patch한 stage mock들의 정상 반환값을 설정한다."""
    mock_route.return_value = RouteDecision(should_continue=True, metadata={})
    mock_prepare.return_value = PreparedContext(
        session_context=None,
        expanded_query="확장된 쿼리",
        original_query="원본 쿼리",
        expanded_queries=["확장된 쿼리"],
        query_weights=[1.0],
    )
    mock_search.return_value = (
        RetrievalResults(documents=[MagicMock(id="doc1")], count=1),
        None,
    )
    mock_rerank.return_value = RerankResults(
        documents=[MagicMock(id="doc1")], count=1, reranked=True
    )
    mock_expand.return_value = [MagicMock(id="doc1")]
    gen = GenerationResult(
        answer="정상 답변",
        text="정상 답변",
        tokens_used=100,
        model_used="gemini-2.5-flash",
        provider="google",
        generation_time=1.0,
    )
    mock_generate.return_value = gen
    mock_self_rag.return_value = gen
    mock_format.return_value = FormattedSources(sources=[{"title": "문서1"}], count=1)
    mock_build.return_value = {
        "answer": "정상 답변",
        "sources": [{"title": "문서1"}],
        "metadata": {},
        "processing_time": 1.0,
    }


class TestStageTimeout:
    """stage별 deadline 동작 검증."""

    @pytest.mark.asyncio
    async def test_slow_stage_raises_pipeline_timeout(
        self, mock_modules: dict[str, Any]
    ) -> None:
        """검색 stage가 deadline을 초과하면 PIPE-001로 즉시 실패(무한 대기 금지)."""
        # retrieve_documents에 0.05초 deadline을 주고, 검색을 5초 걸리게 만든다.
        config = _base_config(
            stages={
                "route_query": 30,
                "prepare_context": 30,
                "retrieve_documents": 0.05,  # 매우 짧게
                "rerank_documents": 30,
                "generate_answer": 180,
                "self_rag_verify": 60,
            }
        )
        pipeline = RAGPipeline(config=config, **mock_modules)

        async def slow_search(*args: Any, **kwargs: Any) -> Any:
            await asyncio.sleep(5)
            return (RetrievalResults(documents=[], count=0), None)

        patches = _patch_fast_stages(pipeline)
        with (
            patches[0] as mock_route,
            patches[1] as mock_prepare,
            patches[2] as mock_search,
            patches[3] as mock_rerank,
            patches[4] as mock_expand,
            patches[5] as mock_generate,
            patches[6] as mock_self_rag,
            patches[7] as mock_format,
            patches[8] as mock_build,
        ):
            _wire_stage_mocks(
                mock_route,
                mock_prepare,
                mock_search,
                mock_rerank,
                mock_expand,
                mock_generate,
                mock_self_rag,
                mock_format,
                mock_build,
            )
            mock_search.side_effect = slow_search

            start = time.monotonic()
            with pytest.raises(PipelineTimeoutError) as exc_info:
                await pipeline.execute(
                    message="테스트 질문",
                    session_id="s1",
                    options={"use_agent": False},
                )
            elapsed = time.monotonic() - start

        # 무한 대기가 아니라 deadline 직후에 끊겨야 한다(5초 sleep 전에).
        assert elapsed < 2.0
        # 어느 stage에서 초과됐는지 명확해야 한다.
        assert exc_info.value.error_code == ErrorCode.PIPELINE_STAGE_TIMEOUT.value
        assert exc_info.value.context.get("stage") == "retrieve_documents"

    @pytest.mark.asyncio
    async def test_fast_request_passes_without_timeout(
        self, mock_modules: dict[str, Any]
    ) -> None:
        """정상(빠른) 요청은 timeout에 걸리지 않고 통과한다(회귀 가드)."""
        config = _base_config()  # 넉넉한 기본 예산
        pipeline = RAGPipeline(config=config, **mock_modules)

        patches = _patch_fast_stages(pipeline)
        with (
            patches[0] as mock_route,
            patches[1] as mock_prepare,
            patches[2] as mock_search,
            patches[3] as mock_rerank,
            patches[4] as mock_expand,
            patches[5] as mock_generate,
            patches[6] as mock_self_rag,
            patches[7] as mock_format,
            patches[8] as mock_build,
        ):
            _wire_stage_mocks(
                mock_route,
                mock_prepare,
                mock_search,
                mock_rerank,
                mock_expand,
                mock_generate,
                mock_self_rag,
                mock_format,
                mock_build,
            )
            result = await pipeline.execute(
                message="테스트 질문",
                session_id="s1",
                options={"use_agent": False},
            )

        assert result["answer"] == "정상 답변"

    @pytest.mark.asyncio
    async def test_disabled_skips_timeout_wrapping(
        self, mock_modules: dict[str, Any]
    ) -> None:
        """enabled=false면 느린 stage도 timeout 없이 통과(기존 동작 유지)."""
        # 매우 짧은 stage 값을 줘도 enabled=false면 무시되어야 한다.
        config = _base_config(
            enabled=False,
            stages={
                "route_query": 0.01,
                "prepare_context": 0.01,
                "retrieve_documents": 0.01,
                "rerank_documents": 0.01,
                "generate_answer": 0.01,
                "self_rag_verify": 0.01,
            },
        )
        pipeline = RAGPipeline(config=config, **mock_modules)

        async def slowish_search(*args: Any, **kwargs: Any) -> Any:
            await asyncio.sleep(0.1)  # stage 값(0.01)보다 길지만 disabled라 통과해야 함
            return (RetrievalResults(documents=[MagicMock(id="doc1")], count=1), None)

        patches = _patch_fast_stages(pipeline)
        with (
            patches[0] as mock_route,
            patches[1] as mock_prepare,
            patches[2] as mock_search,
            patches[3] as mock_rerank,
            patches[4] as mock_expand,
            patches[5] as mock_generate,
            patches[6] as mock_self_rag,
            patches[7] as mock_format,
            patches[8] as mock_build,
        ):
            _wire_stage_mocks(
                mock_route,
                mock_prepare,
                mock_search,
                mock_rerank,
                mock_expand,
                mock_generate,
                mock_self_rag,
                mock_format,
                mock_build,
            )
            mock_search.side_effect = slowish_search

            result = await pipeline.execute(
                message="테스트 질문",
                session_id="s1",
                options={"use_agent": False},
            )

        assert result["answer"] == "정상 답변"


class TestTotalBudget:
    """총 budget 동작 검증."""

    @pytest.mark.asyncio
    async def test_total_budget_exceeded_raises_pipe_002(
        self, mock_modules: dict[str, Any]
    ) -> None:
        """누적 처리 시간이 총 budget을 넘으면 PIPE-002로 실패한다."""
        # 총 budget을 0.1초로 매우 작게, 각 stage deadline은 넉넉하게 둔다.
        # 각 stage가 조금씩 지연되면 stage cap엔 안 걸리지만 total은 넘긴다.
        config = _base_config(
            total_budget=0.1,
            stages={
                "route_query": 30,
                "prepare_context": 30,
                "retrieve_documents": 30,
                "rerank_documents": 30,
                "generate_answer": 30,
                "self_rag_verify": 30,
            },
        )
        pipeline = RAGPipeline(config=config, **mock_modules)

        async def slow_prepare(*args: Any, **kwargs: Any) -> PreparedContext:
            await asyncio.sleep(1.0)  # total budget(0.1초)보다 길게
            return PreparedContext(
                session_context=None,
                expanded_query="q",
                original_query="q",
                expanded_queries=["q"],
                query_weights=[1.0],
            )

        patches = _patch_fast_stages(pipeline)
        with (
            patches[0] as mock_route,
            patches[1] as mock_prepare,
            patches[2] as mock_search,
            patches[3] as mock_rerank,
            patches[4] as mock_expand,
            patches[5] as mock_generate,
            patches[6] as mock_self_rag,
            patches[7] as mock_format,
            patches[8] as mock_build,
        ):
            _wire_stage_mocks(
                mock_route,
                mock_prepare,
                mock_search,
                mock_rerank,
                mock_expand,
                mock_generate,
                mock_self_rag,
                mock_format,
                mock_build,
            )
            mock_prepare.side_effect = slow_prepare

            start = time.monotonic()
            with pytest.raises(PipelineTimeoutError) as exc_info:
                await pipeline.execute(
                    message="테스트 질문",
                    session_id="s1",
                    options={"use_agent": False},
                )
            elapsed = time.monotonic() - start

        assert elapsed < 2.0
        assert exc_info.value.error_code == ErrorCode.PIPELINE_TOTAL_TIMEOUT.value


class TestStreamTotalBudget:
    """스트리밍 전용 총 예산(_remaining_stream_budget / stream_total_budget_seconds) 검증."""

    def _config_with_stream_budget(self, value: Any) -> dict[str, Any]:
        config = _base_config()
        config["rag"]["pipeline_timeout"]["stream_total_budget_seconds"] = value
        return config

    def test_loads_stream_total_budget(self, mock_modules: dict[str, Any]) -> None:
        pipeline = RAGPipeline(config=self._config_with_stream_budget(600), **mock_modules)
        assert pipeline.pipeline_stream_total_budget_seconds == 600.0

    def test_remaining_stream_budget_returns_remaining(
        self, mock_modules: dict[str, Any]
    ) -> None:
        pipeline = RAGPipeline(config=self._config_with_stream_budget(600), **mock_modules)
        # 방금 시작 → 남은 예산은 600에 근접(경과시간만큼만 차감).
        remaining = pipeline._remaining_stream_budget(time.time())
        assert remaining is not None
        assert 595.0 < remaining <= 600.0

    def test_remaining_stream_budget_none_when_unset(
        self, mock_modules: dict[str, Any]
    ) -> None:
        # stream_total_budget_seconds 미설정 → None(무제한, stage deadline만 적용).
        pipeline = RAGPipeline(config=_base_config(), **mock_modules)
        assert pipeline.pipeline_stream_total_budget_seconds is None
        assert pipeline._remaining_stream_budget(time.time()) is None

    def test_remaining_stream_budget_zero_when_exceeded(
        self, mock_modules: dict[str, Any]
    ) -> None:
        pipeline = RAGPipeline(config=self._config_with_stream_budget(600), **mock_modules)
        # 시작 시각을 700초 전으로 두면 예산(600) 초과 → 0.0.
        assert pipeline._remaining_stream_budget(time.time() - 700) == 0.0

    def test_remaining_stream_budget_none_when_timeout_disabled(
        self, mock_modules: dict[str, Any]
    ) -> None:
        config = _base_config(enabled=False)
        config["rag"]["pipeline_timeout"]["stream_total_budget_seconds"] = 600
        pipeline = RAGPipeline(config=config, **mock_modules)
        # enabled=false면 예산값이 있어도 None(기존 무제한 동작 유지).
        assert pipeline._remaining_stream_budget(time.time()) is None
