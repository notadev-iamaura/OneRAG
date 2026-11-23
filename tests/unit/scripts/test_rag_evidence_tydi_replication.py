from dataclasses import replace

from app.modules.core.generation.korean_span_reader import _cited_span
from scripts import rag_evidence_tydi_bounds as audit
from scripts import rag_evidence_tydi_replication as runner
from scripts import rag_evidence_tydi_windows as windows
from scripts.rag_evidence_tydi import Query


def example():
    text = "서울은 수도다. 평양에서도 공연했다. 야외에서 관객을 만났다."
    doc = {"id": "d", "content": text, "title": "기록"}
    source = _cited_span(text, 0, "d", 0, 2, 4)
    return Query({"id": "q", "question": "야외에서 누굴 만났나?"}, [doc], [[source]], [source], [3], {}, None), source


def test_capture_preserves_local_coordinates_and_complete_candidate_evidence():
    case, _ = example()

    class Model:
        def propose(self, q, docs, n):
            assert q == case.question["question"] and n == 6
            return [[_cited_span(d["content"], i, d["id"], 0, 2, 5)] for i, d in enumerate(docs)]

    groups, expanded = windows.read_case(Model(), case)
    for w in groups:
        begin = w["start"]
        reading = w["readings"][0]
        assert case.docs[0]["content"][begin:begin + 2] == reading["answer"]
        assert any(s.start == begin and s.answer == reading["answer"] for s in expanded[0])


def test_arm_error_does_not_turn_into_a_correct_refusal_or_change_rank_order():
    case, source = example()
    assert runner.predict(case, {"windows": []}, lambda *_: None) == {
        "id": "q", "retrieved": ["d"], "status": "abstained"}
    assert runner.predict(case, {"error": "unread window"}, lambda *_: None)["status"] == "error"
    answered = runner.predict(case, {"windows": []}, lambda *_: source)
    assert answered["source_id"] == "d" and answered["answer"] == "서울"
    for span in (replace(source, document_index=-1), replace(source, answer="부산")):
        row = runner.predict(case, {"windows": []}, lambda *_, s=span: s)
        assert row["status"] == "error" and row["retrieved"] == ["d"]


def test_direct_document_bound_needs_exact_gold_in_the_actually_selected_source():
    case, _ = example()
    gold = {"q": {"answerable": True, "source_id": "d", "answers": ["서울"], "spans": [{"start": 0, "end": 2}]}}
    opts = {"q": {"id": "q", "windows": []}}
    refused = audit.bounds([case], opts, gold, {"q": {"status": "abstained"}})
    assert refused["raw_correct_on_eligible_gold"] == 1
    assert refused["raw_correct_in_selected_document"] == 0
    answered = audit.bounds([case], opts, gold, {"q": {"status": "answered", "source_id": "d"}})
    assert answered["raw_correct_in_selected_document"] == 1
