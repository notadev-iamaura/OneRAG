"""
Ragas 기반 배치 평가기
Ragas 라이브러리를 사용한 RAG 답변 품질 평가

주요 기능:
- 배치 평가 지원 (여러 샘플 동시 평가)
- 다양한 메트릭 지원 (faithfulness, answer_relevancy 등)
- Graceful Degradation (Ragas 없어도 기본값 반환)

의존성: ragas (선택적, pip install rag-chatbot[ragas])
"""

import math
from dataclasses import dataclass
from typing import Any

from app.lib.logger import get_logger

from .models import EvaluationResult

logger = get_logger(__name__)

# Ragas 기본 메트릭
DEFAULT_RAGAS_METRICS = [
    "faithfulness",
    "answer_relevancy",
    "context_precision",
]

# Ragas 라이브러리 사용 가능 여부 확인
_RAGAS_AVAILABLE = False
try:
    from ragas import evaluate as ragas_evaluate
    from ragas.metrics import (
        answer_relevancy,
        context_precision,
        faithfulness,
    )

    _RAGAS_AVAILABLE = True
    logger.info("Ragas 라이브러리 로드 성공")
except ImportError:
    logger.warning("Ragas 라이브러리가 설치되지 않았습니다. pip install rag-chatbot[ragas]")
    ragas_evaluate = None
    faithfulness = None
    answer_relevancy = None
    context_precision = None


@dataclass
class RagasSample:
    """Ragas 평가용 샘플 데이터"""

    question: str
    answer: str
    contexts: list[str]
    ground_truth: str | None = None


