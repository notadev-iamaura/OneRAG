"""
InternalEvaluator - LLM 기반 실시간 내부 평가기

빠르고 저렴한 실시간 답변 품질 평가.
Self-RAG 시스템에서 환각 검출 및 품질 게이트로 사용.

주요 기능:
- faithfulness (충실도): 답변이 컨텍스트에 근거하는지 평가
- relevance (관련성): 답변이 질문 의도에 부합하는지 평가

의존성:
- app.lib.logger (로깅)
- app.modules.core.evaluation.models (EvaluationResult)
"""
import json
from typing import Any

from app.lib.logger import get_logger

from .models import EvaluationResult

logger = get_logger(__name__)


# Self-RAG 실시간 평가 프롬프트 템플릿 (코드 내장 기본값=한국어)
# 운영자는 evaluation.yaml의 evaluation.internal.prompt_template로 코드 포크 없이
# 언어/도메인별 루브릭을 오버라이드한다. {query}/{context_text}/{answer}
# 플레이스홀더 보존 필수. JSON 응답 형식의 중괄호는 {{ }}로 이스케이프되어 있다
# (str.format() 호환). 미설정 시 이 기본값을 사용하므로 평가 동작 변화 없음(회귀 0).
DEFAULT_EVALUATION_PROMPT_TEMPLATE = """당신은 AI 답변의 품질을 객관적으로 평가하는 전문가입니다.

다음 기준으로 답변을 JSON 형식으로 평가하세요:

평가 기준:
1. faithfulness (충실도): 답변이 제공된 컨텍스트에 근거하는가? (0.0-1.0)
   - 1.0: 모든 내용이 컨텍스트에서 직접 확인됨
   - 0.5: 일부 내용만 컨텍스트에서 확인됨
   - 0.0: 컨텍스트와 무관한 내용 (환각)

2. relevance (관련성): 답변이 질문 의도에 부합하는가? (0.0-1.0)
   - 1.0: 질문에 완벽히 답변함
   - 0.5: 부분적으로 답변함
   - 0.0: 질문과 무관한 답변

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
    "faithfulness": 0.0-1.0,
    "relevance": 0.0-1.0,
    "reasoning": "각 점수에 대한 간단한 근거"
}}"""

# 평가 컨텍스트의 문서 구분 라벨(LLM 입력). prompt_template을 다른 언어로 교체해도
# 이 라벨이 한국어로 남던 비대칭을 해소한다. {index} 플레이스홀더 필수. 미설정 시
# 한국어 기본값 유지(회귀 0). self_rag evaluator와 동일 기본값.
DEFAULT_DOCUMENT_LABEL_TEMPLATE = "문서 {index}:"


