from dataclasses import replace

import pytest

from app.modules.core.generation.korean_span_reader import _cited_span
from app.modules.core.generation.tydi_evidence_context import ContextWindow, expand, ranges, windows


def test_sentence_windows_respect_original_ranges_and_include_neighbor():
    body = "도시에서 태어났다. 연구소에서 일했다. 2004년에 상을 받았다. 그 후 은퇴했다."
    doc = {"id": "a", "title": "연구자", "content": body}
    span = _cited_span(body, 0, "a", 0, 3, 8)
    selected = windows("상을 받은 시점은?", [doc], [[span]])
    assert 1 <= len(selected) <= 2
    assert any("상을 받았다" in body[w.start:w.end] for w in selected)
    assert all(w.document_index == 0 and body[w.start:w.end] != body for w in selected)
    assert all(body[a:b].strip() == body[a:b] for a, b in ranges(body))


def test_recovered_second_occurrence_is_in_the_original_article_and_keeps_the_original_gate():
    body = "수도는 서울이다. 행사는 부산이다. 본사도 서울이다."
    doc = {"id": "a", "title": "회사", "content": body}
    left = body.index("서울")
    base = _cited_span(body, 0, "a", left, left+2, 5)
    window_start = body.index("본사도")
    window = ContextWindow(0, window_start, len(body))
    text = body[window.start:window.end]
    local_start = text.index("서울")
    proposal = _cited_span(text, 0, "a", local_start, local_start+2, 35)
    [expanded] = expand([doc], [[base]], [window], [[proposal]])
    assert expanded[0] == base and expanded[1].score == base.score
    assert expanded[1].start == body.rindex("서울")
    assert expanded[1].quote == "본사도 서울이다."
    with pytest.raises(ValueError, match="original source"):
        expand([doc], [[base]], [window], [[replace(proposal, answer="런던")]])


def test_single_sentence_never_pays_for_an_identical_model_request():
    body = "서울은 수도다."
    doc = {"id": "a", "title": "서울", "content": body}
    assert windows("수도는?", [doc], [[_cited_span(body, 0, "a", 0, 2, 4)]]) == []
