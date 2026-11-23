import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import rag_growth_local as local
from scripts.rag_growth_gate import failure, main, paired_outcomes


def panel(split="development", positives=2, negatives=2):
    cases = []
    for i in range(positives + negatives):
        yes = i < positives
        cases.append({"id": f"q{i}", "question": f"공개 문항 {i}의 값은?",
                      "answerable": yes, "answers": ["1.5원", "일 점 오 원"] if yes else [],
                      "source_ids": [f"s{i}"] if yes else []})
    return {"schema_version": 1, "model": "M", "index": "I", "dataset": "D",
            "split": split, "trials": 3, "cases": cases}


def fixtures(directory: Path, manifest):
    source = directory / "manifest.json"
    source.write_text(json.dumps(manifest, ensure_ascii=False))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    runs = {}
    for policy in ("baseline", "candidate"):
        rows = []
        for case in manifest["cases"]:
            for trial in (1, 2, 3):
                yes = case["answerable"]
                row = {"id": case["id"], "trial": trial, "policy": policy, "model": "M", "index": "I",
                       "manifest_sha256": digest, "status": "answered" if yes else "abstained",
                       "answer": "1.5원" if yes else "근거 부족", "citations": list(case["source_ids"]),
                       "candidates": list(case["source_ids"]), "tokens": 10, "latency_ms": 12.5}
                if policy == "baseline" and case["id"] == "q0":
                    row["answer"] = "15원"
                rows.append(row)
        runs[policy] = rows
    return runs


def attach_measurements(directory, runs):
    path = directory / "manifest.json"
    manifest = json.loads(path.read_bytes())
    docs = [{"id": "s" + c["id"][1:], "title": c["id"], "content": "요금은 1.5원이다. 행사장은 서울이다."}
            for c in manifest["cases"]]
    manifest.update(documents=docs, corpus_sha256=local.corpus_sha256(docs), model_sha256="b" * 64, index=local.INDEX_ID)
    path.write_text(json.dumps(manifest, ensure_ascii=False))
    metadata = {k: manifest[k] for k in ("dataset", "split", "index", "model_sha256", "corpus_sha256")}
    metadata.update(manifest_sha256=local.file_sha256(path), index_sha256=local.index_sha256(docs),
                    agent_sha256=local.agent_sha256(), runner_sha256=local.file_sha256(Path(local.__file__)),
                    api_model=manifest["model"], temperature=0, max_tokens=640, fresh_agent_each_trial=True,
                    model_cache="shared prefix", model_calls=1)
    for rows in runs.values():
        for r in rows:
            doc_id = "s" + r["id"][1:]
            answered = r["status"] == "answered"
            r.update(metadata, candidates=[doc_id], candidate_batches=[[doc_id]], citations=[doc_id] if answered else [],
                     cited_evidence=[{"document_id": doc_id, "quote": "요금은 1.5원이다."}] if answered else [],
                     grounding_status="verified_quotes" if answered else "insufficient",
                     stop_reason="completed" if answered else "no_new_evidence")


def run(directory, rows):
    for name, run_rows in rows.items():
        (directory / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in run_rows))
    output = directory / "result.json"
    code = main(["--manifest", str(directory / "manifest.json"), "--baseline", str(directory / "baseline.jsonl"),
                 "--candidate", str(directory / "candidate.jsonl"), "--output", str(output)])
    return code, json.loads(output.read_text())


def test_paired_results_use_fixed_trials_and_both_strata(tmp_path):
    rows = fixtures(tmp_path, panel())
    rows["candidate"].reverse()
    attach_measurements(tmp_path, rows)
    code, result = run(tmp_path, rows)
    assert code == 0 and result["decision"] == "eligible_for_holdout"
    assert result["release_certified"] is False
    for primary in ["first", "all3"]:
        counts = result["bins"]["answerable"][primary]
        assert (counts["baseline"], counts["candidate"], counts["improved"], counts["regressed"]) == (1, 2, 1, 0)
        assert counts["n"] == 2 and counts["candidate_rate"] == 1
    assert list(result["bins"]["unanswerable"]["trials"]) == ["1", "2", "3"]
    assert result["errors"] == {"baseline": 0, "candidate": 0}
    assert result["budget"]["candidate"]["n"] == 12 and result["budget"]["token_ratio"] == 1
    assert result["policy_suggestions"] == []


def test_bootstrap_resamples_paired_questions_once_and_is_deterministic():
    pairs = [(False, True), (True, True), (True, False)]
    estimate = paired_outcomes(pairs)["rate_difference"]
    assert estimate == paired_outcomes(pairs)["rate_difference"]
    assert estimate["estimate"] == 0 and estimate["n_questions"] == 3 and estimate["resamples"] == 2000
    assert estimate["ci95"][0] < 0 < estimate["ci95"][1]
    assert paired_outcomes([(True, True)] * 4)["rate_difference"]["ci95"] == [0, 0]


