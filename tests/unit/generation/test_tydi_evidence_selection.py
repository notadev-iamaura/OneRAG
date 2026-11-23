from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.modules.core.generation import tydi_evidence_selection as p
from app.modules.core.generation.korean_span_reader import SpanAnswer
from app.modules.core.generation.tydi_evidence_spans import KoreanEvidenceProposer


def material():
    docs = [{"id": "a", "title": "항만", "content": "규모는 18만 명이다."},
            {"id": "b", "title": "인구", "content": "인구는 11만 명으로 집계됐다."}]
    groups = []
    for i, (doc, answer, score) in enumerate(zip(docs, ("18만 명", "11만 명"), (7.0, 6.0), strict=True)):
        left = doc["content"].index(answer)
        groups.append([SpanAnswer(i, doc["id"], answer, left, left+len(answer),
                                 doc["content"], 0, len(doc["content"]), score)])
    return docs, groups, [3.0, 2.5], {"a": {}, "b": {}}


def model(**weights):
    return {"features": list(p.NAMES), "weights": [weights.get(k, 0) for k in p.NAMES],
            "mean": [0] * len(p.NAMES), "scale": [1] * len(p.NAMES)}


def test_learned_evidence_can_choose_a_competing_document_and_a_verbatim_shorter_span():
    docs, groups, full, support = material()
    learned = model(query_title_overlap=10, measure_or_name_trim=5)
    span = p.decide("인구는 얼마인가?", docs, groups, full, support, "learned_global", learned)
    assert span.source_id == "b" and span.answer == "11만"
    assert docs[1]["content"][span.start:span.end] == span.answer
    assert docs[1]["content"][span.quote_start:span.quote_end] == span.quote
    within = p.decide("인구는 얼마인가?", docs, groups, full, support, "learned_within", learned)
    assert within.source_id == "a"


def test_existing_null_and_span_thresholds_apply_to_all_modes():
    docs, groups, _, support = material()
    for mode in p.MODES:
        assert p.decide("인구는?", docs, groups, [-1, -2], support, mode, model()) is None
        below = [[replace(s, score=p.THRESHOLD) for s in spans] for spans in groups]
        assert p.decide("인구는?", docs, below, [2, 2], support, mode, model()) is None


def test_damaged_citation_cannot_be_selected_and_no_generated_text_is_inserted():
    docs, groups, full, support = material()
    groups[1][0] = replace(groups[1][0], quote="무관한 인용")
    with pytest.raises(ValueError, match="offsets|substring"):
        p.decide("인구는?", docs, groups, full, support, "learned_global", model())


def test_incompatible_ranker_rejected_before_any_model_load():
    with pytest.raises(ValueError, match="compatible"):
        p.TyDiEvidenceReader.from_local("unavailable", "unavailable", "learned_global")


@pytest.mark.parametrize("vocab, expected", [(1, ["input_ids", "attention_mask"]),
                                              (2, ["input_ids", "token_type_ids", "attention_mask"])])
def test_single_segment_embedding_does_not_index_nonexistent_question_pair_row(monkeypatch, vocab, expected):
    from app.modules.core.generation.korean_span_reader import KoreanSpanReader

    def stub(self, model_path, *, device):
        self.model = SimpleNamespace(config=SimpleNamespace(type_vocab_size=vocab))
        self.tokenizer = SimpleNamespace(model_input_names=["input_ids", "token_type_ids", "attention_mask"])
    monkeypatch.setattr(KoreanSpanReader, "__init__", stub)
    assert KoreanEvidenceProposer("dummy").tokenizer.model_input_names == expected


def test_failing_experimental_sentence_does_not_invalidate_real_baseline():
    from scripts.rag_evidence_tydi import Query, predictions

    docs, groups, full, support = material()
    q = Query({"id": "one", "question": "인구는?"}, docs, groups,
              [g[0] for g in groups], full, support, "new model error")
    assert predictions([q], "sentence", None)[0]["status"] == "error"
    assert predictions([q], "baseline", None)[0]["status"] == "answered"
