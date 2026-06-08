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
        "",
        "bm25",
        "법령 검색",
        "show documents",
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
    assert engine._is_simple_query("show sessions") is True
