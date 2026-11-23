import pytest

from app.modules.core.generation.korean_corroborated_evidence import (
    corroborate_misplaced_citation,
    select_supported_extent,
)


def span(doc, value):
    body = doc["content"]
    a = body.index(value)
    return {"answer": value, "start": a, "end": a + len(value), "quote": body, "quote_start": 0,
            "quote_end": len(body), "source_id": doc["id"]}


def test_misplaced_label_requires_an_independently_confirmed_literal():
    doc = {"id": "s1", "content": "비가 내렸다. 현지 관측소는 해오름이다."}
    exact = span(doc, "해오름")
    assert corroborate_misplaced_citation(doc, "[1.1] 해오름", exact, 1.) == exact
    for raw in ("NONE", "[1.3] 해오름", "[1.1] 바람", "[1.2] 해오름", "해오름"):
        assert corroborate_misplaced_citation(doc, raw, exact, 1.) is None
    assert corroborate_misplaced_citation(doc, "[1.1] 해오름", exact, 0.) is None
    assert corroborate_misplaced_citation(doc, "[1.1] 해오름", {**exact, "start": 0}, 1.) is None


@pytest.mark.parametrize(("phrase","question","expected"), [
    ("연간 4.5%", "증가율은 얼마인가?", "4.5%"),
    ("연간 4.5%", "측정 기간과 증가율을 모두 적으라.", "연간 4.5%"),
    ("2~4%", "비율은 얼마인가?", "2~4%"),
    ("최소 8명", "인원 제한은?", "최소 8명"),
])
def test_contiguous_quantity_extent(phrase, question, expected):
    doc = {"id": "s", "content": "보고된 수치는 " + phrase + "였다."}
    s = span(doc, phrase)
    assert select_supported_extent(question, doc, s, s, s)["answer"] == expected


def test_title_prefix_requires_both_readers_and_preserves_all_original_offsets():
    doc = {"id": "s", "content": "시가 개최한 행사는 2019년 서울 국제 미술 전시회였다."}
    full, short = span(doc, "2019년 서울 국제 미술 전시회"), span(doc, "미술 전시회")
    result = select_supported_extent("시가 개최한 행사의 이름은?", doc, short, full, short)
    assert doc["content"][result["start"]:result["end"]] == result["answer"] == "서울 국제 미술 전시회"
    assert select_supported_extent("언제 개최한 행사인가?", doc, short, full, short) == short
