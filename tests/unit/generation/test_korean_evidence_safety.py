import math

import pytest

from app.modules.core.generation.korean_evidence_safety import (
    safe_extent,
    safe_mention,
    safe_recover,
)


def span(body, answer, *, last=False, score=8.0):
    a = body.rindex(answer) if last else body.index(answer)
    return {"source_id": "S1", "answer": answer, "start": a, "end": a+len(answer),
            "quote": body, "quote_start": 0, "quote_end": len(body), "score": score}


def recover(question, body, answer="6개", *, score=8., support=1., raw=None):
    return safe_recover(question, {"id": "S1", "content": body}, raw or f"[1.1] {answer}",
                        span(body, answer, score=score), support)


def test_recovery_requires_question_quantities_in_actual_answer_clause():
    question = "2025년에 점검한 시설은 몇 개인가?"
    assert recover(question, "2025년에는 시설 점검을 보류했다. 2024년에는 6개 시설을 점검했다.") is None
    assert recover(question, "점검 계획을 밝혔다. 2025년에는 쉬었지만 2024년에는 6개 시설을 점검했다.") is None
    assert recover(question, "점검 계획을 밝혔다. 2024년에서 2025년 사이 6개 시설을 점검했다.") is None
    correct = recover(question, "점검 계획을 밝혔다. 2025년도에는 6개 시설을 점검했다.")
    assert correct["answer"] == "6개"
    assert recover("10개월 점검에서 찾은 문제 수는?", "현황을 알렸다. 10명 점검반은 6개 문제를 찾았다.") is None
    assert recover("1,200원 지원 시 추가 품목은?", "현황을 알렸다. 1200원 지원 시 6개 물품을 제공한다.") is not None


@pytest.mark.parametrize(("score", "support"), [(4., 1.), (-10., 1.), (math.nan, 1.), (5., 0.), (5., math.inf)])
def test_recovery_needs_two_strict_finite_scores(score, support):
    assert recover("조사한 시설 수는?", "계획을 밝혔다. 점검한 시설은 6개였다.", score=score, support=support) is None


def test_recovery_rejects_bad_reference_bad_offsets_and_different_literal():
    body = "계획을 밝혔다. 점검한 시설은 6개였다."
    doc = {"id": "S1", "content": body}
    proposed = span(body, "6개")
    for raw in ("[1.1] 9개", "[1.5] 6개", "NONE", "[1.2] 6개"):
        assert safe_recover("시설 수는?", doc, raw, proposed, 5.) is None
    assert safe_recover("시설 수는?", doc, "[1.1] 6개", {**proposed, "source_id": "S2"}, 5.) is None


@pytest.mark.parametrize("question", ["지급 주기와 지원 금액은 얼마인가?", "지급액 및 대상은?", "어느 기간을 기준으로 얼마인가?",
                                      "빈도와 금액을 각각 알려 줘.", "금액과 지급일은?"])
def test_multi_attribute_or_period_question_keeps_original_extent(question):
    body = "지원금은 연간 10만원이다."
    full, short = span(body, "연간 10만원"), span(body, "10만원")
    assert safe_extent(question, full, short) == full
    assert safe_extent("지원 금액은 얼마인가?", full, short) == short


@pytest.mark.parametrize(("answer", "composite"), [("5%", "15%"), ("5%", "1.5%"), ("5%", "-5%"),
                                                  ("A12", "KA12"), ("A12", "A12-7"), ("4", "4,000")])
def test_longer_numeric_or_ascii_identifier_does_not_become_the_citation(answer, composite):
    body = f"원래 값은 {answer}였다. 별칭으로 {composite}를 등록했다."
    first, last = span(body, answer), span(body, answer, last=True)
    assert first["start"] != last["start"]
    assert safe_mention({"id": "S1", "content": body}, first, last) == first


@pytest.mark.parametrize("tail", ["대출 금리가 5%라는 보도를 반박했다.", "대출 금리는 5%가 아닙니다.",
                                   "대출에 5%를 적용하지 않았습니다.", "대출 금리가 5%라는 주장은 사실과 다르다."])
def test_same_literal_in_disputed_statement_keeps_original(tail):
    body = "기본 금리는 5%다. " + tail
    a, b = span(body, "5%"), span(body, "5%", last=True)
    assert safe_mention({"id": "S1", "content": body}, a, b) == a


def test_same_whole_literal_in_affirmative_clause_can_move_but_bad_evidence_fails():
    body = "기본 금리는 5%다. 청년 대출의 기본 금리는 5%다."
    a, b = span(body, "5%"), span(body, "5%", last=True)
    doc = {"id": "S1", "content": body}
    assert safe_mention(doc, a, b) == b
    with pytest.raises(ValueError, match="verified"):
        safe_mention(doc, a, {**b, "start": 0})
