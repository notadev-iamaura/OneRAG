"""Measure raw-only span ceilings inside the selected original document after replication has been scored."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))

from app.modules.core.generation import tydi_evidence_context as ctx
from app.modules.core.generation.korean_span_reader import SpanAnswer
from app.modules.core.generation.tydi_evidence_selection import THRESHOLD
from scripts import rag_evidence_tydi as exp
from scripts import rag_evidence_tydi_replication as rep
from scripts.rag_growth_ko_eval import write_new
from scripts.rag_growth_local import file_sha256


def bounds(cases, raw_by_q, gold, control):
    totals = dict.fromkeys(("positive_n", "gold_in_top8", "gold_passed_qa_and_support",
                            "raw_correct_on_eligible_gold", "control_picked_gold_and_answered",
                            "raw_correct_in_selected_document", "negative_n", "control_refusals_on_negatives"), 0)
    for c in cases:
        qid = c.question["id"]
        old, label = control[qid], gold[qid]
        if not label["answerable"]:
            totals["negative_n"] += 1
            totals["control_refusals_on_negatives"] += old["status"] == "abstained"
            continue
        totals["positive_n"] += 1
        idx = next((i for i, d in enumerate(c.docs) if d["id"] == label["source_id"]), None)
        if idx is None:
            continue
        totals["gold_in_top8"] += 1
        if c.incumbent_error or c.full[idx] <= 0 or c.original[idx].score <= THRESHOLD:
            continue
        totals["gold_passed_qa_and_support"] += 1
        chosen = old["status"] == "answered" and old["source_id"] == label["source_id"]
        totals["control_picked_gold_and_answered"] += chosen
        row = raw_by_q[qid]
        if c.error or row.get("error"):
            continue
        limits = [ctx.ContextWindow(w["document_index"], w["start"], w["end"]) for w in row["windows"]]
        local = [[SpanAnswer(**s) for s in w["readings"]] for w in row["windows"]]
        groups = ctx.expand(c.docs, c.candidates, limits, local)
        contains = any(exp.exact(s, label) for s in [c.original[idx], *groups[idx]])
        totals["raw_correct_on_eligible_gold"] += contains
        totals["raw_correct_in_selected_document"] += chosen and contains
    return totals


def run(out):
    _, lock, score = rep.checked_lock(out)
    if not score.exists():
        raise ValueError("Open labels only after the common paired score is complete")
    report = json.loads(score.read_bytes())
    if any(report[key + "_rows_sha256"] != file_sha256(Path(lock[key + "_rows"])) for key in ("control", "candidate")):
        raise ValueError("Changed predictions since independent scoring")
    _, cases, part = exp.load_cached("final", rep.PANELS / rep.PANEL, out)
    gold = {r["id"]: r for r in part("labels")}
    control = {r["id"]: r for r in json.loads(Path(lock["control_rows"]).read_bytes())}
    raw = out / "final.window-readings.jsonl"
    write_new(out / "final.policy-ceiling.json", {"common_score_sha256": file_sha256(score),
              "raw_windows_sha256": file_sha256(raw), "audit_code_sha256": file_sha256(Path(__file__)),
              "counts": bounds(cases, exp.lines(raw), gold, control)})


if __name__ == "__main__":
    run(rep.cache.OUT / "replication")
