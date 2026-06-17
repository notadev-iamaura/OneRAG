"""
LLMQualityEvaluator 평가 프롬프트 외부화 회귀/오버라이드 테스트

코드에 f-string으로 하드코딩됐던 Self-RAG 품질 평가 프롬프트를
config(evaluation_prompt_template)로 외부화한 것이 다음을 만족하는지 검증:

(a) config 미설정 시 코드 내장 한국어 기본 평가 프롬프트와 동일 (회귀 0)
(b) config 오버라이드 시 코드 변경 없이 프롬프트가 바뀜
(c) 변수 치환({query}/{context_text}/{answer}) 보존
"""

from app.modules.core.self_rag.evaluator import (
    DEFAULT_EVALUATION_PROMPT_TEMPLATE,
    LLMQualityEvaluator,
)


def _make_evaluator(template: str | None = None) -> LLMQualityEvaluator:
    """API 키 없이(LLM=None) 생성 — _build_evaluation_prompt만 단위 검증한다."""
    return LLMQualityEvaluator(
        api_key=None,  # LLM 초기화 생략 (graceful degradation), 프롬프트 빌드만 검증
        evaluation_prompt_template=template,
    )


class TestEvaluatorPromptDefault:
    """(a) 미설정 시 코드 내장 한국어 기본 평가 프롬프트 동치 (회귀 0)"""

    def test_default_template_is_builtin(self) -> None:
        ev = _make_evaluator()
        assert ev.evaluation_prompt_template == DEFAULT_EVALUATION_PROMPT_TEMPLATE

    def test_default_prompt_content_and_substitution(self) -> None:
        ev = _make_evaluator()
        prompt = ev._build_evaluation_prompt(
            query="질문입니다",
            answer="답변입니다",
            context=["문서A 내용", "문서B 내용"],
        )
        # 한국어 평가 기준이 그대로 유지됨
        assert "품질을 객관적으로 평가하는 전문가" in prompt
        assert "relevance (관련성)" in prompt
        # (c) 변수 치환 보존
        assert "질문입니다" in prompt
        assert "답변입니다" in prompt
        assert "문서 1:\n문서A 내용" in prompt
        assert "문서 2:\n문서B 내용" in prompt
        # JSON 응답 형식 중괄호가 정상 출력됨 (이스케이프 검증)
        assert '"relevance": 0.0-1.0' in prompt


class TestEvaluatorPromptOverride:
    """(b)(c) 오버라이드 시 코드 변경 없이 프롬프트 교체 + 변수 보존"""

    def test_override_changes_prompt(self) -> None:
        custom = (
            "Evaluate the answer quality.\n"
            "Question: {query}\nContext: {context_text}\nAnswer: {answer}\n"
            'Respond JSON: {{"relevance": 0.0-1.0}}'
        )
        ev = _make_evaluator(template=custom)
        prompt = ev._build_evaluation_prompt(
            query="q", answer="a", context=["ctx"]
        )
        # 한국어 내장 프롬프트가 사라지고 영어 커스텀이 사용됨
        assert "품질을 객관적으로 평가하는 전문가" not in prompt
        assert "Evaluate the answer quality." in prompt
        # (c) 변수 치환 보존
        assert "Question: q" in prompt
        assert "Answer: a" in prompt
        assert "문서 1:\nctx" in prompt
        assert '"relevance": 0.0-1.0' in prompt