@pytest.mark.parametrize(("text", "good"), [
    ("１.５원.", True), ("일  점 오 원", True), ("15원", False), ("-1.5원", False),
    ("11.5원", False), ("답은 1.5원이나 달라질 수 있다", False),
])
def test_exact_alias_protects_amount_and_sign(text, good):
    c = panel()["cases"][0]
    r = {"answer": text, "status": "answered", "tokens": 10, "citations": ["s0"], "candidates": ["s0"]}
    assert (failure(c, r) is None) == good


@pytest.mark.parametrize(("edits", "reason"), [
    ({"status": "error", "answer": "근거 부족"}, "model_error"),
    ({"answer": ""}, "empty_response"),
    ({"tokens": 0}, "no_model_tokens"),
    ({"status": "abstained", "answer": "텍스트가 가리키는 값은 15원"}, "inconsistent_status"),
    ({"status": "abstained", "answer": "근거 부족", "citations": []}, "unnecessary_abstention"),
    ({"status": "abstained", "answer": "근거 부족"}, "cited_abstention"),
    ({"citations": ["s404"]}, "citation_outside_candidates"),
    ({"candidates": [], "citations": []}, "retrieval_miss"),
    ({"citations": []}, "incorrect_sources"),
    ({"candidates": ["s0", "s1"], "citations": ["s1", "s0"]}, "incorrect_sources"),
])
def test_failure_attribution(edits, reason):
    c = panel()["cases"][0]
    r = {"answer": "1.5원", "status": "answered", "tokens": 1, "citations": ["s0"], "candidates": ["s0"]}
    assert failure(c, r | edits) == reason


def test_invalid_citation_classification_is_distinct_from_runtime_failure():
    assert failure({"answerable": False}, {"status": "error", "answer": "근거 부족",
                                           "grounding_status": "invalid_citation", "stop_reason": "error",
                                           "tokens": 12, "model_calls": 1}) == "invalid_citation"


def test_only_a_measured_baseline_citation_failure_can_be_repaired(tmp_path):
    rows = fixtures(tmp_path, panel())
    attach_measurements(tmp_path, rows)
    baseline = rows["baseline"][0]
    baseline.update(status="error", answer="근거 부족", citations=[], cited_evidence=[],
                    stop_reason="error", grounding_status="invalid_citation")
    code, result = run(tmp_path, rows)
    assert code == 0 and result["eligible"]
    assert result["failure_counts"]["baseline"]["invalid_citation"] == 1 and result["errors"]["baseline"] == 1
    rows["candidate"][0].update(status="error", answer="근거 부족", citations=[], cited_evidence=[],
                                stop_reason="error", grounding_status="invalid_citation")
    assert "execution_errors" in run(tmp_path, rows)[1]["reasons"]
    rows["candidate"][0].update(status="answered", answer="1.5원", citations=["s0"],
                                cited_evidence=[{"document_id": "s0", "quote": "요금은 1.5원이다."}],
                                stop_reason="completed", grounding_status="verified_quotes")
    baseline.update(tokens=0, model_calls=0)
    code, result = run(tmp_path, rows)
    assert code == 1 and "execution_errors" in result["reasons"] and result["failure_counts"]["baseline"]["model_error"] == 1


def test_answer_span_missing_from_verbatim_quote_failure_is_actionable(tmp_path):
    rows = fixtures(tmp_path, panel())
    attach_measurements(tmp_path, rows)
    for row in rows["candidate"]:
        if row["id"] == "q0":
            row["cited_evidence"][0]["quote"] = "행사장은 서울이다."
    code, result = run(tmp_path, rows)
    assert code == 1 and result["decision"] == "rejected"
    assert result["failure_counts"]["candidate"] == {"answer_span_not_in_citation": 3}
    assert result["development_failures"][0]["cited_evidence"][0]["quote"] == "행사장은 서울이다."


@pytest.mark.parametrize("split", ["development", "holdout"])
def test_legacy_diagnostic_manifest_cannot_certify_even_if_perfect(tmp_path, split):
    rows = fixtures(tmp_path, panel(split, 24, 12))
    code, result = run(tmp_path, rows)
    assert code == 1 and result["eligible"] is False and result["decision"] == "unverified"
    assert result["evidence_status"] == "diagnostic_only" and "missing_source_provenance" in result["reasons"]


def test_standalone_cli_validates_registered_artifact_from_outside_checkout(tmp_path):
    rows = fixtures(tmp_path, panel())
    attach_measurements(tmp_path, rows)
    run(tmp_path, rows)
    r = rows["candidate"][0]
    provenance = {k: r[k] for k in ("api_model", "runner_sha256", "agent_sha256", "index_sha256")}
    registered = tmp_path / "registered.json"
    registered.write_text(json.dumps(provenance))
    report = tmp_path / "reviewed.json"
    script = Path(__file__).resolve().parents[3] / "scripts/rag_growth_gate.py"
    command = [sys.executable, "-I", str(script), "--manifest", "manifest.json", "--baseline", "baseline.jsonl",
               "--candidate", "candidate.jsonl", "--output", report.name, "--expected-provenance", registered.name]
    assert subprocess.run(command, cwd=tmp_path).returncode == 0
    registered.write_text(json.dumps({**provenance, "agent_sha256": "3" * 64}))
    assert subprocess.run(command, cwd=tmp_path).returncode == 2
    assert json.loads(report.read_bytes())["decision"] == "invalid"


