"""
InternalEvaluator 프롬프트 외부화 회귀/오버라이드 테스트

코드 _build_prompt에 하드코딩됐던 Self-RAG 평가 프롬프트를
config(prompt_template)로 외부화한 것이 다음을 만족하는지 검증한다
(self_rag/evaluator, llm_entity_extractor 패턴과 동일):

(a) config 미설정 시 코드 내장 한국어 기본 프롬프트가 사용됨 (회귀 0)
(b) config 오버라이드 시 코드 변경 없이 프롬프트가 바뀜
(c) 변수 치환({query}/{context_text}/{answer}) 보존
"""

from unittest.mock import MagicMock

from app.modules.core.evaluation.internal_evaluator import (
    DEFAULT_EVALUATION_PROMPT_TEMPLATE,
    InternalEvaluator,
)


class TestInternalEvaluatorPromptDefault:
    """(a)(c) 미설정 시 코드 내장 한국어 기본 프롬프트 사용 (회귀 0)"""

    def test_default_uses_builtin_prompt(self) -> None:
        evaluator = InternalEvaluator(llm_client=MagicMock())
        # 미설정 시 내부 템플릿 = 코드 내장 기본 프롬프트
        assert evaluator._prompt_template == DEFAULT_EVALUATION_PROMPT_TEMPLATE

        prompt = evaluator._build_prompt(
            query="테스트 질문입니다",
            answer="테스트 답변입니다",
            context=["첫 번째 컨텍스트", "두 번째 컨텍스트"],
        )
        # 한국어 평가 기준이 그대로 전달됨 (회귀 0)
        assert "답변의 품질을 객관적으로 평가하는 전문가" in prompt
        assert "faithfulness" in prompt
        assert "relevance" in prompt
        # (c) 변수 치환 보존
        assert "테스트 질문입니다" in prompt
        assert "테스트 답변입니다" in prompt
        assert "첫 번째 컨텍스트" in prompt
        assert "두 번째 컨텍스트" in prompt


class TestInternalEvaluatorPromptOverride:
    """(b)(c) 오버라이드 시 코드 변경 없이 프롬프트 교체 + 변수 보존"""

    def test_override_changes_prompt(self) -> None:
        custom = (
            "Evaluate the answer. Q: {query}. Context: {context_text}. A: {answer}."
        )
        evaluator = InternalEvaluator(
            llm_client=MagicMock(),
            prompt_template=custom,
        )
        prompt = evaluator._build_prompt(
            query="What is RAG?",
            answer="RAG combines retrieval and generation.",
            context=["RAG is a technique."],
        )
        # 한국어 내장 프롬프트가 사라지고 영어 커스텀이 전달됨
        assert "답변의 품질을 객관적으로 평가하는 전문가" not in prompt
        assert prompt.startswith("Evaluate the answer. Q: What is RAG?.")
        assert "A: RAG combines retrieval and generation." in prompt
        # 컨텍스트 포맷팅(문서 N:) 보존
        assert "문서 1:" in prompt
        assert "RAG is a technique." in prompt

    def test_blank_override_falls_back_to_default(self) -> None:
        """빈 문자열/None이면 코드 기본 프롬프트로 폴백(회귀 0)"""
        evaluator = InternalEvaluator(
            llm_client=MagicMock(),
            prompt_template="",
        )
        assert evaluator._prompt_template == DEFAULT_EVALUATION_PROMPT_TEMPLATE