class RagasEvaluator:
    """
    Ragas 기반 배치 평가기

    Ragas 라이브러리를 사용하여 RAG 답변 품질을 평가합니다.
    배치 처리에 최적화되어 있으며, 다양한 메트릭을 지원합니다.

    Args:
        metrics: 사용할 메트릭 목록 (기본값: faithfulness, answer_relevancy)
        batch_size: 배치 크기 (기본값: 10)
        llm_model: 평가용 LLM 모델
        embedding_model: 임베딩 모델

    Attributes:
        name: 평가기 이름 ("ragas")

    Example:
        >>> evaluator = RagasEvaluator()
        >>> result = await evaluator.evaluate(
        ...     query="질문",
        ...     answer="답변",
        ...     context="컨텍스트"
        ... )
        >>> print(f"충실도: {result.faithfulness}")
    """

    def __init__(
        self,
        metrics: list[str] | None = None,
        batch_size: int = 10,
        llm_model: str = "gpt-4o",
        embedding_model: str = "text-embedding-3-large",
    ):
        """
        RagasEvaluator 초기화

        Args:
            metrics: 사용할 메트릭 목록
            batch_size: 배치 크기
            llm_model: 평가용 LLM 모델
            embedding_model: 임베딩 모델
        """
        self._metrics = metrics or DEFAULT_RAGAS_METRICS.copy()
        self._batch_size = batch_size
        self._llm_model = llm_model
        self._embedding_model = embedding_model
        self._ragas_metrics = self._load_metrics()

        logger.info(
            f"RagasEvaluator 초기화: metrics={self._metrics}, "
            f"batch_size={batch_size}, available={self.is_available()}"
        )

    @property
    def name(self) -> str:
        """평가기 이름 반환"""
        return "ragas"

    def is_available(self) -> bool:
        """
        Ragas 사용 가능 여부 확인

        Returns:
            Ragas 라이브러리가 설치되어 있고 메트릭이 로드되었으면 True
        """
        return _RAGAS_AVAILABLE and len(self._ragas_metrics) > 0

    def _load_metrics(self) -> list[Any]:
        """
        Ragas 메트릭 객체 로드

        Returns:
            사용 가능한 Ragas 메트릭 객체 리스트
        """
        if not _RAGAS_AVAILABLE:
            return []

        metric_map = {
            "faithfulness": faithfulness,
            "answer_relevancy": answer_relevancy,
            "context_precision": context_precision,
        }

        loaded = []
        for metric_name in self._metrics:
            if metric_name in metric_map and metric_map[metric_name] is not None:
                loaded.append(metric_map[metric_name])
            else:
                logger.warning(f"Ragas 메트릭 '{metric_name}'을 찾을 수 없습니다")

        return loaded

    def get_available_metrics(self) -> list[str]:
        """
        사용 가능한 메트릭 목록 반환

        Returns:
            메트릭 이름 리스트
        """
        if not _RAGAS_AVAILABLE:
            return []

        return ["faithfulness", "answer_relevancy", "context_precision"]

    async def evaluate(
        self,
        query: str,
        answer: str,
        context: list[str],
        reference: str | None = None,
    ) -> EvaluationResult:
        """
        단일 샘플 평가

        Args:
            query: 사용자 질문
            answer: 생성된 답변
            context: 검색된 컨텍스트
            reference: 참조 답변 (선택)

        Returns:
            EvaluationResult: 평가 결과
        """
        samples = [
            {
                "query": query,
                "answer": answer,
                "context": context,
                "reference": reference,
            }
        ]

        results = await self.batch_evaluate(samples)
        return results[0] if results else self._create_default_result(
            "단일 평가 실패"
        )

    async def batch_evaluate(
        self,
        samples: list[dict[str, Any]],
    ) -> list[EvaluationResult]:
        """
        배치 평가 실행

        Args:
            samples: 평가할 샘플 리스트
                각 샘플은 {"query", "answer", "context", "reference"} 형태

        Returns:
            EvaluationResult 리스트
        """
        if not samples:
            return []

        if not self.is_available():
            logger.warning("Ragas를 사용할 수 없습니다. 기본값을 반환합니다.")
            return [
                self._create_default_result("Ragas 라이브러리 없음")
                for _ in samples
            ]

        try:
            return await self._run_ragas_evaluation(samples)
        except Exception as e:
            logger.error(f"Ragas 배치 평가 실패: {e}")
            return [
                self._create_default_result(f"평가 실패: {str(e)}")
                for _ in samples
            ]

    async def _run_ragas_evaluation(
        self,
        samples: list[dict[str, Any]],
    ) -> list[EvaluationResult]:
        """
        실제 Ragas 평가 실행

        Args:
            samples: 평가할 샘플 리스트

        Returns:
            EvaluationResult 리스트
        """
        try:
            # Ragas Dataset 형식으로 변환
            from datasets import Dataset

            contexts: list[list[str]] = []
            for sample in samples:
                ctx = sample.get("context", [])
                if isinstance(ctx, list):
                    contexts.append([str(c) for c in ctx])
                else:
                    contexts.append([str(ctx)])

            data = {
                "question": [s.get("query", "") for s in samples],
                "answer": [s.get("answer", "") for s in samples],
                "contexts": contexts,
                "ground_truth": [s.get("reference", "") or "" for s in samples],
            }

            dataset = Dataset.from_dict(data)

            # Ragas 평가 실행
            result = ragas_evaluate(
                dataset=dataset,
                metrics=self._ragas_metrics,
            )

            # 결과 변환
            return self._convert_ragas_results(result, len(samples))

        except Exception as e:
            logger.error(f"Ragas 평가 실행 오류: {e}")
            raise

    def _convert_ragas_results(
        self,
        ragas_result: Any,
        sample_count: int,
    ) -> list[EvaluationResult]:
        """
        Ragas 결과를 EvaluationResult로 변환

        Args:
            ragas_result: Ragas 평가 결과
            sample_count: 샘플 개수

        Returns:
            EvaluationResult 리스트
        """
        results = []

        try:
            # Ragas 결과에서 DataFrame 추출
            df = ragas_result.to_pandas()

            for i in range(min(len(df), sample_count)):
                row = df.iloc[i]

                # 메트릭 값 추출 (없으면 기본값)
                faith = float(row["faithfulness"])
                relevance = float(row["answer_relevancy"])
                if not math.isfinite(faith) or not math.isfinite(relevance):
                    results.append(self._create_default_result("유한한 평가 점수가 필요합니다"))
                    continue
                precision = row.get("context_precision", None)

                # 범위 보정 (0.0-1.0)
                faith = max(0.0, min(1.0, faith))
                relevance = max(0.0, min(1.0, relevance))

                # 종합 점수 계산
                overall = (faith + relevance) / 2

                result = EvaluationResult(
                    faithfulness=faith,
                    relevance=relevance,
                    overall=overall,
                    reasoning="Ragas 평가 완료",
                    context_precision=float(precision) if precision is not None else None,
                    raw_scores={
                        "faithfulness": faith,
                        "answer_relevancy": relevance,
                        "context_precision": precision,
                    },
                )
                results.append(result)

        except Exception as e:
            logger.error(f"Ragas 결과 변환 오류: {e}")
            # 변환 실패 시 기본값 반환
            for _ in range(len(results), sample_count):
                results.append(self._create_default_result(f"결과 변환 실패: {e}"))

        return results

    def _create_default_result(self, reason: str) -> EvaluationResult:
        """
        기본 평가 결과 생성 (Graceful Degradation)

        Args:
            reason: 기본값 반환 사유

        Returns:
            기본값으로 채워진 EvaluationResult
        """
        return EvaluationResult(
            faithfulness=0.5,
            relevance=0.5,
            overall=0.5,
            reasoning=reason,
            raw_scores={},
        )