class InternalEvaluator:
    """
    LLM 기반 실시간 내부 평가기

    빠른 LLM 모델을 사용하여 답변 품질을 실시간으로 평가합니다.
    Self-RAG 시스템에서 품질 게이트로 사용됩니다.

    Args:
        llm_client: LLM 클라이언트 (generate 메서드 필요)
        model: 사용할 LLM 모델명 (기본: google/gemini-2.5-flash-lite)
        timeout: 평가 타임아웃 (초) (기본: 10.0)

    사용 예시:
        ```python
        from app.modules.core.evaluation import InternalEvaluator

        evaluator = InternalEvaluator(llm_client=my_llm_client)

        result = await evaluator.evaluate(
            query="서울 맛집 추천해줘",
            answer="서울에는 A식당이 유명합니다.",
            context=["A식당은 강남역 근처에 위치..."],
        )

        if result.is_acceptable():
            print("품질 합격")
        ```
    """

    def __init__(
        self,
        llm_client: Any | None = None,
        model: str = "google/gemini-2.5-flash-lite",
        timeout: float = 10.0,
        prompt_template: str | None = None,
        document_label_template: str | None = None,
    ):
        """
        InternalEvaluator 초기화

        Args:
            llm_client: LLM 클라이언트 (generate 메서드 필요, None이면 평가 불가)
            model: 사용할 LLM 모델명
            timeout: 평가 타임아웃 (초)
            prompt_template: config 외부화된 평가 프롬프트 템플릿.
                None 또는 빈 문자열이면 코드 내장 한국어 기본값
                (DEFAULT_EVALUATION_PROMPT_TEMPLATE)을 사용한다 → 회귀 0.
                오버라이드 시 {query}/{context_text}/{answer} 플레이스홀더 보존 필수.
            document_label_template: 컨텍스트 문서 구분 라벨({index} 플레이스홀더).
                None이면 한국어 기본("문서 {index}:") 사용(회귀 0).
        """
        self._llm_client = llm_client
        self._model = model
        self._timeout = timeout
        # 평가 프롬프트 템플릿: config 오버라이드 없으면 코드 내장 한국어 기본값.
        self._prompt_template: str = (
            prompt_template or DEFAULT_EVALUATION_PROMPT_TEMPLATE
        )
        self._document_label_template: str = (
            document_label_template or DEFAULT_DOCUMENT_LABEL_TEMPLATE
        )

    @property
    def name(self) -> str:
        """
        평가기 이름 반환

        Returns:
            평가기 식별 문자열 ("internal")
        """
        return "internal"

    def is_available(self) -> bool:
        """
        평가기 사용 가능 여부 확인

        LLM 클라이언트가 설정되어 있으면 사용 가능.

        Returns:
            True: LLM 클라이언트가 설정됨
            False: LLM 클라이언트가 없음
        """
        return self._llm_client is not None

    async def evaluate(
        self,
        query: str,
        answer: str,
        context: list[str],
        reference: str | None = None,
    ) -> EvaluationResult:
        """
        단일 답변 품질 평가

        LLM을 사용하여 답변의 충실도(faithfulness)와 관련성(relevance)을 평가합니다.

        Args:
            query: 사용자 질문
            answer: LLM이 생성한 답변
            context: 검색된 컨텍스트 문서 리스트
            reference: 참조 답변 (선택, 현재 미사용)

        Returns:
            EvaluationResult: 평가 결과 (faithfulness, relevance, overall 점수 포함)

        Note:
            - LLM 클라이언트가 없으면 기본값(0.5) 반환
            - LLM 호출 실패 시 기본값(0.5) 반환
        """
        # LLM 클라이언트가 없으면 기본값 반환
        if not self.is_available():
            logger.warning("InternalEvaluator 사용 불가: LLM 클라이언트 없음")
            return self._default_result("평가 불가: LLM 클라이언트가 설정되지 않았습니다")

        # 프롬프트 생성
        prompt = self._build_prompt(query, answer, context)

        llm_client = self._llm_client
        if llm_client is None:
            return self._default_result("평가 불가: LLM 클라이언트가 설정되지 않았습니다")

        try:
            # LLM 호출
            response = await llm_client.generate(prompt)
            return self._parse_response(response)
        except Exception as e:
            logger.error(f"InternalEvaluator 평가 실패: {e}")
            return self._default_result(f"평가 실패: {str(e)}")

    async def batch_evaluate(
        self,
        samples: list[dict[str, Any]],
    ) -> list[EvaluationResult]:
        """
        배치 평가

        여러 샘플을 순차적으로 평가합니다.

        Args:
            samples: 평가 샘플 리스트
                각 샘플은 {"query": str, "answer": str, "context": list[str]} 형식

        Returns:
            list[EvaluationResult]: 각 샘플에 대한 평가 결과 리스트

        Note:
            개별 평가 실패 시에도 전체 결과를 반환합니다 (실패한 항목은 기본값).
        """
        results = []
        for sample in samples:
            result = await self.evaluate(
                query=sample.get("query", ""),
                answer=sample.get("answer", ""),
                context=sample.get("context", []),
                reference=sample.get("reference"),
            )
            results.append(result)
        return results

    def _build_prompt(self, query: str, answer: str, context: list[str]) -> str:
        """
        평가용 프롬프트 생성 (config 외부화 템플릿 또는 코드 내장 기본값 사용)

        Args:
            query: 사용자 질문
            answer: LLM이 생성한 답변
            context: 검색된 컨텍스트 문서 리스트

        Returns:
            LLM에게 전달할 평가 프롬프트
        """
        # 컨텍스트 포맷팅 (문서 라벨은 config 외부화 — 평가 프롬프트와 언어 일관성)
        context_text = "\n\n".join(
            [
                f"{self._document_label_template.format(index=i + 1)}\n{doc}"
                for i, doc in enumerate(context)
            ]
        )

        return self._prompt_template.format(
            query=query,
            context_text=context_text,
            answer=answer,
        )

    def _parse_response(self, response: str) -> EvaluationResult:
        """
        LLM 응답 파싱

        Args:
            response: LLM의 JSON 형식 응답

        Returns:
            EvaluationResult: 파싱된 평가 결과

        Note:
            - ```json``` 또는 ``` ``` 코드 블록 내 JSON 추출
            - 파싱 실패 시 기본값 반환
        """
        try:
            content = response

            # ```json 코드 블록 추출
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()
            # ``` 코드 블록 추출
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                content = content[start:end].strip()

            # JSON 파싱
            data = json.loads(content)

            # 점수 추출 (기본값 0.5)
            faithfulness = float(data.get("faithfulness", 0.5))
            relevance = float(data.get("relevance", 0.5))
            reasoning = data.get("reasoning", "")

            # overall 계산: faithfulness 50% + relevance 50%
            overall = faithfulness * 0.5 + relevance * 0.5

            return EvaluationResult(
                faithfulness=faithfulness,
                relevance=relevance,
                overall=overall,
                reasoning=reasoning,
                raw_scores=data,
            )
        except Exception as e:
            logger.warning(f"LLM 응답 파싱 실패: {e}")
            return self._default_result(f"파싱 실패: {str(e)}")

    def _default_result(self, reasoning: str) -> EvaluationResult:
        """
        기본 평가 결과 생성

        평가 불가 또는 실패 시 반환할 기본값을 생성합니다.

        Args:
            reasoning: 기본값 반환 사유

        Returns:
            EvaluationResult: 모든 점수가 0.5인 기본 결과
        """
        return EvaluationResult(
            faithfulness=0.5,
            relevance=0.5,
            overall=0.5,
            reasoning=reasoning,
        )
