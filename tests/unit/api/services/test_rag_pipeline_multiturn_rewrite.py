"""멀티턴 standalone query rewrite 단위 테스트.

검증 대상:
1. 게이트(_needs_standalone_rewrite): 대명사/지시어/짧은 질문만 재작성 대상.
2. 정제(_postprocess_rewritten_query): 라벨/따옴표/여러 줄 방어.
3. 재작성(_rewrite_standalone_query): 비활성/맥락 없음/factory 없음 시 원본,
   LLM 실패·비정상 결과 시 graceful 폴백, 성공 시 재작성 질문 반환.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.services.rag_pipeline import RAGPipeline


@pytest.fixture
def mock_modules() -> dict[str, Any]:
    """rewrite 테스트용 Mock 모듈."""
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


def _build_pipeline(
    mock_modules: dict[str, Any],
    *,
    enabled: bool = True,
    llm_factory: Any | None = None,
    rewrite_overrides: dict[str, Any] | None = None,
) -> RAGPipeline:
    rewrite_config: dict[str, Any] = {"enabled": enabled, "provider": "google"}
    if rewrite_overrides:
        rewrite_config.update(rewrite_overrides)
    config = {
        "rag": {
            "top_k": 10,
            "rerank_top_k": 5,
            "multiturn_rewrite": rewrite_config,
        },
        "retrieval": {"top_k": 10, "min_score": 0.05},
        "privacy": {"enabled": False},
    }
    return RAGPipeline(config=config, llm_factory=llm_factory, **mock_modules)


class TestNeedsStandaloneRewriteGate:
    """휴리스틱 게이트 판정 검증."""

    def test_pronoun_dependent_question_needs_rewrite(self, mock_modules):
        pipeline = _build_pipeline(mock_modules)
        assert pipeline._needs_standalone_rewrite("그건 신청 자격이 어떻게 되나요 자세히 알려주세요") is True

    def test_start_conjunction_needs_rewrite(self, mock_modules):
        pipeline = _build_pipeline(mock_modules)
        assert pipeline._needs_standalone_rewrite("그리고 신청 기한과 제출 서류 목록도 알려주세요") is True

    def test_mid_sentence_conjunction_is_standalone(self, mock_modules):
        pipeline = _build_pipeline(mock_modules)
        # 문장 중간의 "그리고"는 후속 신호가 아니다 (어절 6개 이상으로 충분히 김)
        assert (
            pipeline._needs_standalone_rewrite(
                "청년 지원 사업의 신청 자격 그리고 제출 서류 목록을 알려주세요"
            )
            is False
        )

    def test_short_question_needs_rewrite(self, mock_modules):
        pipeline = _build_pipeline(mock_modules)
        assert pipeline._needs_standalone_rewrite("정규직 요건은?") is True

    def test_long_specific_question_is_standalone(self, mock_modules):
        pipeline = _build_pipeline(mock_modules)
        assert (
            pipeline._needs_standalone_rewrite(
                "청년 내일채움공제 프로그램의 신청 자격과 지원 금액을 자세히 알려주세요"
            )
            is False
        )

    def test_empty_message_skips_rewrite(self, mock_modules):
        pipeline = _build_pipeline(mock_modules)
        assert pipeline._needs_standalone_rewrite("   ") is False

    def test_patterns_overridable_via_config(self, mock_modules):
        # 언어별 패턴 오버라이드 (예: 영어)
        pipeline = _build_pipeline(
            mock_modules,
            rewrite_overrides={
                "followup_dependent_patterns": ["that one", "it"],
                "followup_start_patterns": ["and", "also"],
                "short_question_max_words": 3,
            },
        )
        assert pipeline._needs_standalone_rewrite("what about that one program details") is True
        assert pipeline._needs_standalone_rewrite("and what is the deadline for application") is True
        assert (
            pipeline._needs_standalone_rewrite(
                "please explain the youth employment support program requirements"
            )
            is False
        )


class TestPostprocessRewrittenQuery:
    """LLM 재작성 결과 정제 검증."""

    def test_strips_label_prefix_and_quotes(self, mock_modules):
        pipeline = _build_pipeline(mock_modules)
        assert (
            pipeline._postprocess_rewritten_query('재작성된 질문: "청년 사업 신청 자격은?"')
            == "청년 사업 신청 자격은?"
        )

    def test_takes_first_non_empty_line(self, mock_modules):
        pipeline = _build_pipeline(mock_modules)
        assert (
            pipeline._postprocess_rewritten_query("\n\n청년 사업 신청 자격은?\n부가 설명입니다.")
            == "청년 사업 신청 자격은?"
        )

    def test_none_and_empty_return_empty(self, mock_modules):
        pipeline = _build_pipeline(mock_modules)
        assert pipeline._postprocess_rewritten_query(None) == ""
        assert pipeline._postprocess_rewritten_query("   \n  ") == ""


class TestRewriteStandaloneQuery:
    """재작성 실행/폴백 동작 검증."""

    @pytest.mark.asyncio
    async def test_disabled_returns_original(self, mock_modules):
        factory = MagicMock()
        factory.generate_with_fallback = AsyncMock()
        pipeline = _build_pipeline(mock_modules, enabled=False, llm_factory=factory)

        result = await pipeline._rewrite_standalone_query("그건 뭐야?", "직전 대화")

        assert result == "그건 뭐야?"
        factory.generate_with_fallback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_session_context_returns_original(self, mock_modules):
        factory = MagicMock()
        factory.generate_with_fallback = AsyncMock()
        pipeline = _build_pipeline(mock_modules, llm_factory=factory)

        result = await pipeline._rewrite_standalone_query("그건 뭐야?", None)

        assert result == "그건 뭐야?"
        factory.generate_with_fallback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_llm_factory_returns_original(self, mock_modules):
        pipeline = _build_pipeline(mock_modules, llm_factory=None)

        result = await pipeline._rewrite_standalone_query("그건 뭐야?", "직전 대화")

        assert result == "그건 뭐야?"

    @pytest.mark.asyncio
    async def test_standalone_question_skips_llm_call(self, mock_modules):
        factory = MagicMock()
        factory.generate_with_fallback = AsyncMock()
        pipeline = _build_pipeline(mock_modules, llm_factory=factory)

        message = "청년 내일채움공제 프로그램의 신청 자격과 지원 금액을 자세히 알려주세요"
        result = await pipeline._rewrite_standalone_query(message, "직전 대화")

        assert result == message
        factory.generate_with_fallback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_successful_rewrite_returns_rewritten(self, mock_modules):
        factory = MagicMock()
        factory.generate_with_fallback = AsyncMock(
            return_value=("청년 내일채움공제의 신청 자격은 무엇인가요?", "google")
        )
        pipeline = _build_pipeline(mock_modules, llm_factory=factory)

        result = await pipeline._rewrite_standalone_query("그건 자격이 어떻게 돼?", "청년 내일채움공제 얘기 중")

        assert result == "청년 내일채움공제의 신청 자격은 무엇인가요?"
        factory.generate_with_fallback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_original(self, mock_modules):
        factory = MagicMock()
        factory.generate_with_fallback = AsyncMock(side_effect=RuntimeError("LLM 불가"))
        pipeline = _build_pipeline(mock_modules, llm_factory=factory)

        result = await pipeline._rewrite_standalone_query("그건 자격이 어떻게 돼?", "직전 대화")

        assert result == "그건 자격이 어떻게 돼?"

    @pytest.mark.asyncio
    async def test_empty_llm_result_falls_back_to_original(self, mock_modules):
        factory = MagicMock()
        factory.generate_with_fallback = AsyncMock(return_value=("", "google"))
        pipeline = _build_pipeline(mock_modules, llm_factory=factory)

        result = await pipeline._rewrite_standalone_query("그건 자격이 어떻게 돼?", "직전 대화")

        assert result == "그건 자격이 어떻게 돼?"

    @pytest.mark.asyncio
    async def test_abnormally_long_result_falls_back_to_original(self, mock_modules):
        factory = MagicMock()
        factory.generate_with_fallback = AsyncMock(return_value=("긴" * 500, "google"))
        pipeline = _build_pipeline(mock_modules, llm_factory=factory)

        result = await pipeline._rewrite_standalone_query("그건 자격이 어떻게 돼?", "직전 대화")

        assert result == "그건 자격이 어떻게 돼?"


class TestPromptPlaceholderSubstitution:
    """프롬프트 플레이스홀더 치환 안전성 검증 (치환 값 재스캔 차단)."""

    @pytest.mark.asyncio
    async def test_message_token_in_context_is_not_resubstituted(self, mock_modules):
        """직전 대화에 리터럴 '{message}'가 있어도 컨텍스트 블록이 원문 그대로 보존된다.

        순차 replace 방식은 session_context 치환 결과를 재스캔하므로,
        사용자가 제어 가능한 직전 대화에 '{message}' 토큰이 있으면
        컨텍스트 블록 안에 새 질문이 주입된다(프롬프트 인젝션 벡터).
        """
        factory = MagicMock()
        factory.generate_with_fallback = AsyncMock(return_value=("재작성된 질문", "google"))
        pipeline = _build_pipeline(mock_modules, llm_factory=factory)

        session_context = (
            "User: 프롬프트에 {message} 토큰을 그대로 쓰면 어떻게 되나요?\n"
            "Assistant: 치환자(placeholder)로 동작합니다."
        )
        await pipeline._rewrite_standalone_query("그건 자격이 어떻게 돼?", session_context)

        prompt = factory.generate_with_fallback.call_args.kwargs["prompt"]
        # 컨텍스트 블록이 리터럴 '{message}'를 포함한 원문 그대로 보존되어야 한다
        assert session_context in prompt
        # 새 질문은 템플릿의 질문 슬롯 1곳에만 들어가야 한다 (컨텍스트 내 주입 금지)
        assert prompt.count("그건 자격이 어떻게 돼?") == 1

    @pytest.mark.asyncio
    async def test_context_token_in_message_is_not_resubstituted(self, mock_modules):
        """새 질문에 리터럴 '{session_context}'가 있어도 재치환되지 않는다."""
        factory = MagicMock()
        factory.generate_with_fallback = AsyncMock(return_value=("재작성된 질문", "google"))
        pipeline = _build_pipeline(mock_modules, llm_factory=factory)

        # 템플릿 라벨과 충돌하지 않는 고유한 컨텍스트 문자열 사용
        context = "이전-대화-컨텍스트-원문-2026"
        message = "그건 {session_context} 토큰이랑 뭐가 달라?"
        await pipeline._rewrite_standalone_query(message, context)

        prompt = factory.generate_with_fallback.call_args.kwargs["prompt"]
        # 질문 원문(리터럴 '{session_context}' 포함)이 그대로 보존되어야 한다
        assert message in prompt
        # 직전 대화 맥락은 템플릿의 컨텍스트 슬롯 1곳에만 들어가야 한다
        assert prompt.count(context) == 1


class TestMultiturnRewritePromptTemplate:
    """재작성 프롬프트 템플릿 설정 이관 검증."""

    def test_default_prompt_template_is_korean(self, mock_modules):
        """설정이 없으면 한국어 기본 프롬프트 템플릿을 사용한다(하위 호환)."""
        pipeline = _build_pipeline(mock_modules)
        assert "후속 질문" in pipeline.multiturn_rewrite_prompt_template
        assert "standalone" in pipeline.multiturn_rewrite_prompt_template
        assert "{session_context}" in pipeline.multiturn_rewrite_prompt_template
        assert "{message}" in pipeline.multiturn_rewrite_prompt_template

    @pytest.mark.asyncio
    async def test_default_prompt_passed_to_llm(self, mock_modules):
        """기본 템플릿이 직전 맥락/후속 질문을 채워 LLM에 전달된다."""
        factory = MagicMock()
        factory.generate_with_fallback = AsyncMock(
            return_value=("재작성된 질문", "google")
        )
        pipeline = _build_pipeline(mock_modules, llm_factory=factory)

        await pipeline._rewrite_standalone_query("그건 자격이 어떻게 돼?", "청년 공제 얘기 중")

        prompt = factory.generate_with_fallback.call_args.kwargs["prompt"]
        # 한국어 기본 프롬프트 + 맥락/질문 치환 확인
        assert "당신은 멀티턴 대화의 후속 질문을" in prompt
        assert "청년 공제 얘기 중" in prompt
        assert "그건 자격이 어떻게 돼?" in prompt
        # 플레이스홀더가 모두 치환됐는지 확인
        assert "{session_context}" not in prompt
        assert "{message}" not in prompt

    @pytest.mark.asyncio
    async def test_custom_prompt_template_overrides(self, mock_modules):
        """설정으로 외국어 프롬프트 템플릿을 주입하면 그 템플릿이 사용된다."""
        custom = (
            "You rewrite follow-up questions into standalone search queries.\n"
            "Context:\n{session_context}\n"
            "Follow-up:\n{message}\n"
            "Rewritten:"
        )
        factory = MagicMock()
        factory.generate_with_fallback = AsyncMock(
            return_value=("rewritten query", "google")
        )
        pipeline = _build_pipeline(
            mock_modules,
            llm_factory=factory,
            rewrite_overrides={"prompt_template": custom},
        )

        await pipeline._rewrite_standalone_query("그건 자격이 어떻게 돼?", "context here")

        prompt = factory.generate_with_fallback.call_args.kwargs["prompt"]
        assert "You rewrite follow-up questions into standalone search queries" in prompt
        assert "context here" in prompt
        assert "그건 자격이 어떻게 돼?" in prompt
        # 한국어 기본 프롬프트는 들어가지 않는다
        assert "당신은 멀티턴 대화의 후속 질문을" not in prompt
