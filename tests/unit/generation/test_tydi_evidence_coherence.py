from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from app.modules.core.generation import tydi_evidence_coherence as policy
from app.modules.core.generation.korean_span_reader import _cited_span
from app.modules.core.generation.tydi_evidence_context import ContextWindow


def fixture(monkeypatch, windows, direct=8.0):
    body = "지난 회의는 서울에서 열렸다. 다음 회의는 부산에서 열린다. 서울로 돌아왔다."
    doc = {"id": "paper", "title": "회의", "content": body}
    start, end = body.index("서울"), body.index("부산")
    old = _cited_span(body, 0, "paper", start, start + 2, direct)
    new = _cited_span(body, 0, "paper", end, end + 2, 5)
    case = SimpleNamespace(
        question={"question": "다음 회의 장소는?"}, docs=[doc], candidates=[[old, new]],
        original=[old], full=[1.0], error=None, incumbent_error=None,
    )
    recorded = []
    regions = []
    for a, b, answers in windows:
        text = body[a:b]
        regions.append(ContextWindow(0, a, b))
        values = []
        for rank, t in enumerate(answers):
            idx = text.index(t)
            values.append(asdict(_cited_span(text, 0, "paper", idx, idx + len(t), 20-rank)))
        recorded.append({"document_index": 0, "start": a, "end": b, "readings": values})
    monkeypatch.setattr(policy, "windows", lambda *_: regions)
    return case, recorded, old, new


def test_raw_span_agreement_changes_source_offsets_and_retains_exact_quote(monkeypatch):
    case, local, _, new = fixture(monkeypatch, [(0, 34, ["부산", "회의", "서울"])])
    result = policy.decide(case, local)
    assert result == new
    assert result.quote == "다음 회의는 부산에서 열린다."
    assert case.docs[0]["content"][result.start:result.end] == result.answer


def test_preserve_original_when_it_wins_or_ties_one_real_view(monkeypatch):
    case, local, old, _ = fixture(monkeypatch, [(0, 34, ["부산", "서울"])])
    assert policy.decide(case, local) == old
    case, local, old, _ = fixture(monkeypatch, [(0, 34, ["서울", "부산"])])
    assert policy.decide(case, local) == old


def test_one_window_cannot_replace_an_answer_outside_its_range(monkeypatch):
    case, local, old, _ = fixture(monkeypatch, [(17, 34, ["부산"])])
    assert policy.decide(case, local) == old


def test_distinct_views_can_select_a_shared_location_absent_from_full_nbest(monkeypatch):
    case, local, old, _ = fixture(monkeypatch, [(1, 35, ["부산"]), (17, 40, ["부산"])])
    case.candidates = [[old]]
    assert policy.decide(case, local).answer == "부산"
    with pytest.raises(ValueError, match="intervals differ"):
        policy.decide(case, [local[0], local[0]])


def test_four_ways_to_keep_insufficient_or_invalid_results_distinct(monkeypatch):
    case, local, old, _ = fixture(monkeypatch, [(0, 34, ["부산"])])
    case.full = [0.]
    assert policy.decide(case, local) is None
    case.full = [1.]
    case.original = [replace(old, score=policy.THRESHOLD)]
    assert policy.decide(case, local) is None
    case.original = [old]
    local[0]["readings"][0]["answer"] = "합성"
    with pytest.raises(ValueError, match="exact substring"):
        policy.decide(case, local)
    case.incumbent_error = "QA failed"
    with pytest.raises(ValueError, match="QA failed"):
        policy.decide(case, local)
