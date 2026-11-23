import math
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from app.modules.core.generation.korean_span_reader import _cited_span
from app.modules.core.generation.tydi_evidence_context import ContextWindow
from app.modules.core.generation.tydi_evidence_direct import decide, sentence_score
from app.modules.core.generation.tydi_evidence_selection import evidence, variants


def sample():
    body = "지난 회의는 서울이다. 다음 회의는 부산 해운대에서 열린다."
    doc = {"id": "a", "title": "계획", "content": body}
    start = body.index("부산")
    span = _cited_span(body, 0, "a", start, start+len("부산 해운대에서"), 7)
    c = SimpleNamespace(docs=[doc], full=[2.0], original=[span], candidates=[[span]],
                        question={"question": "다음 회의는 어디서 열리나?"}, sentences={},
                        error=None, incumbent_error=None)
    return c, span


def test_no_suffix_trimming_without_raw_hypothesis(monkeypatch):
    c, base = sample()
    assert len(variants(c.question["question"], base)) > 1
    monkeypatch.setattr("app.modules.core.generation.tydi_evidence_direct.windows", lambda *_: [])
    assert decide(c, []) == base


def test_sentence_scoring_matches_existing_feature_values_for_unedited_raw_span():
    c, span = sample()
    query, steady = c.question["question"], 3.7
    _, vectors = evidence(query, c.docs, [[span]], c.full, {"a": {span.quote: steady}})
    v = vectors[0]
    original = 10*v[0] + 1.5*v[4] + 3*v[9] + 1.5*v[12] + .4*v[17] - 1.5*v[19] - .15*v[13]
    assert sentence_score(query, span, steady) == pytest.approx(original, abs=1e-12)
    with pytest.raises(ValueError, match="Nonfinite"):
        sentence_score(query, span, math.nan)


def test_allow_genuine_shorter_window_answer_and_verify_offsets(monkeypatch):
    c, span = sample()
    body = c.docs[0]["content"]
    a = body.index("다음")
    monkeypatch.setattr("app.modules.core.generation.tydi_evidence_direct.windows",
                        lambda *_: [ContextWindow(0, a, len(body))])
    excerpt = body[a:]
    start = excerpt.index("부산")
    local = _cited_span(excerpt, 0, "a", start, start+2, 8)
    raw = [{"document_index": 0, "start": a, "end": len(body), "readings": [asdict(local)]}]
    selected = decide(c, raw)
    assert selected.answer == "부산" and selected.start == span.start and selected.end == span.start+2
    assert body[selected.quote_start:selected.quote_end] == selected.quote
    c.full = [0.]
    assert decide(c, raw) is None
    c.full = [2.]
    raw[0]["readings"][0]["answer"] = "금요일"
    with pytest.raises(ValueError, match="exact substring"):
        decide(c, raw)
