"""Attribute observed errors after the supervised development decision without changing its policy."""

import argparse
import sys
from collections import Counter
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation import english_calibrated_spans as cal
from scripts import rag_growth_transfer as tr
from scripts import rag_growth_transfer_fit as fit
from scripts.rag_growth_transfer_train_features import read_jsonl


def run(args):
    root = args.output
    trained = tr.load(root / "calibrator.json")
    scored = tr.load(root / "development-report.json")
    audit = {}
    for name in ("squad", "development"):
        rows = fit.samples(args, name)
        predicted = read_jsonl(root / (name + "-verdicts.jsonl"))
        failures, paired = Counter(), Counter()
        decisions = []
        for r in rows:
            ans, p = fit.answer_probability(r, trained)
            actual = cal.decide(ans, p, r.incumbent, trained["mode"], trained["threshold"])
            if predicted[r.case["id"]]["prediction"] != fit.verdict(actual):
                raise ValueError("Frozen development prediction cannot be reproduced")
            correct = (
                r.incumbent_ok
                if actual == r.incumbent
                else (r.case["impossible"] if actual is None else r.exact[r.answers.index(actual)])
            )
            group = "negative" if r.case["impossible"] else "positive"
            if correct != r.incumbent_ok:
                paired[group + ("_won" if correct else "_lost")] += 1
            if correct:
                continue
            if r.case["impossible"]:
                reason = "answered_native_unanswerable"
            elif not r.gold_retrieved:
                reason = "reference_not_in_top12"
            elif not any(r.exact):
                reason = "no_scoring_candidate_on_reference"
            elif actual is None:
                reason = "abstained_while_gold_proposed"
            elif actual.source_id != r.case["source"]:
                reason = "selected_other_document_while_gold_proposed"
            else:
                reason = "selected_other_span_on_correct_document"
            failures[reason] += 1
            decisions.append(
                {
                    "id": r.case["id"],
                    "failure": reason,
                    "ranker_first_exact": bool(ans and r.exact[r.answers.index(ans)]),
                    "incumbent_correct": r.incumbent_ok,
                    "answerability_probability": p,
                }
            )
        if sum(failures.values()) != sum(
            g["n"] - g["passed"] for g in scored["candidate"][name]["metrics"].values()
        ):
            raise ValueError("Failure groups do not reconcile with the frozen report")
        audit[name] = {"failures": dict(failures), "paired": dict(paired), "cases": decisions}
    tr.dump(
        root / "selection-audit.json",
        {
            "development_report_sha256": tr.file_sha256(root / "development-report.json"),
            "calibrator_sha256": tr.file_sha256(root / "calibrator.json"),
            "cases": audit,
        },
    )
    print({k: (v["failures"], v["paired"]) for k, v in audit.items()})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("output", "train", "squad", "tydi"):
        p.add_argument("--" + key, type=Path, required=True)
    run(p.parse_args())
