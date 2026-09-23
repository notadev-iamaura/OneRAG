"""
LLM 기반 답변 품질 평가 모듈

LLM을 활용하여 생성된 답변의 품질을 4가지 차원에서 객관적으로 평가합니다.
Self-RAG 시스템에서 답변 재생성 여부를 판단하는 데 사용됩니다.

주요 기능:
- Gemini LLM 기반 품질 평가
- 4가지 평가 차원: 관련성, 근거성, 완전성, 확신도
- 품질 임계값 기반 재생성 필요 여부 판단
"""

import asyncio
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

import structlog
from langchain_google_genai import ChatGoogleGenerativeAI

from ....lib.langfuse_client import observe, record_generation

logger = structlog.get_logger(__name__)


# Self-RAG 품질 평가 프롬프트 템플릿 (코드 내장 기본값=한국어)
# 운영자는 self_rag.yaml의 evaluation.prompt_template로 코드 포크 없이 오버라이드한다.
# {query}/{context_text}/{answer} 플레이스홀더 보존 필수.
# JSON 응답 형식의 중괄호는 {{ }}로 이스케이프되어 있다(.format() 호환).
DEFAULT_EVALUATION_PROMPT_TEMPLATE = """당신은 AI 답변의 품질을 객관적으로 평가하는 전문가입니다.

다음 기준으로 답변을 JSON 형식으로 평가하세요:

📋 평가 기준:
1. relevance (관련성): 질문과 답변이 얼마나 관련이 있는가?
   - 1.0: 질문에 직접적으로 답변함
   - 0.5: 부분적으로 관련 있음
   - 0.0: 질문과 무관함

2. grounding (근거성): 답변이 제공된 컨텍스트에 근거하고 있는가?
   - 1.0: 모든 정보가 컨텍스트에서 나옴
   - 0.5: 일부 추측이 포함됨
   - 0.0: 컨텍스트와 무관한 답변

3. completeness (완전성): 질문에 완전히 답변했는가?
   - 1.0: 질문의 모든 부분에 답변함
   - 0.5: 일부만 답변함
   - 0.0: 답변이 불완전함

4. confidence (확신도): 답변의 확실성 수준은?
   - 1.0: 매우 확실한 답변
   - 0.5: 불확실성 포함
   - 0.0: 매우 불확실함

---

질문:
{query}

제공된 컨텍스트:
{context_text}

생성된 답변:
{answer}

---

다음 JSON 형식으로 응답하세요:
{{
    "relevance": 0.0-1.0,
    "grounding": 0.0-1.0,
    "completeness": 0.0-1.0,
    "confidence": 0.0-1.0,
    "reasoning": "각 점수에 대한 간단한 근거"
}}"""

# 평가 컨텍스트의 문서 구분 라벨(LLM 입력). 평가 프롬프트를 다른 언어로 교체해도
# 이 라벨이 한국어로 남던 비대칭을 해소하기 위해 외부화한다. {index} 플레이스홀더
# 필수. 미설정 시 한국어 기본값 유지(회귀 0).
DEFAULT_DOCUMENT_LABEL_TEMPLATE = "문서 {index}:"


@dataclass
class QualityScore:
    """품질 평가 점수"""

    relevance: float  # 관련성 (0.0-1.0)
    grounding: float  # 근거성 (0.0-1.0)
    completeness: float  # 완전성 (0.0-1.0)
    confidence: float  # 확신도 (0.0-1.0)
    overall: float  # 종합 점수 (0.0-1.0)
    reasoning: str  # 평가 근거
    raw_response: dict  # LLM 원본 응답


class EvalStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


@dataclass
class QualityEvaluation:
    status: EvalStatus
    score: QualityScore | None
    error: str | None = None


