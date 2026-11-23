"""Offline public-gate checks with invented documents, answers and model results."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import rag_growth_public_gate as gate

Row = dict[str, Any]


def write(folder: Path, name: str, data: Any) -> str:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = ("\n".join(json.dumps(r) for r in data) if name.endswith(".jsonl") else json.dumps(data)).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def grounded(doc: str, text: str, index: int = 0, score: float = 5.0) -> Row:
    return {"document_index": index, "source_id": doc, "answer": "Blue", "start": 0, "end": 4,
            "quote": text, "quote_start": 0, "quote_end": len(text), "score": score}


def korean_fixture(root: Path, suite: Row, key: str) -> None:
    p = suite["panels"][key]
    n = p["per_stratum"]
    docs = [{"id": "doc", "content": "Blue sky.", "title": "Sky"}]
    questions = [{"id": f"{key}-{i}", "question": f"색상 {i}?"} for i in range(2*n)]
    labels, rows = [], []
    for i, q in enumerate(questions):
        pos = i < n
        labels.append({"id": q["id"], "source_id": "doc" if pos else None, "answerable": pos,
                       "answers": ["Blue"] if pos else [], "spans": [{"start": 0, "end": 4}] if pos else []})
        pred = {"status": "answered", **grounded("doc", "Blue sky.")} if pos else {"status": "abstained"}
        rows.append({"id": q["id"], "retrieved": ["doc"], "tool_retrieved": ["doc"], **pred})
    prefix = Path(p["reservation"]).parent
    parts = {f"final.{k}.json": write(root, str(prefix / f"final.{k}.json"), v)
             for k, v in {"labels": labels, "corpus": docs, "questions": questions}.items()}
    regs = suite["registrations"]
    regs[p["reservation"]] = write(root, p["reservation"], {"files": parts})
    identity = {"adapter": "AgentFactory", "device": "cpu", "top_k": 1, "packages": {},
                "model_files": {"profile": regs["ko/rescue-profile.json"], "gguf": "identical"},
                "policy_files": {"/app/model.py": "same"}, "reservation_sha256": regs[p["reservation"]]}
    regs[p["freeze"]] = write(root, p["freeze"], identity)
    write(root, p["freeze"] + ".started", {"output": "output/rag-growth-03/" + p["result"],
                                           "freeze_sha256": regs[p["freeze"]]})
    write(root, p["result"], {"split": "final", "identity": identity, "rows": rows, **gate.ko.grade(rows, labels, docs)})


def english_fixtures(root: Path, suite: Row) -> None:
    regs, plans = suite["registrations"], suite["panels"]
    articles = []
    for a in range(3):
        paragraphs = []
        for i in range(64):
            qid = f"article{a}-q{i}"
            qa = {"id": qid, "question": f"Which colour {qid}?", "is_impossible": i % 2 == 1,
                  "answers": [] if i % 2 else [{"text": "Blue", "answer_start": 0}]}
            paragraphs.append({"context": f"Blue sky {qid}.", "qas": [qa]})
        articles.append({"title": f"Article {a}", "paragraphs": paragraphs})
    source = write(root, "squad.json", {"data": articles})
    splits = gate.en.panels(articles)
    registration: Row = {"data_sha256": source, "panels": {}}
    for name, (docs, cases) in splits.items():
        registration["panels"][name] = {"case_ids": [c["id"] for c in cases],
                                         "questions_per_stratum": len(cases)//2,
                                         "manifest_sha256": gate.json_sha256([docs, cases])}
    regs["transfer/preregistration.json"] = write(root, "transfer/preregistration.json", registration)
    weights = {"deberta": {"weights": "A"}, "embedding": {"weights": "B"}}
    for file, data in [("two-reader/preregistration.json", {"weights": weights}),
                       ("two-reader/frozen-policy.json", {"mode": "deberta", "threshold": -2})]:
        path = "transfer/" + file
        regs[path] = write(root, path, data)
    selection = {"policy_sha256": regs["transfer/two-reader/frozen-policy.json"], "mode": "deberta", "threshold": -2}
    regs["transfer/selected-for-final.json"] = write(root, "transfer/selected-for-final.json", selection)
    protocol = {"mode": "deberta", "threshold": -2, "use_review": False,
                "development_selection_sha256": regs["transfer/selected-for-final.json"],
                "upstream_registration_sha256": regs["transfer/two-reader/preregistration.json"]}
    arms = plans["squad_en_primary"]["freeze"]
    regs[arms] = write(root, arms, protocol)
    for key in ("squad_en_primary", "squad_en_confirmation"):
        p = plans[key]
        docs, cases = splits[p["split"]]
        rows = []
        for c in cases:
            ranking = [c["source"], *[d for d in docs if d != c["source"]][:5]]
            pred = {"status": "abstained"} if c["impossible"] else {
                "status": "answered", **grounded(ranking[0], docs[ranking[0]]["content"])}
            rows.append({"id": c["id"], "hybrid_ids": ranking, "candidate": pred})
        raw = write(root, p["result"], rows)
        stats = {g: {"n": 32, "passed": 32, "rate": 1, "errors": 0} for g in gate.EN_GROUPS}
        suite["completed_report_sha256"][p["report"]] = write(root, p["report"], {
            "split": p["split"], "arms": {"candidate": stats}, "protocol_sha256": regs[arms], "measured_sha256": raw})
    p = plans["tydi_en_original"]
    docs = {f"doc{i}": {"content": f"Blue sample {i}."} for i in range(20)}
    cases, rows = [], []
    for i in range(48):
        impossible = i % 2 == 1
        qid = f"en-tydi-{i}"
        cases.append({"id": qid, "source": "doc0", "question": "What colour?",
                      "impossible": impossible, "answers": [] if impossible else [{"text": "Blue", "answer_start": 0}]})
        rows.append({"id": qid, "hybrid": list(docs), "baseline": [
            grounded(d, docs[d]["content"], j, -10 if impossible else 5) for j, d in enumerate(list(docs)[:6])]})
    digest = write(root, "tydi-en.json", {"documents": docs, "cases": cases})
    regs[p["reservation"]] = write(root, p["reservation"], {"case_ids": [c["id"] for c in cases],
                                                           "manifest_sha256": digest, "questions_per_stratum": 24})
    regs[p["freeze"]] = write(root, p["freeze"], {"inputs": weights})
    dev = "transfer/minilm/development-report.json"
    regs[dev] = write(root, dev, {"adopt": False, "protocol_sha256": regs[p["freeze"]]})
    stats = {"errors": 0, "metrics": {g: {"n": 24, "passed": 24, "rate": 1} for g in gate.EN_GROUPS}}
    suite["completed_report_sha256"][p["report"]] = write(root, p["report"], {
        "selected": "original frozen DeBERTa", "depth": 6, "threshold": -2,
        "baseline": stats, "candidate": stats, "protocol_sha256": regs[p["freeze"]],
        "measured_sha256": write(root, p["result"], rows)})


@pytest.fixture
def registered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Row]:
    # Replace only the registration fingerprint with that of the synthetic artifacts.
    suite = json.loads(gate.SUITE.read_bytes())
    suite["registrations"] = {"ko/rescue-profile.json": write(tmp_path, "ko/rescue-profile.json", {"fixture": True})}
    for key in ("klue_ko_final", "tydi_ko_final"):
        korean_fixture(tmp_path, suite, key)
    english_fixtures(tmp_path, suite)
    monkeypatch.setattr(gate, "SUITE_SHA", write(tmp_path, "public-suite.json", suite))
    return tmp_path, suite


def run(root: Path, *extra: str) -> int:
    return gate.main(["--root", str(root), "--squad", str(root / "squad.json"),
                      "--tydi-en", str(root / "tydi-en.json"), *extra])


def test_all_ten_and_replay_receipt(registered: tuple[Path, Row]) -> None:
    root, _ = registered
    receipt = root / "receipt.json"
    assert run(root, "--receipt", str(receipt)) == 0
    assert run(root, "--receipt", str(receipt)) == 0
    result = json.loads(receipt.read_bytes())
    assert result["passed"] and set(result["panels"]) == set(gate.REQUIRED)
    assert len({p["policy_sha256"] for p in result["panels"].values()}) == 2
    assert sum(len(p["sample_ids"]) for p in result["panels"].values()) == 384
    receipt.write_text("{}")
    assert run(root, "--receipt", str(receipt)) == 2


def test_one_missing_panels_stratum_and_real_error(registered: tuple[Path, Row]) -> None:
    root, suite = registered
    p = suite["panels"]["tydi_ko_final"]
    data = json.loads((root / p["result"]).read_bytes())
    for i in range(5):
        data["rows"][i] = {"id": data["rows"][i]["id"], "retrieved": ["doc"], "tool_retrieved": ["doc"],
                           "status": "error", "error": "timeout"}
    base = (root / p["reservation"]).parent
    data.update(gate.ko.grade(data["rows"], json.loads((base/"final.labels.json").read_bytes()),
                             json.loads((base/"final.corpus.json").read_bytes())))
    write(root, p["result"], data)
    receipt = root / "receipt.json"
    assert run(root, "--receipt", str(receipt)) == 1
    panel = json.loads(receipt.read_bytes())["panels"]["tydi_ko_final"]
    assert panel["answerable"]["correct"] == 19 and panel["unanswerable"]["correct"] == 24
    assert len(panel["errors"]) == 5
    assert all(v == "timeout" for v in panel["errors"].values())


@pytest.mark.parametrize("change", ["id", "denominator", "policy", "row_truth", "hidden_error", "fake_hit",
                                    "raw_hash", "report_hash", "roster"])
def test_rejects_invalid_or_substituted_evidence(registered: tuple[Path, Row], change: str) -> None:
    root, suite = registered
    p = suite["panels"]["klue_ko_final"]
    data = json.loads((root / p["result"]).read_bytes())
    if change == "id":
        data["rows"][0]["id"] = data["rows"][1]["id"]
    elif change == "denominator":
        data["summary"]["answerable"]["n"] -= 1
    elif change == "policy":
        data["identity"]["model_files"]["gguf"] = "other"
    elif change == "row_truth":
        data["rows"][0]["quote_start"] = -1
    elif change == "hidden_error":
        data["rows"][-1]["error"] = "provider timeout"
    elif change == "fake_hit":
        data["rows"][-1]["tool_retrieved"].append("unregistered-document")
    elif change in {"raw_hash", "report_hash"}:
        en = suite["panels"]["squad_en_confirmation"]
        name = en["result" if change == "raw_hash" else "report"]
        with (root / name).open("ab") as stream:
            stream.write(b" ")
    else:
        suite["panels"].pop("tydi_en_original")
        write(root, "public-suite.json", suite)
    write(root, p["result"], data)
    assert run(root) == 2


def test_preflight_before_scores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = gate.SUITE.read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == gate.SUITE_SHA
    (tmp_path / "public-suite.json").write_bytes(manifest)
    names = []
    orig = gate.Evidence.load

    def track(self: gate.Evidence, name: str, **kw: Any) -> Any:
        names.append(name)
        return orig(self, name, **kw)

    monkeypatch.setattr(gate.Evidence, "load", track)
    assert run(tmp_path) == 2
    assert names == ["public-suite.json"]


def test_threshold_is_inclusive_and_no_averaging() -> None:
    ids = [str(i) for i in range(10)]
    flags = [True]*5 + [False]*5
    assert gate.panel_summary(ids, flags, [True]*4+[False]+[True]*4+[False], {}, 5)["passed"]
    assert not gate.panel_summary(ids, flags, [False]*2+[True]*8, {}, 5)["passed"]


def test_tydi_error_and_top_six_order() -> None:
    docs = {str(i): {"content": "Blue sky."} for i in range(20)}
    row: Row = {"id": "tydi-1", "hybrid": list(docs), "baseline": {"error": "tokenizer failure"}}
    case = {"question": "What colour?"}
    pred, ranking = gate.english_prediction(case, row, docs, tydi=True)
    assert pred == {"status": "error", "reason": "tokenizer failure"}
    assert ranking == list(docs)[:6]
    row["baseline"] = [grounded(d, "Blue sky.", i) for i, d in enumerate(reversed(ranking))]
    with pytest.raises(ValueError, match="top six"):
        gate.english_prediction(case, row, docs, tydi=True)
