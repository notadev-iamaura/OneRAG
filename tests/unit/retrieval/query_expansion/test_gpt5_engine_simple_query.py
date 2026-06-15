from unittest.mock import MagicMock

import pytest

from app.modules.core.retrieval.query_expansion.gpt5_engine import (
    GPT5QueryExpansionEngine,
)


@pytest.fixture
def engine() -> GPT5QueryExpansionEngine:
    return GPT5QueryExpansionEngine(llm_factory=MagicMock())


@pytest.mark.parametrize(
    "query",
    [
        "",  # 빈 쿼리
        "bm25",  # 4자 1토큰
        "법령 검색",  # 6자 2토큰 (의문 신호 없음)
        "show docs",  # 9자 2토큰 (영어 짧은 키워드)
    ],
)
def test_is_simple_query_allows_short_keyword_phrases(
    engine: GPT5QueryExpansionEngine,
    query: str,
) -> None:
    assert engine._is_simple_query(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "어떻게 세션을 복구하나요?",
        "RAG는 왜 느린가요",
        "How do I reset a session?",
        "検索はどう動く？",
        "retrieval quality ranking session timeout backport",
    ],
)
def test_is_simple_query_rejects_question_signals_and_long_queries(
    engine: GPT5QueryExpansionEngine,
    query: str,
) -> None:
    assert engine._is_simple_query(query) is False


def test_is_simple_query_does_not_match_english_question_words_inside_words(
    engine: GPT5QueryExpansionEngine,
) -> None:
    # "show"는 의문사 "how"를 포함하지만 단어 경계 매칭으로 오판하지 않아야 한다.
    # 8자 1토큰이므로 길이 임계(10자 미만) 내에서 단순 쿼리로 판정된다.
    assert engine._is_simple_query("showdocs") is True


@pytest.mark.parametrize(
    "query",
    [
        # 공백 없는 CJK 다중 키워드 질의(1토큰이지만 10자 이상) — 더 이상
        # 단순으로 누락되지 않고 LLM 쿼리 확장 대상이 되어야 한다.
        "삼성전자 2024년 매출 실적 비교",
        "매출비교실적분석현황요약정리",
    ],
)
def test_is_simple_query_rejects_long_cjk_keyword_queries(
    engine: GPT5QueryExpansionEngine,
    query: str,
) -> None:
    assert engine._is_simple_query(query) is False
