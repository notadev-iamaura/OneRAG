import json
from pathlib import Path

import pytest

from scripts import rag_evidence_replication_gate as gate


def panel(tmp_path, monkeypatch):
    domain = "tydi-replication"
    folder = tmp_path / "panels"
    src = folder / domain
    src.mkdir(parents=True)
    records = {
        "final.questions.json": [{"id": "p", "question": "누구?"}, {"id": "n", "question": "언제?"}],
        "final.labels.json": [{"id": "p", "source_id": "a", "answers": ["민아"], "answerable": True,
                               "spans": [{"start": 0, "end": 2}]},
                              {"id": "n", "source_id": None, "answers": [], "answerable": False, "spans": []}],
        "final.corpus.json": [{"id": "a", "content": "민아다."}, {"id": "b", "content": "다른 문서"}],
    }
    for name, body in records.items():
        (src / name).write_text(json.dumps(body))
    (src / "reservation.json").write_text('{"test":true}')
    reserved = gate.primary.digest(src / "reservation.json")
    manifest = {"panels": {domain: {"reserve_only": True, "reservation_sha256": reserved,
                                     "files": {f: gate.primary.digest(src / f) for f in records}}}}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(gate.primary, "REGISTERED_SHA", gate.primary.digest(folder / "manifest.json"))
    monkeypatch.setitem(gate.PANELS, domain, (1, reserved))
    ctrl, cand, driver = [tmp_path / name for name in ("policy-a", "policy-b", "driver")]
    for p in (ctrl, cand, driver):
        p.write_text(p.name)
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    def start():
        gate.start(folder, domain, [ctrl], [cand], [driver], a, b)
    rows = [{"id": "p", "status": "answered", "answer": "민아", "source_id": "a", "start": 0, "end": 2,
             "quote": "민아다.", "quote_start": 0, "quote_end": 4, "retrieved": ["b", "a"]},
            {"id": "n", "status": "error", "retrieved": ["a", "b"]}]
    return start, folder, domain, a, b, rows, cand


def test_one_shot_identical_retrieval_counts_native_refusal_and_execution_error(tmp_path, monkeypatch):
    start, folder, domain, a, b, rows, _ = panel(tmp_path, monkeypatch)
    start()
    with pytest.raises(FileExistsError):
        start()
    a.write_text(json.dumps(rows))
    b.write_text(json.dumps([rows[0], dict(rows[1], status="abstained")]))
    gate.score(folder, domain)
    _, result = gate.primary.paths(folder, domain)
    score = json.loads(result.read_text())
    assert score["identical_retrieval_order"] == 2 and score["absolute_both_at_least_80"]
    assert score["summaries"]["control"]["statuses"]["error"] == 1
    assert score["pairs"]["unanswerable"]["gained_ids"] == ["n"]
    with pytest.raises(FileExistsError):
        gate.score(folder, domain)


def test_reject_preexisting_files_changed_sources_and_different_rank_order(tmp_path, monkeypatch):
    start, folder, domain, a, b, rows, policy = panel(tmp_path, monkeypatch)
    a.write_text("[]")
    with pytest.raises(ValueError, match="unoccupied"):
        start()
    a.unlink()
    start()
    a.write_text(json.dumps(rows))
    b.write_text(json.dumps([dict(rows[0], retrieved=["a", "b"]), rows[1]]))
    with pytest.raises(ValueError, match="identical"):
        gate.score(folder, domain)
    policy.write_text("changed code")
    with pytest.raises(ValueError, match="policy or driver changed"):
        gate.score(folder, domain)
    with pytest.raises(ValueError, match="Only the two"):
        gate.identity(Path("."), "tydi")
