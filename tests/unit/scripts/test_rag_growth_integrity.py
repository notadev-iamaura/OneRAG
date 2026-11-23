from copy import deepcopy

import pytest

from scripts import rag_growth_integrity as integrity
from scripts import rag_growth_local as local


def measured():
    documents = [{"id": "d", "title": "기록", "content": "서울에서 행사가 열렸다. 참가자는 8명이었다."}]
    case = {"id": "q", "answerable": True, "question": "참가자는 몇 명인가?", "answers": ["8"], "source_ids": ["d"]}
    manifest = {"schema_version": 1, "trials": 3, "model": "local", "index": local.INDEX_ID, "dataset": "public",
                "split": "development", "model_sha256": "b" * 64, "corpus_sha256": local.corpus_sha256(documents),
                "documents": documents, "cases": [case]}
    provenance = {"index_sha256": "a" * 64, "agent_sha256": "c" * 64, "runner_sha256": "e" * 64, "api_model": "alias"}
    row = {**{k: manifest[k] for k in ("model", "index", "corpus_sha256", "model_sha256", "split", "dataset")},
           **provenance, "manifest_sha256": "f" * 64, "status": "answered", "answer": "8", "citations": ["d"],
           "candidates": ["d"], "candidate_batches": [["d"]], "cited_evidence": [{"document_id": "d", "quote": "참가자는 8명이었다."}],
           "id": "q", "grounding_status": "verified_quotes", "stop_reason": "completed", "tokens": 20, "model_calls": 1,
           "temperature": 0, "max_tokens": 640, "fresh_agent_each_trial": True, "model_cache": "shared prefix"}
    before, after = [{("q", t): dict(deepcopy(row), trial=t, policy=arm, policy_mode=arm) for t in (1, 2, 3)}
                     for arm in ("baseline", "candidate")]
    return manifest, before, after, {"expected_provenance": provenance, "manifest_sha256": "f" * 64}


@pytest.mark.parametrize(("term", "quote", "supported"), [
    ("8", "참가자는 18명이다.", False), ("8", "이는 -8명이었다.", False),
    ("8", "이는 1.8 또는 8.5로 기록되었다.", False), ("8", "이는 1,008원이다.", False),
    ("8", "참가자는 ８명이었다.", True), ("18", "총합은 18명.", True),
    ("서울", "연구는 서울에서 이루어졌다.", True), ("서울", "연구는 서울시에서 이루어졌다.", False),
    ("CAT", "A category was selected.", False), ("Cat", "A cat.", True),
    ("가수", "성악가수가 노래한다.", False), ("프란치스코", "프란치스코는 교황이다.", True),
])
def test_gold_span_boundaries(term, quote, supported):
    assert integrity._term_in_quote(term, quote) == supported


def test_official_offsets_require_enclosing_quote_at_annotated_location():
    body = "A는 8명이다. B는 8명이다."
    case = {"id": "q", "answerable": True, "source_ids": ["d"], "answers": ["8"],
            "answer_spans": [{"document_id": "d", "start": body.rindex("8"), "text": "8"}]}
    row = {"status": "answered", "answer": "8", "citations": ["d"], "cited_evidence": [{"document_id": "d", "quote": "A는 8명이다."}]}
    assert integrity.answer_evidence_failure(case, row, {"d": body}) == integrity.SPAN_FAILURE
    row["cited_evidence"][0]["quote"] = "B는 8명이다."
    assert integrity.answer_evidence_failure(case, row, {"d": body}) is None
    case["answer_spans"][0]["start"] += 1
    with pytest.raises(ValueError, match="offset"):
        integrity.answer_evidence_failure(case, row, {"d": body})


def test_matching_document_id_alone_does_not_substantiate_answer():
    manifest, before, after, kwargs = measured()
    integrity.validate_paired(manifest, before, after, **kwargs)
    case, row = manifest["cases"][0], after["q", 1]
    assert integrity.answer_evidence_failure(case, row, manifest["documents"]) is None
    row["cited_evidence"][0]["quote"] = "서울에서 행사가 열렸다."
    assert integrity.answer_evidence_failure(case, row, manifest["documents"]) == integrity.SPAN_FAILURE
    row["answer"] = "다른 답"
    assert integrity.answer_evidence_failure(case, row, manifest["documents"]) is None


@pytest.mark.parametrize(("key", "bad"), [
    ("model_sha256", "9" * 64), ("runner_sha256", "9" * 64), ("corpus_sha256", "9" * 64),
    ("index_sha256", "9" * 64), ("agent_sha256", "9" * 64), ("api_model", "other"),
    ("temperature", .2), ("seed", 7), ("fresh_agent_each_trial", False), ("model_calls", 0),
    ("candidate_batches", [["d", "d"]]), ("candidates", []), ("cited_evidence", []),
    ("cited_evidence", [{"document_id": "d", "quote": "원문에 없는 문장"}]),
    ("status", "abstained"), ("policy_mode", "baseline"), ("verify_premise_mismatch", False),
])
def test_rejects_inconsistent_measurements(key, bad):
    manifest, before, after, kwargs = measured()
    after["q", 1][key] = bad
    with pytest.raises(ValueError):
        integrity.validate_paired(manifest, before, after, **kwargs)


def test_error_rows_remain_in_denominator_without_fabricating_model_usage():
    manifest, before, after, kwargs = measured()
    after["q", 1].update(status="error", tokens=0, model_calls=0, stop_reason="error",
                         grounding_status="invalid_citation", citations=[], cited_evidence=[])
    integrity.validate_paired(manifest, before, after, **kwargs)
    del after["q", 1]
    with pytest.raises(ValueError, match="question/trial"):
        integrity.validate_paired(manifest, before, after, **kwargs)