def test_exposes_only_development_failures_with_executable_next_action(tmp_path):
    m = panel()
    rows = fixtures(tmp_path, m)
    for r in rows["candidate"]:
        if r["id"] == "q2":
            r.update(status="answered", answer="22원", citations=["s42"], candidates=["s42"])
    code, result = run(tmp_path, rows)
    assert code == 1 and set(result["reasons"]) == {"missing_source_provenance", "unanswerable_regression"}
    assert result["development_failures"][0]["question"] == m["cases"][2]["question"]
    assert result["policy_suggestions"] == [
        {"reason": "unsupported_answer", "failed_cases": 1, "failed_trials": 3,
         "action": "답변 전에 원문이 질문의 주체와 조건을 모두 뒷받침하는지 검증한다."}
    ]
    m["split"] = "holdout"
    rows = fixtures(tmp_path, m)
    rows["candidate"][0]["answer"] = "비공개 홀드아웃 오답"
    code, result = run(tmp_path, rows)
    assert code == 1 and result["development_failures"] == [] and result["policy_suggestions"] == []
    assert all(s not in json.dumps(result, ensure_ascii=False) for s in (
        m["cases"][0]["question"], "비공개 홀드아웃 오답", m["cases"][0]["source_ids"][0],
    ))


def test_guardrails_reject_ties_same_version_trial_regression_and_cost(tmp_path):
    rows = fixtures(tmp_path, panel())
    for r in rows["candidate"]:
        r["policy"] = "baseline"
        r["tokens"] = 16
        if r["trial"] == 2 and r["id"] == "q2":
            r.update(status="error", answer="")
    code, result = run(tmp_path, rows)
    assert code == 1
    assert set(result["reasons"]) == {
        "same_policy", "token_budget_exceeded", "unanswerable_regression", "execution_errors", "missing_source_provenance",
    }
    assert result["bins"]["unanswerable"]["first"]["regressed"] == 0
    assert result["bins"]["unanswerable"]["trials"]["2"]["regressed"] == 1
    assert result["bins"]["unanswerable"]["all3"]["regressed"] == 1
    assert result["errors"]["candidate"] == 1
    rows["candidate"] = [{**r, "policy": "renamed"} for r in rows["baseline"]]
    assert set(run(tmp_path, rows)[1]["reasons"]) == {"no_first_or_all3_improvement", "missing_source_provenance"}


@pytest.mark.parametrize(("field", "value"), [
    ("trial", 0), ("trial", True), ("manifest_sha256", "other"), ("model", "other"), ("index", "other"),
    ("policy", "mixed"), ("tokens", -1), ("latency_ms", float("nan")), ("citations", "s0"),
    ("status", "unknown"), ("id", "unexpected"),
])
def test_mismatched_or_invalid_run_is_unscorable(tmp_path, field, value):
    rows = fixtures(tmp_path, panel())
    rows["candidate"][0][field] = value
    code, report = run(tmp_path, rows)
    assert code == 2 and report["decision"] == "invalid" and report["eligible"] is False


def test_missing_duplicates_and_single_class_are_invalid(tmp_path):
    rows = fixtures(tmp_path, panel())
    removed = rows["candidate"].pop()
    assert run(tmp_path, rows)[0] == 2
    rows["candidate"] += [removed, removed]
    assert run(tmp_path, rows)[0] == 2
    rows = fixtures(tmp_path, panel(negatives=0))
    assert run(tmp_path, rows)[0] == 2


def test_holdout_absolute_counts_apply_to_all_three_and_require_full_sample(tmp_path):
    rows = fixtures(tmp_path, panel("holdout", 24, 12))
    for r in rows["candidate"]:
        i = int(r["id"][1:])
        if r["trial"] == 2 and (20 <= i < 24 or i >= 33):
            r["status"], r["answer"] = "answered", "오답"
    # Same hard cases in the baseline, plus one extra answerable failure.
    for a, b in zip(rows["baseline"], rows["candidate"], strict=True):
        if b["answer"] == "오답":
            a.update(status=b["status"], answer=b["answer"])
    attach_measurements(tmp_path, rows)
    code, report = run(tmp_path, rows)
    assert code == 0 and report["decision"] == "confirmed_on_panel" and report["release_certified"] is False
    assert report["bins"]["answerable"]["all3"]["candidate"] == 20
    assert report["bins"]["unanswerable"]["all3"]["candidate"] == 9
    rows["candidate"][3]["answer"] = "오답"
    code, report = run(tmp_path, rows)
    assert code == 1 and "answerable_holdout_requirement" in report["reasons"]
    code, report = run(tmp_path, fixtures(tmp_path, panel("holdout")))
    assert code == 1 and "unanswerable_holdout_requirement" in report["reasons"]