class LLMQualityEvaluator:
    """
    LLM 기반 답변 품질 평가기

    Gemini LLM을 사용하여 생성된 답변의 품질을 객관적으로 평가합니다.
    Self-RAG 시스템에서 저품질 답변 재생성 여부를 결정하는 핵심 컴포넌트입니다.
    """

    def __init__(
        self,
        llm_provider: str = "google",
        model_name: str = "gemini-2.0-flash-exp",
        api_key: str | None = None,
        quality_threshold: float = 0.75,
        relevance_weight: float = 0.35,
        grounding_weight: float = 0.30,
        completeness_weight: float = 0.25,
        confidence_weight: float = 0.10,
        evaluation_prompt_template: str | None = None,
        document_label_template: str | None = None,
        timeout_seconds: float = 10.0,
    ):
        """
        Args:
            evaluation_prompt_template: config 외부화된 평가 프롬프트 템플릿.
                None이면 코드 내장 DEFAULT_EVALUATION_PROMPT_TEMPLATE(한국어)를
                사용한다 → 미설정 시 평가 동작 변화 없음(회귀 0).
                {query}/{context_text}/{answer} 플레이스홀더 보존 필수.
            document_label_template: 컨텍스트 문서 구분 라벨({index} 플레이스홀더).
                None이면 한국어 기본("문서 {index}:") 사용(회귀 0).
        """
        self.quality_threshold = quality_threshold
        self.relevance_weight = relevance_weight
        self.grounding_weight = grounding_weight
        self.completeness_weight = completeness_weight
        self.confidence_weight = confidence_weight
        self.timeout_seconds = timeout_seconds
        # 평가 프롬프트 템플릿: config 오버라이드 없으면 코드 내장 한국어 기본값.
        self.evaluation_prompt_template: str = (
            evaluation_prompt_template or DEFAULT_EVALUATION_PROMPT_TEMPLATE
        )
        self._document_label_template: str = (
            document_label_template or DEFAULT_DOCUMENT_LABEL_TEMPLATE
        )
        self.llm = None  # Graceful degradation: LLM 초기화 실패 시 None

        # LLM 초기화 (Graceful Degradation - MVP Phase 1)
        if llm_provider == "google":
            # API 키가 없으면 Self-RAG 평가 비활성화
            if not api_key:
                logger.warning(
                    "self_rag_evaluator_no_api_key",
                    provider=llm_provider,
                    reason=(
                        "Self-RAG evaluator에 API 키가 제공되지 않았습니다. "
                        "GOOGLE_API_KEY 환경변수를 설정하면 Self-RAG 품질 평가가 활성화됩니다. "
                        "Self-RAG 평가를 건너뜁니다."
                    ),
                )
                return

            try:
                self.llm = ChatGoogleGenerativeAI(
                    model=model_name,
                    google_api_key=api_key,  # type: ignore[call-arg]
                    temperature=0.0,  # 일관된 평가를 위해 0
                )
                logger.info(
                    "evaluator_initialized",
                    provider=llm_provider,
                    model=model_name,
                    threshold=quality_threshold,
                )
            except Exception as e:
                # Google 자격증명 오류 또는 기타 초기화 실패
                logger.warning(
                    "evaluator_initialization_failed",
                    provider=llm_provider,
                    model=model_name,
                    error=str(e),
                    reason=(
                        "Self-RAG 평가기 초기화 실패. "
                        "API 키 형식, 네트워크, 모델명을 확인하세요. "
                        "Self-RAG 평가를 건너뜁니다."
                    ),
                )
                # self.llm은 None 상태로 유지 (Graceful Degradation)
        else:
            logger.error("unsupported_llm_provider", provider=llm_provider)
            raise ValueError(f"Unsupported LLM provider: {llm_provider}")


    @property
    def is_available(self) -> bool:
        return self.llm is not None

    @observe(
        as_type="generation",
        name="Self-RAG Evaluation",
        capture_input=False,
        capture_output=False,
    )
    async def evaluate(self, query: str, answer: str, context: list[str]) -> QualityEvaluation:
        """
        답변 품질 평가

        Args:
            query: 사용자 질문
            answer: 생성된 답변
            context: 검색된 문서 리스트

        Returns:
            QualityEvaluation: 평가 상태와 검증된 점수
        """
        # Self-RAG 비활성화 상태 확인 (Graceful Degradation)
        if self.llm is None:
            logger.debug("self_rag_disabled_skip_evaluation")
            return QualityEvaluation(EvalStatus.UNAVAILABLE, None)

        # 평가 프롬프트 생성
        prompt = self._build_evaluation_prompt(query, answer, context)

        # LLM 평가 수행
        try:
            response = await asyncio.wait_for(self.llm.ainvoke(prompt), self.timeout_seconds)
            # LLM 호출별 토큰/비용을 Langfuse generation으로 기록한다(LangChain은
            # AIMessage.usage_metadata에 input/output/total 토큰을 제공).
            um = getattr(response, "usage_metadata", None)
            if um:
                record_generation(
                    model=getattr(self.llm, "model", "gemini"),
                    prompt_tokens=um.get("input_tokens", 0) or 0,
                    completion_tokens=um.get("output_tokens", 0) or 0,
                    total_tokens=um.get("total_tokens", 0) or 0,
                )
            # response.content는 str | list 타입이므로 str 변환
            content: str = (
                response.content if isinstance(response.content, str) else str(response.content)
            )
            raw_response = self._parse_llm_response(content)
            if raw_response is None:
                return QualityEvaluation(EvalStatus.FAILED, None, "Invalid JSON response")

            # 점수 추출
            dimensions = ("relevance", "grounding", "completeness", "confidence")
            if any(
                key not in raw_response
                or isinstance(raw_response[key], bool)
                or not isinstance(raw_response[key], (int, float))
                or not 0.0 <= raw_response[key] <= 1.0
                for key in dimensions
            ):
                logger.warning(
                    "evaluation_invalid_dimensions",
                    raw={key: raw_response.get(key) for key in dimensions},
                )
                return QualityEvaluation(EvalStatus.FAILED, None, "Invalid quality dimensions")
            relevance = float(raw_response["relevance"])
            grounding = float(raw_response["grounding"])
            completeness = float(raw_response["completeness"])
            confidence = float(raw_response["confidence"])
            reasoning = raw_response.get("reasoning", "")

            # 종합 점수 계산
            overall = (
                relevance * self.relevance_weight
                + grounding * self.grounding_weight
                + completeness * self.completeness_weight
                + confidence * self.confidence_weight
            )

            quality_score = QualityScore(
                relevance=relevance,
                grounding=grounding,
                completeness=completeness,
                confidence=confidence,
                overall=overall,
                reasoning=reasoning,
                raw_response=raw_response,
            )

            logger.info(
                "answer_evaluated",
                overall_score=overall,
                relevance=relevance,
                grounding=grounding,
                completeness=completeness,
                confidence=confidence,
                requires_regeneration=overall < self.quality_threshold,
            )

            return QualityEvaluation(EvalStatus.OK, quality_score)

        except TimeoutError:
            logger.warning("evaluation_timeout", timeout_seconds=self.timeout_seconds)
            return QualityEvaluation(EvalStatus.TIMEOUT, None, "Evaluation timed out")
        except Exception as e:
            logger.error("evaluation_failed", error=str(e))
            return QualityEvaluation(EvalStatus.FAILED, None, str(e))

    def requires_regeneration(self, quality: QualityScore) -> bool:
        """재생성 필요 여부 판단"""
        return quality.overall < self.quality_threshold

    def _build_evaluation_prompt(self, query: str, answer: str, context: list[str]) -> str:
        """평가 프롬프트 생성 (config 외부화 템플릿 또는 코드 내장 기본값 사용)"""
        context_text = "\n\n".join(
            [
                f"{self._document_label_template.format(index=i + 1)}\n{doc}"
                for i, doc in enumerate(context)
            ]
        )

        return self.evaluation_prompt_template.format(
            query=query,
            context_text=context_text,
            answer=answer,
        )

    def _parse_llm_response(self, content: str) -> dict[str, Any] | None:
        """LLM 응답 파싱"""
        try:
            # JSON 블록 추출 (```json ... ``` 형식 처리)
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                content = content[start:end].strip()

            result = json.loads(content)
            if not isinstance(result, dict):
                return None
            return result
        except Exception as e:
            logger.warning("llm_response_parse_failed", error=str(e), content=content[:200])
            return None
