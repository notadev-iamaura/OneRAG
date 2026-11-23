"""Regression checks for panel leakage and one-shot, two-arm scoring."""

import json
from pathlib import Path

import pytest

from scripts import rag_evidence_holdouts as preparation
from scripts import rag_evidence_holdouts_gate as gate
from scripts.rag_growth_tydi_ko import digest
from scripts.rag_research_inputs import previous_input


def test_relocated_history_uses_same_contents_and_leaves_other_paths_untouched(tmp_path, monkeypatch):
    original = Path("/private/tmp/study/panel.json")
    monkeypatch.delenv("ONERAG_EVAL_CACHE_DIR", raising=False)
    assert previous_input(original) == original
    monkeypatch.setenv("ONERAG_EVAL_CACHE_DIR", str(tmp_path))
    relocated = tmp_path / "study/panel.json"
    assert previous_input(original) == previous_input(Path("/tmp/study/panel.json")) == relocated
    outside = Path("/public/klue/train.json")
    assert previous_input(outside) == outside
    relocated.parent.mkdir()
    relocated.write_text("registered")
    pinned = digest(relocated)
    preparation.verified(previous_input(original), pinned)
    relocated.write_text("substituted")
    with pytest.raises(ValueError, match="checksum"):
        preparation.verified(previous_input(original), pinned)


def store(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False))
    return path


def test_near_duplicate_cutoff_matches_brute_force():
    index = preparation.NearArticles()
    texts = [" ".join(f"term{i}" for i in range(offset, offset + 30)) for offset in range(16)]
    for original in texts[::6]:
        index.add(original)
    for query in texts:
        actual = index.grams(query)
        expected = any(5 * len(index.grams(doc) & actual) >= 4 * len(index.grams(doc) | actual)
                       for doc in texts[::6])
        assert index.contains(query) == expected


def test_once_only_two_arm_score_retains_errors(tmp_path: Path, monkeypatch):
    panels = tmp_path / "panels"
    section = panels / "tydi"
    section.mkdir(parents=True)
    inputs = {
        "questions": [{"id": "yes", "question": "when?"}, {"id": "no", "question": "where?"}],
        "corpus": [{"id": "d", "title": "public", "content": "July"}],
        "labels": [{"id": "yes", "answerable": True, "source_id": "d", "answers": ["July"],
                    "spans": [{"text": "July", "start": 0, "end": 4}]},
                   {"id": "no", "answerable": False, "source_id": None, "answers": [], "spans": []}],
    }
    files = {f"final.{k}.json": digest(store(section / f"final.{k}.json", v)) for k, v in inputs.items()}
    registration = store(section / "reservation.json", {"files": files})
    manifest = store(panels / "manifest.json", {"panels": {"tydi": {"files": files, "reservation_sha256": digest(registration)}}})
    with pytest.raises(ValueError, match="prospectively registered"):
        gate.panel_identity(panels, "tydi")
    monkeypatch.setattr(gate, "REGISTERED_SHA", digest(manifest))
    old_proof, new_proof = (store(tmp_path / f"policy-{n}.json", n) for n in (1, 2))
    gate.start(panels, "tydi", [old_proof], [new_proof], [])
    with pytest.raises(FileExistsError):
        gate.start(panels, "tydi", [old_proof], [new_proof], [])
    ans = {"id": "yes", "retrieved": ["d"], "status": "answered", "answer": "July", "quote": "July",
           "source_id": "d", "start": 0, "end": 4, "quote_start": 0, "quote_end": 4}
    abstention = {"id": "no", "retrieved": ["d"], "status": "abstained"}
    previous = store(tmp_path / "before.json", [ans, abstention])
    proposed = store(tmp_path / "after.json", [ans, {"id": "no", "retrieved": ["d"], "status": "error"}])
    gate.score(panels, "tydi", previous, proposed)
    result = gate.load(gate.paths(panels, "tydi")[1])
    assert result["n"] == 2 and result["pairs"]["unanswerable"]["lost_ids"] == ["no"]
    assert result["summaries"]["candidate"]["unanswerable_reference_retrieved"]["percent"] is None
    assert not result["absolute_both_at_least_80"] and not result["candidate_has_no_more_errors"]
    with pytest.raises(FileExistsError):
        gate.score(panels, "tydi", previous, proposed)
    with pytest.raises(ValueError, match="refusal"):
        gate.compare([ans, abstention], [ans, {**abstention, "citations": ["d"]}], inputs["labels"], inputs["corpus"])
