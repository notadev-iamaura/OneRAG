"""
AgentReflector - Self-Reflection 담당

ReAct 패턴에서 "Reflect" 담당 컴포넌트.
생성된 답변의 품질을 평가하고, 개선이 필요한 부분을 식별합니다.

주요 기능:
- LLM을 사용하여 답변 품질 평가 (0-10점)
- 답변의 문제점 식별 및 개선 제안
- threshold 기반 개선 필요 여부 판단
- 추가 검색이 필요한 키워드 추출

사용 예시:
    reflector = AgentReflector(llm_client, config)
    result = await reflector.reflect(query, answer, context)
    if result.needs_improvement:
        # 개선 로직 실행
"""

import json
import re
from typing import Any

from ....lib.logger import get_logger
from .interfaces import AgentConfig, ReflectionResult

logger = get_logger(__name__)


# Reflection 프롬프트 템플릿
# {output_language}는 build_reflector_system_prompt에서 치환된다.
REFLECTOR_SYSTEM_PROMPT_TEMPLATE = """당신은 RAG 시스템의 답변 품질 평가 에이전트입니다.
생성된 답변의 품질을 객관적으로 평가하세요.

## 평가 기준 (각 항목 0-2점):
1. 정확성: 질문에 정확히 답변했는가?
2. 완전성: 필요한 정보가 모두 포함되었는가?
3. 충실성: 컨텍스트에 기반한 사실인가?
4. 명확성: 이해하기 쉽게 작성되었는가?
5. 관련성: 질문과 관련 있는 내용인가?

## 응답 형식 (JSON만 출력):
{
    "score": 0-10 (소수점 가능),
    "issues": ["발견된 문제점들"],
    "suggestions": ["개선을 위한 제안들"],
    "reasoning": "평가 근거 (1-2문장)"
}

## 중요:
- 객관적이고 공정하게 평가하세요
- 문제점이 없으면 빈 배열 []을 반환하세요
- issues/suggestions/reasoning은 {output_language}로 작성하세요
- 반드시 JSON 형식으로만 응답하세요
"""


def build_reflector_system_prompt(output_language: str = "한국어") -> str:
    """답변 품질 평가 시스템 프롬프트를 출력 언어로 조립한다.

    Args:
        output_language: issues/suggestions/reasoning 출력 언어 (기본값: "한국어")

    Returns:
        출력 언어가 반영된 시스템 프롬프트 문자열
    """
    return REFLECTOR_SYSTEM_PROMPT_TEMPLATE.replace(
        "{output_language}", output_language
    )


REFLECTOR_USER_PROMPT = """## 원본 질문:
{query}

## 생성된 답변:
{answer}

## 검색 컨텍스트:
{context}

위 답변의 품질을 평가하세요. JSON 형식으로만 응답하세요."""


class AgentReflector:
    """
    Self-Reflection 담당

    생성된 답변의 품질을 LLM으로 평가하고,
    개선이 필요한 경우 문제점과 제안을 반환합니다.

    Attributes:
        _llm_client: LLM 클라이언트 (generate_text 메서드 필요)
        _config: 에이전트 설정 (reflection_threshold 등)
    """

    def __init__(
        self,
        llm_client: Any,
        config: AgentConfig,
    ):
        """
        AgentReflector 초기화

        Args:
            llm_client: LLM 클라이언트 (generate_text 메서드 필요)
            config: 에이전트 설정

        Raises:
            ValueError: 필수 의존성 누락 시
        """
        if llm_client is None:
            raise ValueError("llm_client는 필수입니다")
        if config is None:
            raise ValueError("config는 필수입니다")

        self._llm_client = llm_client
        self._config = config
        # 출력 언어를 반영한 시스템 프롬프트를 미리 빌드 (기본값=한국어)
        self._system_prompt = build_reflector_system_prompt(
            getattr(config, "output_language", "한국어")
        )

        logger.info(
            f"AgentReflector 초기화: "
            f"threshold={config.reflection_threshold}, "
            f"max_iterations={config.max_reflection_iterations}"
        )

    async def reflect(
        self,
        query: str,
        answer: str,
        context: str,
    ) -> ReflectionResult:
        """
        답변 품질 평가 (Self-Reflection)

        LLM을 사용하여 생성된 답변의 품질을 평가하고,
        개선이 필요한지 판단합니다.

        Args:
            query: 원본 사용자 질문
            answer: 생성된 답변
            context: 검색된 컨텍스트 (검색 결과 요약)

        Returns:
            ReflectionResult: 평가 결과 (score, issues, suggestions 등)

        Note:
            LLM 호출 실패 시 보수적으로 needs_improvement=False 반환
        """
        try:
            # 1. 프롬프트 구성
            user_prompt = REFLECTOR_USER_PROMPT.format(
                query=query,
                answer=answer,
                context=context or "컨텍스트 없음",
            )

            # 2. LLM 호출
            response = await self._llm_client.generate_text(
                prompt=user_prompt,
                system_prompt=self._system_prompt,
            )

            # 3. 응답 파싱
            return self._parse_reflection_response(response)

        except Exception as e:
            logger.error(f"AgentReflector 에러: {e}")
            return self._fallback_result()

    def _parse_reflection_response(self, response: str) -> ReflectionResult:
        """
        LLM 응답을 ReflectionResult로 파싱

        Args:
            response: LLM 응답 문자열 (JSON 형식)

        Returns:
            ReflectionResult: 파싱된 결과
        """
        try:
            # JSON 추출 (마크다운 코드 블록 처리)
            json_str = self._extract_json(response)
            data = json.loads(json_str)

            score = float(data.get("score", 7.0))
            issues = data.get("issues", [])
            suggestions = data.get("suggestions", [])
            reasoning = data.get("reasoning", "")

            # threshold 기반 개선 필요 여부 판단
            needs_improvement = score < self._config.reflection_threshold

            logger.info(
                f"AgentReflector: score={score}, "
                f"needs_improvement={needs_improvement}"
            )

            return ReflectionResult(
                score=score,
                issues=issues,
                suggestions=suggestions,
                needs_improvement=needs_improvement,
                reasoning=reasoning,
            )

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.warning(f"Reflection 응답 파싱 실패: {e}")
            return self._fallback_result()

    def _extract_json(self, response: str) -> str:
        """응답에서 JSON 문자열 추출"""
        response = response.strip()

        # 마크다운 코드 블록 처리
        json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            return json_match.group(1).strip()

        return response

    def _fallback_result(self) -> ReflectionResult:
        """폴백 결과 (에러 시 보수적 처리)"""
        return ReflectionResult(
            score=7.0,
            issues=[],
            suggestions=[],
            needs_improvement=False,
            reasoning="평가 실패 - 기본값 사용",
        )
