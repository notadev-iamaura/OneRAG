"""
쿼리 복잡도 계산 모듈

사용자 질문의 복잡도를 분석하여 Self-RAG 적용 여부를 결정합니다.
"""

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ComplexityResult:
    """복잡도 계산 결과"""

    score: float  # 0.0-1.0
    length_score: float
    depth_score: float
    multi_intent_score: float
    details: dict


# 코드 내장 한국어 기본 마커 (회귀 안전판).
# config 미설정 시 이 목록을 사용해 기존 동작과 동치를 유지한다.
_DEFAULT_DEPTH_INDICATORS: list[str] = [
    "어떻게",
    "왜",
    "차이",
    "비교",
    "단계",
    "방법",
    "원리",
    "이유",
]
_DEFAULT_MULTI_INTENT_INDICATORS: list[str] = [
    "그리고",
    "또는",
    "그런데",
    "아니면",
    "그다음",
    "추가로",
]
# 언어 중립 다중 의도 신호: 문장 구분/병렬 접속을 나타내는 부호.
# 마커 미설정 언어에서도 다중 의도 점수가 0으로만 떨어지지 않도록 보강한다.
_LANGUAGE_NEUTRAL_MULTI_INTENT_PUNCT: list[str] = [";", " and ", " or ", "?"]


class ComplexityCalculator:
    """쿼리 복잡도 계산기"""

    def __init__(
        self,
        threshold: float = 0.7,
        length_weight: float = 0.3,
        depth_weight: float = 0.4,
        multi_intent_weight: float = 0.3,
        depth_indicators: list[str] | None = None,
        multi_intent_indicators: list[str] | None = None,
        use_language_neutral_signals: bool = False,
    ):
        """ComplexityCalculator 초기화

        Args:
            threshold: Self-RAG 적용 임계값
            length_weight: 길이 점수 가중치
            depth_weight: 깊이 점수 가중치
            multi_intent_weight: 다중 의도 점수 가중치
            depth_indicators: 깊이(분석성) 판단 마커 목록.
                미지정(None) 시 코드 내장 한국어 기본 목록을 사용한다(회귀 0).
                비한국어 운영자는 routing.yaml의 complexity.depth_indicators로
                자국어 마커를 주입할 수 있다.
            multi_intent_indicators: 다중 의도 판단 마커 목록.
                미지정(None) 시 코드 내장 한국어 기본 목록을 사용한다.
                routing.yaml의 complexity.multi_intent_indicators로 주입 가능.
            use_language_neutral_signals: 언어 중립 다중 의도 신호 보강 여부.
                기본 False(회귀 0) — 켜기 전까지는 기존 한국어 마커 점수와
                완전히 동치다. True로 켜면 세미콜론/and·or/물음표 같은
                언어 중립 병렬 신호도 다중 의도 점수에 합산하여, 마커가
                매칭되지 않는 언어에서도 점수가 0으로만 떨어지지 않게 한다.
                routing.yaml의 complexity.use_language_neutral_signals로 제어.
        """
        self.threshold = threshold
        self.length_weight = length_weight
        self.depth_weight = depth_weight
        self.multi_intent_weight = multi_intent_weight
        self.use_language_neutral_signals = use_language_neutral_signals

        # 마커 목록: config 주입 우선, 미설정 시 한국어 기본값(회귀 0)
        self.depth_indicators = (
            depth_indicators
            if depth_indicators is not None
            else list(_DEFAULT_DEPTH_INDICATORS)
        )
        self.multi_intent_indicators = (
            multi_intent_indicators
            if multi_intent_indicators is not None
            else list(_DEFAULT_MULTI_INTENT_INDICATORS)
        )

    async def calculate(self, query: str) -> ComplexityResult:
        """
        쿼리 복잡도 계산

        Args:
            query: 사용자 질문

        Returns:
            ComplexityResult: 복잡도 점수 및 상세 정보
        """
        # 1. 길이 점수 (언어 중립)
        length_score = min(len(query) / 100, 1.0) * self.length_weight

        # 2. 깊이 점수 (언어 의존 마커)
        depth_count = sum(1 for word in self.depth_indicators if word in query)
        depth_score = min(depth_count / 3, 1.0) * self.depth_weight

        # 3. 다중 의도 점수 (언어 의존 마커 + 선택적 언어 중립 신호)
        #    기본은 마커만 사용해 기존 한국어 동작과 동치를 유지한다(회귀 0).
        #    use_language_neutral_signals=True일 때만 세미콜론/and·or/물음표
        #    같은 언어 중립 병렬 신호를 추가 집계하여, 마커가 한 언어에만
        #    매칭돼 0이 되는 문제를 보강한다.
        multi_marker_count = sum(
            1 for word in self.multi_intent_indicators if word in query
        )
        neutral_signal_count = 0
        if self.use_language_neutral_signals:
            lower_query = query.lower()
            neutral_signal_count = sum(
                1
                for token in _LANGUAGE_NEUTRAL_MULTI_INTENT_PUNCT
                if token in lower_query
            )
        multi_count = multi_marker_count + neutral_signal_count
        multi_score = min(multi_count / 2, 1.0) * self.multi_intent_weight

        # 최종 점수
        total_score = length_score + depth_score + multi_score

        result = ComplexityResult(
            score=total_score,
            length_score=length_score,
            depth_score=depth_score,
            multi_intent_score=multi_score,
            details={
                "query_length": len(query),
                "depth_indicators_found": depth_count,
                "multi_intent_indicators_found": multi_count,
            },
        )

        logger.info(
            "complexity_calculated",
            score=result.score,
            threshold=self.threshold,
            self_rag_applicable=result.score >= self.threshold,
        )

        return result

    def requires_self_rag(self, complexity: ComplexityResult) -> bool:
        """Self-RAG 적용 필요 여부 판단"""
        return complexity.score >= self.threshold
