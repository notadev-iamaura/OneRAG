from unittest.mock import patch

from app.modules.core.generation import korean_span_support as reader
from scripts import rag_evidence_span_support as audit


def test_close_plausible_anchor_recovers_only_the_closest_real_occurrence():
    impossible = {"is_impossible":True,"context":"오늘과 내일. 오늘과 모레.","answers":{"answer_start":[7],"text":["오늘"]}}
    assert audit.anchors(impossible) == ([(8,10)],"nearest_literal")
    positive = {**impossible,"is_impossible":False,"answers":{"answer_start":[0],"text":["오늘"]}}
    assert audit.anchors(positive) == ([(0,2)],"exact")


def test_calibration_keeps_all_96_positives_including_the_boundary():
    rows = [{"is_impossible": i >= 96,"context":"답","title":"문서","question":str(i),
             "answers":{"answer_start":[0],"text":["답"]}} for i in range(192)]
    with patch.object(reader,"score",side_effect=lambda q,*_: .2 if int(q)<96 else .1):
        result = audit.calibrate({},rows)
    assert result["threshold"] == .2
    assert result["positive_supported"] == result["negative_rejected"] == 96


def test_string_agreement_at_another_occurrence_cannot_protect_an_answer():
    span = {"source_id":"doc","answer":"답","start":0,"end":1}
    assert reader.agreement(span,span,span)
    assert not reader.agreement(span,span,dict(span,start=8,end=9))
    assert not reader.agreement(None,span,span)
