"""
GPT5QueryExpansionEngine 영어 의문사 마커 config 외부화 테스트

영어 의문사 정규식(_ENGLISH_QUESTION_RE)이 모듈 상수로 하드코딩되어
question_markers 메커니즘과 비대칭이던 문제를 해소한다. 영어 마커도
english_question_markers 생성자 파라미터 + config 키로 외부화해, 운영자가
마커 전체를 자국어로 교체/비활성화할 수 있게 한다.

핵심 단언:
- (a) config 미설정 시 기존 영어 의문사 판정과 동치(회귀 0, 단어 경계 보존)
- (b) english_question_markers 주입 시 새 마커로 교체 가능(빈 목록=비활성화)
"""

from unittest.mock import MagicMock

import pytest

from app.modules.core.retrieval.query_expansion.gpt5_engine import (
    GPT5QueryExpansionEngine,
)


@pytest.fixture
def default_engine() -> GPT5QueryExpansionEngine:
    return GPT5QueryExpansionEngine(llm_factory=MagicMock())


class TestEnglishMarkersDefaultRegression:
    """영어 의문사 기본 판정 회귀 0 검증"""

    @pytest.mark.parametrize(
        "query",
        [
            "How do I reset a session?",
            "why is retrieval slow today",
            "what is the backport plan here",
        ],
    )
    def test_english_question_words_rejected(
        self, default_engine: GPT5QueryExpansionEngine, query: str
    ) -> None:
        assert default_engine._is_simple_query(query) is False

    def test_word_boundary_preserved(
        self, default_engine: GPT5QueryExpansionEngine
    ) -> None:
        """단어 경계 매칭 보존: 'showdocs'의 'how'를 의문사로 오판하지 않는다."""
        # 8자 1토큰, 의문 신호 없음 → 단순 쿼리
        assert default_engine._is_simple_query("showdocs") is True


class TestEnglishMarkersConfigInjection:
    """영어 마커 config 주입 검증"""

    def test_disable_english_markers(self) -> None:
        """빈 목록 주입 시 영어 의문사 판정이 비활성화된다."""
        engine = GPT5QueryExpansionEngine(
            llm_factory=MagicMock(),
            english_question_markers=[],
        )
        # 의문사가 있어도 짧은 키워드면 단순으로 분류(영어 분기 비활성).
        # "how" 3자 1토큰 → 길이 임계(10자) 내 단순 쿼리.
        assert engine._is_simple_query("how") is True

    def test_replace_english_markers(self) -> None:
        """마커를 교체하면 새 단어만 의문사로 판정된다."""
        engine = GPT5QueryExpansionEngine(
            llm_factory=MagicMock(),
            english_question_markers=["explain"],
        )
        # 새 마커 'explain'은 의문 신호로 판정(복합 쿼리)
        assert engine._is_simple_query("explain") is False
        # 기존 'how'는 더 이상 의문 신호 아님 → 짧으면 단순
        assert engine._is_simple_query("how") is True

    def test_from_config_reads_english_markers(self) -> None:
        """from_config가 query_expansion.english_question_markers를 읽는다."""
        config = {
            "query_expansion": {
                "english_question_markers": ["explain", "describe"],
            }
        }
        engine = GPT5QueryExpansionEngine.from_config(config, llm_factory=MagicMock())
        assert engine._is_simple_query("describe the flow here please now") is False
