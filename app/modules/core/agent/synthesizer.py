"""
AgentSynthesizer - 결과 합성

ReAct 패턴에서 "Synthesize" 담당 컴포넌트.
도구 실행 결과들을 분석하여 최종 답변을 생성하거나
추가 도구 호출이 필요한지 판단합니다.

주요 기능:
- 모든 스텝의 도구 결과를 종합하여 LLM으로 최종 답변 생성
- 도구 결과에서 소스 정보(메타데이터) 추출
- 중복 소스 제거 및 상위 N개 제한
- 결과 내용 길이 제한으로 토큰 사용량 최적화

사용 예시:
    synthesizer = AgentSynthesizer(llm_client, config)
    answer, sources = await synthesizer.synthesize(state)
"""

from typing import Any

from ....lib.logger import get_logger
from .interfaces import AgentConfig, AgentState, ToolResult

logger = get_logger(__name__)


# 결과 합성 프롬프트 템플릿
# {output_language} 플레이스홀더는 build_synthesizer_system_prompt에서 치환된다.
SYNTHESIZER_SYSTEM_PROMPT_TEMPLATE = """당신은 RAG 시스템의 답변 생성 에이전트입니다.
도구 실행 결과를 바탕으로 사용자 질문에 정확하고 도움이 되는 답변을 제공하세요.

## 답변 규칙:
1. 검색 결과를 바탕으로 정확하게 답변하세요
2. 정보가 없으면 솔직하게 "관련 정보를 찾지 못했습니다"라고 말하세요
3. {output_language}로 자연스럽고 친절하게 답변하세요
4. 불확실한 정보는 추측하지 말고 확실한 내용만 포함하세요
5. 검색 결과가 여러 개인 경우 핵심 내용을 요약하세요
6. 도구 실행이 실패한 경우에도 가능한 정보를 바탕으로 답변하세요

## 형식:
- 간결하고 명확하게 답변하세요
- 필요한 경우 목록이나 단계를 사용하세요
- 출처 정보는 답변에 포함하지 마세요 (별도로 제공됩니다)
"""


def build_synthesizer_system_prompt(
    output_language: str = "한국어",
    template: str | None = None,
) -> str:
    """결과 합성 시스템 프롬프트를 출력 언어로 조립한다.

    Args:
        output_language: 답변 출력 언어 이름 (기본값: "한국어")
        template: config로 외부화된 시스템 프롬프트 템플릿. None이면 코드 내장
            기본값(SYNTHESIZER_SYSTEM_PROMPT_TEMPLATE)을 사용한다 → 회귀 0.

    Returns:
        출력 언어가 반영된 시스템 프롬프트 문자열
    """
    base_template = (
        template if template is not None else SYNTHESIZER_SYSTEM_PROMPT_TEMPLATE
    )
    return base_template.replace("{output_language}", output_language)


SYNTHESIZER_USER_PROMPT = """## 사용자 질문:
{query}

## 도구 실행 결과:
{tool_results}

위 결과를 바탕으로 사용자 질문에 답변하세요.
결과가 없거나 실패한 경우에도 최선의 답변을 제공하세요."""


# 답변 생성 실패 시 사용자에게 노출되는 폴백 메시지 (코드 내장 기본값=한국어)
# 운영자는 config.synthesizer_error_message로 코드 포크 없이 오버라이드한다.
SYNTHESIZER_ERROR_MESSAGE = (
    "죄송합니다. 답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
)


# 결과 포맷팅 상수
MAX_CONTENT_LENGTH = 500  # 개별 문서 내용 최대 길이
MAX_DOCUMENTS_PER_RESULT = 5  # 결과당 최대 문서 수
MAX_SOURCES = 10  # 최대 소스 수


