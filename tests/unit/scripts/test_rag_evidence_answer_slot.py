from dataclasses import replace

import pytest

from app.modules.core.generation import korean_answer_slot as slot
from app.modules.core.generation.korean_span_reader import SpanAnswer
from scripts import rag_evidence_answer_slot as runner
from scripts.rag_evidence_tydi import Query


def fixture():
    body = "하라는 모아를 반겼다."
    doc = {"id": "one", "content": body, "title": "예시"}
    def make(a, b):
        return SpanAnswer(0, "one", body[a:b], a, b, body, 0, len(body), 4.)
    return doc, make(0, 2), make(4, 6)


def test_object_question_distinguishes_differently_inflected_names():
    doc, subject, obj = fixture()
    question = "누구를 반겼나?"
    weights = {"case_agreement": 3., "expected=object/right=object": 1.}
    opts = [[subject, obj]]
    model = {"blend": [1., 1.], "grammar": weights}
    selected = slot.select(question, [doc], [subject], opts, [4.], model)
    assert selected == obj
    assert slot.select(question, [doc], [subject], opts, [4.], model, grammar=False) == subject
    assert slot.select(question, [doc], [subject], opts, [-1.], model) is None
    with pytest.raises(ValueError, match="Missing measured"):
        slot.select(question, [doc], [subject], [[]], [-1.], model)


def test_nearby_foils_exclude_gold_and_bad_source_is_an_error():
    doc, subject, obj = fixture()
    foils = runner.contrast(doc["content"], 4, 6, {"모아"})
    assert foils
    assert all(doc["content"][a:b].strip() != "모아" for a, b in foils)
    with pytest.raises(ValueError, match="exact substring"):
        slot.choices("누구를", doc, subject, [replace(obj, answer="새 답")])


def test_error_is_retained_and_pair_counts_preserve_groups():
    case = Query({"id": "a", "question": "누구?"}, [], [], [], [], {}, "missing")
    assert runner.predict([case], {}, True)[0]["status"] == "error"
    a = {"outcomes": [{"id": "a", "answerable": True, "correct": True},
                      {"id": "b", "answerable": False, "correct": False}]}
    b = {"outcomes": [dict(x, correct=not x["correct"]) for x in a["outcomes"]]}
    assert runner.paired(a,b) == {"positive": {"gain": 0, "loss": 1, "same": 0},
                                  "negative": {"gain": 1, "loss": 0, "same": 0}}


def test_learned_blend_never_switches_an_accepted_source():
    doc, subject, obj = fixture()
    q = {"id": "case", "question": "누구를 반겼나?"}
    other = {**doc, "id": "elsewhere"}
    other_answer = replace(obj, source_id="elsewhere", document_index=1, score=8.)
    case = Query(q, [doc, other], [[subject, obj], [other_answer]], [subject, other_answer], [7., 0.], {}, None)
    labels = {"case": {"answerable": True, "source_id": "one", "spans": [{"start": 4, "end": 6}], "answers": ["모아"]}}
    weights = {"case_agreement": 1.}
    blend = runner.fit_blend([case], labels, weights)
    assert blend["contrast_queries"] == 1
    answer = runner.predict([case], {**blend, "grammar": weights}, True)[0]
    assert (answer["source_id"],answer["start"],answer["end"]) == ("one",4,6)
