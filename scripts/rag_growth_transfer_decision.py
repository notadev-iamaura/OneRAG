"""Freeze the better development iteration and report paired results on an untouched English panel."""

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_growth_transfer as tr
from scripts import rag_growth_transfer_ensemble as ensemble
from scripts.rag_growth_transfer_diagnostics import wilson


def choose(root):
    if any((folder / (split + ".jsonl")).exists() for folder in (root, root / "two-reader") for split in ("final", "confirmation")):
        raise ValueError("Selection must occur before any independent panel is opened")
    paths = [root / "development-report.json", root / "two-reader/development-report.json"]
    evidence = [tr.load(p) for p in paths]
    def objective(i):
        scores = [v["rate"] for v in evidence[i]["candidate"].values()]
        return min(scores), sum(scores), -i
    best = max(range(2), key=objective)
    return {"iteration": best + 1, "mode": evidence[best].get("mode", "deberta_top3"),
            "threshold": evidence[best]["threshold"], "development": evidence[best]["candidate"],
            "development_reports_sha256": [tr.file_sha256(p) for p in paths],
            "policy_sha256": tr.file_sha256((root / "two-reader" if best else root) / "frozen-policy.json"),
            "selection_rule": "Highest minimum stratum accuracy, then sum of stratum rates, then lowest iteration number."}


def report(root, source, phase):
    chosen = tr.load(root / "selected-for-final.json")
    if tr.file_sha256(source) != tr.DATA_SHA:
        raise ValueError("SQuAD source differs from preregistration")
    original = tr.load(root / "preregistration.json")
    docs, cases = tr.panels(tr.load(source)["data"])[phase]
    if tr.json_sha256([docs, cases]) != original["panels"][phase]["manifest_sha256"]:
        raise ValueError("Reserved scoring labels or corpus changed")
    measurements = root / "two-reader" / (phase + ".jsonl")
    summary = tr.load(root / "two-reader" / (phase + "-report.json"))
    if tr.file_sha256(measurements) != summary["measured_sha256"]:
        raise ValueError("Raw model scores changed")
    rows = {r["id"]: r for r in map(json.loads, measurements.read_text().splitlines())}
    if rows.keys() != {c["id"] for c in cases}:
        raise ValueError("Missing or unexpected questions")
    frozen = (root / "two-reader" if chosen["iteration"] == 2 else root) / "frozen-policy.json"
    if chosen["policy_sha256"] != tr.file_sha256(frozen):
        raise ValueError("Frozen model policy changed")
    bins = {}
    for label, impossible in (("positive", False), ("negative", True)):
        pairs = []
        for case in cases:
            if case["impossible"] != impossible:
                continue
            r = rows[case["id"]]
            v1 = {"error": r["error"]} if "error" in r else {"spans": r["deberta"], "lexical": r["lexical"][:3], "hybrid": r["hybrid"][:3]}
            original_pred = tr.predict(v1, 0, "baseline")
            candidate = (tr.predict(v1, chosen["threshold"], "candidate") if chosen["iteration"] == 1 else
                         ensemble.prediction(case, r, chosen["mode"], chosen["threshold"]))
            pairs.append((tr.grade(case, original_pred, docs), tr.grade(case, candidate, docs)))
        baseline, candidate = (sum(p[i] for p in pairs) for i in (0, 1))
        bins[label] = {"n": len(pairs), "baseline": baseline, "candidate": candidate,
                       "candidate_rate": candidate / len(pairs), "wins": sum(b and not a for a, b in pairs),
                       "losses": sum(a and not b for a, b in pairs), "candidate_wilson_95": wilson(candidate, len(pairs))}
    return {"split": phase, "iteration": chosen["iteration"], "mode": chosen["mode"], "threshold": chosen["threshold"],
            "bins": bins, "both_at_least_80": all(b["candidate_rate"] >= .8 for b in bins.values()),
            "errors": summary["errors"], "measured_sha256": summary["measured_sha256"],
            "selection_sha256": tr.file_sha256(root / "selected-for-final.json")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "final", "confirmation"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dataset", type=Path)
    args = parser.parse_args()
    if args.action == "freeze":
        result = choose(args.output)
        path = args.output / "selected-for-final.json"
    else:
        if args.dataset is None:
            parser.error("--dataset is required to score a measured panel")
        result = report(args.output, args.dataset, args.action)
        path = args.output / (args.action + "-decision.json")
    tr.dump(path, result)
    print(json.dumps(result))