class AgentSynthesizer:
    """
    결과 합성기

    ReAct 패턴에서 "Synthesize" 담당.
    도구 실행 결과들을 종합하여 LLM으로 최종 답변을 생성합니다.

    Attributes:
        _llm_client: LLM 클라이언트 (generate_text 메서드 필요)
        _config: 에이전트 설정
    """

    def __init__(
        self,
        llm_client: Any,
        config: AgentConfig,
    ):
        """
        AgentSynthesizer 초기화

        Args:
            llm_client: LLM 클라이언트 (generate_text 메서드 필요)
            config: 에이전트 설정

        Raises:
            ValueError: llm_client가 None인 경우
        """
        if llm_client is None:
            raise ValueError("llm_client는 필수입니다")

        self._llm_client = llm_client
        self._config = config
        # 출력 언어를 반영한 시스템 프롬프트를 미리 빌드 (기본값=한국어).
        # config.synthesizer_system_prompt가 있으면 외부 템플릿을, 없으면 코드 내장
        # 기본값을 사용한다 → 미설정 시 회귀 0.
        self._system_prompt = build_synthesizer_system_prompt(
            getattr(config, "output_language", "한국어"),
            getattr(config, "synthesizer_system_prompt", None),
        )
        # 사용자 프롬프트와 에러 폴백 메시지도 동일하게 오버라이드 가능.
        self._user_prompt_template = (
            getattr(config, "synthesizer_user_prompt", None) or SYNTHESIZER_USER_PROMPT
        )
        self._error_message = (
            getattr(config, "synthesizer_error_message", None)
            or SYNTHESIZER_ERROR_MESSAGE
        )

        logger.info("AgentSynthesizer 초기화 완료")

    async def synthesize(
        self,
        state: AgentState,
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        결과 합성 → 최종 답변 생성

        모든 스텝의 도구 결과를 종합하여 LLM으로 최종 답변을 생성합니다.
        또한 검색 결과에서 소스 정보를 추출하여 반환합니다.

        Args:
            state: 에이전트 상태 (원본 쿼리 + 모든 스텝 히스토리)

        Returns:
            tuple[str, list[dict[str, Any]]]:
                - answer: 최종 답변 문자열
                - sources: 참조 소스 리스트 (source, title, score 포함)

        Note:
            LLM 호출 실패 시 기본 에러 메시지를 반환합니다.
        """
        try:
            # 1. 모든 스텝의 도구 결과 수집
            all_results = state.all_tool_results

            # 2. 결과 포맷팅 (LLM 프롬프트용)
            results_text = self._format_results(all_results)

            # 3. 소스 정보 추출
            sources = self._extract_sources(all_results)

            # 4. LLM으로 답변 생성
            user_prompt = self._user_prompt_template.format(
                query=state.original_query,
                tool_results=results_text,
            )

            answer = await self._llm_client.generate_text(
                prompt=user_prompt,
                system_prompt=self._system_prompt,
            )

            # 5. 응답 정리
            answer = answer.strip() if answer else ""

            logger.info(
                f"AgentSynthesizer: 답변 생성 완료 "
                f"(길이={len(answer)}, 소스={len(sources)}개)"
            )

            return answer, sources

        except Exception as e:
            logger.error(f"AgentSynthesizer 에러: {e}")
            return (
                self._error_message,
                [],
            )

    def _format_results(self, results: list[ToolResult]) -> str:
        """
        도구 결과를 LLM 프롬프트용 텍스트로 포맷팅

        결과가 너무 길면 적절히 잘라서 토큰 사용량을 최적화합니다.

        Args:
            results: 도구 실행 결과 리스트

        Returns:
            포맷팅된 결과 텍스트
        """
        if not results:
            return "도구 실행 결과 없음"

        parts = []
        for i, result in enumerate(results, 1):
            if result.success and result.data:
                # 문서 검색 결과 처리 (documents 키가 있는 경우)
                if "documents" in result.data:
                    docs = result.data["documents"]
                    for j, doc in enumerate(docs[:MAX_DOCUMENTS_PER_RESULT], 1):
                        content = doc.get("content", "")
                        # 내용 길이 제한
                        if len(content) > MAX_CONTENT_LENGTH:
                            content = content[:MAX_CONTENT_LENGTH] + "..."
                        parts.append(f"[결과 {i}-{j}] {content}")
                else:
                    # 일반 결과 (예: SQL 쿼리 결과)
                    data_str = str(result.data)
                    if len(data_str) > MAX_CONTENT_LENGTH:
                        data_str = data_str[:MAX_CONTENT_LENGTH] + "..."
                    parts.append(f"[결과 {i}] {data_str}")
            else:
                # 실패한 결과
                parts.append(
                    f"[실패 {i}] {result.tool_name}: {result.error or '알 수 없는 에러'}"
                )

        return "\n\n".join(parts) if parts else "도구 실행 결과 없음"

    def _extract_sources(
        self, results: list[ToolResult]
    ) -> list[dict[str, Any]]:
        """
        도구 결과에서 소스 정보 추출

        중복 소스는 제거하고 상위 N개만 반환합니다.

        Args:
            results: 도구 실행 결과 리스트

        Returns:
            소스 정보 리스트 (source, title, score 포함)
        """
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()

        for result in results:
            # 실패한 결과나 데이터 없는 경우 건너뜀
            if not result.success or not result.data:
                continue

            # 문서 검색 결과에서 소스 추출
            if "documents" in result.data:
                for doc in result.data["documents"]:
                    metadata = doc.get("metadata", {})
                    source = metadata.get("source", "")

                    # 빈 소스나 이미 추가된 소스는 건너뜀
                    if not source or source in seen:
                        continue

                    seen.add(source)
                    sources.append(
                        {
                            "source": source,
                            "title": metadata.get("title", source),
                            "score": doc.get("score", 0.0),
                        }
                    )

        # 상위 N개만 반환
        return sources[:MAX_SOURCES]
