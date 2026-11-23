"""Attribute SQuAD transfer failures from registered local inference without running the reader again."""

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_growth_transfer as tr


def wilson(wins, n):
    z = 1.959963984540054
    p = wins / n
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / (1 + z * z / n)
    return [max(0.0, center - half), min(1.0, center + half)]


def diagnostics(docs, cases, rows, threshold):
    counts = Counter()
    failures = Counter()
    decisions = {}
    for case in cases:
        row = rows[case["id"]]
        positive = not case["impossible"]
        pred = tr.predict(row, threshold, "candidate")
        passed = tr.grade(case, pred, docs)
        counts["positive_n" if positive else "negative_n"] += 1
        if positive:
            for name, ids in (("lexical_at_1", row.get("lexical", [])[:1]), ("lexical_at_3", row.get("lexical", [])),
                              ("hybrid_at_3", row.get("hybrid", []))):
                counts[name] += case["source"] in ids
            raw = row.get("oracle")
            gold_ok = bool(raw and tr.grade(case, {"status": "answered", **raw}, docs))
            counts["forced_exact_given_reference"] += gold_ok
            counts["forced_exact_in_hybrid_candidates"] += gold_ok and case["source"] in row.get("hybrid", [])
            if not passed:
                if "error" in row:
                    cause = "runtime_error"
                elif case["source"] not in row["hybrid"]:
                    cause = "reference_not_in_hybrid_top3"
                elif not gold_ok:
                    cause = "wrong_span_in_reference"
                elif pred["status"] == "abstained":
                    cause = "abstained_with_correct_span_available"
                else:
                    cause = "selected_distractor_instead_of_correct_span"
                failures[cause] += 1
        elif not passed:
            failures["runtime_error" if pred["status"] == "error" else "answered_native_unanswerable"] += 1
        decisions[case["id"]] = passed
    candidate = tr.metrics(docs, cases, rows, threshold, "candidate")
    paired = Counter()
    for case in cases:
        before = tr.grade(case, tr.predict(rows[case["id"]], 0, "baseline"), docs)
        after = decisions[case["id"]]
        stratum = "negative" if case["impossible"] else "positive"
        paired[stratum + ("_gain" if after else "_loss")] += before != after
    return {"counts": dict(counts), "candidate_failure_reasons": dict(failures),
            "baseline_to_candidate_question_changes": dict(paired),
            "candidate_wilson_95": {k: wilson(v["passed"], v["n"]) for k, v in candidate.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=tr.SIZES)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if tr.file_sha256(args.dataset) != tr.DATA_SHA:
        raise ValueError("Official source hash mismatch")
    source = args.output / (args.phase + ".jsonl")
    report = tr.load(args.output / (args.phase + "-report.json"))
    protocol = tr.load(args.output / "preregistration.json")
    docs, cases = tr.panels(tr.load(args.dataset)["data"])[args.phase]
    if (tr.json_sha256([docs, cases]) != protocol["panels"][args.phase]["manifest_sha256"]
            or tr.file_sha256(source) != report["measured_sha256"]):
        raise ValueError("Registered corpus, cases or measured rows mismatch")
    rows = {r["id"]: r for r in map(json.loads, source.read_text().splitlines())}
    output = diagnostics(docs, cases, rows, report["threshold"])
    tr.dump(args.output / (args.phase + "-diagnostics.json"), output)
    print(json.dumps(output))


if __name__ == "__main__":
    main()
