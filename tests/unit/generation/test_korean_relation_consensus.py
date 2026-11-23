from typing import Any

import pytest

from app.modules.core.generation.korean_relation_consensus import decide

SOURCES = {"first": "가팀과 나팀. 가팀.", "second": "다팀이다."}


def span(doc: str, text: str, start: int = 0) -> dict[str, Any]:
    body = SOURCES[doc]
    return {"status": "answered", "retrieved": [doc], "source_id": doc, "answer": text,
            "start": start, "end": start+len(text), "quote": body, "quote_start": 0, "quote_end": len(body)}


def test_same_literal_in_other_occurrence_cannot_override_explicit_refusal() -> None:
    baseline = span("first", "가팀")
    refused = {"status": "abstained", "retrieved": ["first", "second"]}
    assert decide(baseline, [baseline], refused, SOURCES) == (baseline, "keep_initial_encoder_agreement")
    repeated = span("first", "가팀", SOURCES["first"].rindex("가팀"))
    assert decide(baseline, [repeated], refused, SOURCES) == (refused, "accept_explicit_refusal")


def test_two_readers_may_rescue_second_article_only_on_exact_agreement() -> None:
    refused = {"status": "abstained", "retrieved": ["first"]}
    second = span("second", "다팀")
    assert decide(refused, [second], second, SOURCES) == (second, "accept_review_encoder_agreement")
    assert decide(refused, [span("first", "가팀")], second, SOURCES) == (refused, "keep_initial_no_agreement")


def test_review_failure_preserves_a_verified_answer_or_real_error() -> None:
    positive = span("first", "나팀", SOURCES["first"].index("나팀"))
    error = {"status": "error", "retrieved": ["first", "second"], "error": "invalid citation"}
    refused = {"status": "abstained", "retrieved": ["first"]}
    assert decide(positive, [], error, SOURCES) == (positive, "keep_verified_initial_after_review_error")
    assert decide(refused, [], error, SOURCES) == (error, "keep_review_error")
    assert decide(error, [], positive, SOURCES) == (error, "keep_initial_error")
    with pytest.raises(ValueError, match="anchor"):
        decide({**positive, "quote": "다른 원문"}, [], error, SOURCES)
