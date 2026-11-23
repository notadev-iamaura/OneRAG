import json

import pytest

from scripts import rag_evidence_third_klue_gate as gate


def test_third_panel_requires_same_retrieval_and_all_locked_rows(tmp_path, monkeypatch):
    meta = {"domain": "klue-third", "n": 2, "per_stratum": 1}
    monkeypatch.setattr(gate, "identity", lambda: meta)
    monkeypatch.setattr(gate, "TRIAL", tmp_path / "trial")
    monkeypatch.setattr(gate.third, "OUT", tmp_path)
    p = tmp_path / "panel"
    p.mkdir()
    (p / "final.labels.json").write_text(json.dumps([
        {"id": "p", "answerable": True, "answers": ["가"], "source_id": "doc",
         "spans": [{"start": 0, "end": 1, "text": "가"}]},
        {"id": "n", "answerable": False, "answers": [], "source_id": "doc", "spans": []}]))
    (p / "final.corpus.json").write_text(json.dumps([{"id": "doc", "content": "가."}]))
    policies = [tmp_path / x for x in ("baseline", "proposal", "driver")]
    for f in policies:
        f.write_text(f.name)
    before, after = tmp_path / "control.json", tmp_path / "candidate.json"
    gate.start([policies[0]], [policies[1]], [policies[2]], before, after)
    with pytest.raises(FileExistsError):
        gate.start([policies[0]], [policies[1]], [policies[2]], before, after)
    rows = [{"id": "p", "status": "error", "retrieved": ["doc"]},
            {"id": "n", "status": "abstained", "retrieved": ["doc"]}]
    before.write_text(json.dumps(rows))
    after.write_text(json.dumps([dict(rows[0], retrieved=[]), rows[1]]))
    with pytest.raises(ValueError, match="ordered retrieval"):
        gate.score()
    after.write_text(json.dumps([dict(rows[0], status="answered", answer="가", start=0, end=1,
                                      source_id="doc", quote="가.", quote_start=0, quote_end=2), rows[1]]))
    gate.score()
    result = json.loads((gate.TRIAL / "score.json").read_text())
    assert result["identical_retrieval_order"] == 2
    assert result["pairs"]["answerable"]["gained_ids"] == ["p"]
    assert result["pairs"]["unanswerable"]["same"] == 1
    with pytest.raises(FileExistsError):
        gate.score()
