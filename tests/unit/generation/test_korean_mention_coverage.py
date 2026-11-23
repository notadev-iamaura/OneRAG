import re

from app.modules.core.generation.korean_mention_coverage import select


def test_only_a_strictly_more_complete_mention_changes_the_source_location():
    body = "도시 누리 개장. 동부 도시 누리 개장."
    source = {"id": "s", "content": body}
    start = body.index("누리")
    old = {"source_id": "s", "quote": body, "quote_start": 0, "quote_end": len(body),
           "answer": "누리", "start": start, "end": start + 2}
    def words(text):
        return re.findall(r"[가-힣]+", text)
    selected = select("동부 도시 개장", source, old, words)
    assert selected["start"] == body.rindex("누리")
    assert selected["quote"] == body[selected["quote_start"]:selected["quote_end"]] == "동부 도시 누리 개장."
    assert selected["answer"] == old["answer"]
    assert select("도시 개장", source, old, words) is old


def test_conflicting_clauses_do_not_move_even_with_more_total_matching_words():
    body = "동부 누리 교통. 북부 누리 행사 개장."
    a = body.index("누리")
    doc = {"id": "s", "content": body}
    span = {"source_id": "s", "answer": "누리", "start": a, "end": a+2, "quote": body,
            "quote_start": 0, "quote_end": len(body)}
    assert select("동부 북부 행사 개장", doc, span, lambda s: re.findall(r"[가-힣]+", s)) is span
