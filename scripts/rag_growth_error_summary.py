"""Summarize observable retrieval, answer boundary and abstention failures after grading."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.rag_growth_gate import normalized
from scripts.rag_growth_ko_eval import write_new


def summarize(
    rows: list[dict[str, Any]], labels: list[dict[str, Any]], outcomes: list[dict[str, Any]]
) -> dict[str, Any]:
    labels_by_id = {r["id"]: r for r in labels}
    correctness = {r["id"]: r["correct"] for r in outcomes}
    observed: dict[str, list[str]] = {}
    for row in rows:
        qid = row["id"]
        if correctness[qid]:
            continue
        label = labels_by_id[qid]
        if row["status"] == "error":
            reason = "execution_or_format_error"
        elif not label["answerable"]:
            reason = "answered_native_unanswerable"
        elif label["source_id"] not in row["retrieved"]:
            reason = "source_not_retrieved"
        elif row["status"] == "abstained":
            reason = "abstained_despite_retrieved_source"
        elif row.get("source_id") != label["source_id"]:
            reason = "selected_other_source"
        else:
            output = normalized(row.get("answer", ""))
            aliases = {normalized(a) for a in label["answers"]}
            if output in aliases:
                reason = "exact_text_but_unverified_annotated_occurrence"
            elif output and any(a in output or output in a for a in aliases):
                reason = "shorter_or_longer_than_reference"
            else:
                reason = "other_answer_in_correct_source"
        observed.setdefault(reason, []).append(qid)
    return {"counts": {r: len(q) for r, q in observed.items()}, "case_ids": observed,
            "statuses": dict(Counter(r["status"] for r in rows))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("result", "labels", "output"):
        parser.add_argument("--"+name, required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.result.read_bytes())
    write_new(args.output, summarize(data["rows"], json.loads(args.labels.read_bytes()), data["outcomes"]))
