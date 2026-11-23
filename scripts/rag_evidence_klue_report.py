"""Compare matched development decisions and separate actual generation from frozen encoder corrections."""

import argparse
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

from scripts.rag_evidence_klue_run import BASE, MODES, OUT, load
from scripts.rag_growth_ko_eval import write_new
from scripts.rag_growth_local import file_sha256

Row = dict[str, Any]


def results(stage: str) -> Row:
    paths: dict[str, Path] = {m: OUT / m / (stage + ".json") for m in MODES}
    arms = {k: load(v) for k, v in paths.items()}
    controls = {r["id"]: r for r in arms["original"]["rows"]}
    historical = {r["id"]: r for r in load(BASE / "qwen/rescue-dev.json")["rows"]}
    truth = {r["id"]: r["answerable"] for r in arms["original"]["outcomes"]}
    old_scores = {r["id"]: r["correct"] for r in arms["original"]["outcomes"]}
    simple: Row = {}
    for name, data in arms.items():
        rows = {r["id"]: r for r in data["rows"]}
        scores = {r["id"]: r["correct"] for r in data["outcomes"]}
        if (set(rows) != set(controls) or set(scores) != set(controls)
                or any(r["retrieved"] != controls[i]["retrieved"] for i, r in rows.items())):
            raise ValueError("Arms were not run on the same passages")
        tally: Row = {}
        for group, yes in (("answerable", True), ("unanswerable", False)):
            ids = [i for i in rows if truth[i] == yes]
            tally[group] = {"correct": sum(scores[i] for i in ids), "n": len(ids),
                            "gained_ids": [i for i in ids if scores[i] and not old_scores[i]],
                            "lost_ids": [i for i in ids if old_scores[i] and not scores[i]]}
        raw_status = Counter(r["raw_status"] for r in rows.values())
        final_status = Counter(r["status"] for r in rows.values())
        tally.update(first_status=dict(raw_status), final_status=dict(final_status),
                     calls=sum(r["request"]["calls"] for r in rows.values()),
                     missing_usage=sum(not r["request"].get("usage") for r in rows.values()),
                     input_tokens=sum((r["request"].get("usage") or {}).get("prompt_tokens", 0) for r in rows.values()),
                     output_tokens=sum((r["request"].get("usage") or {}).get("completion_tokens", 0) for r in rows.values()),
                     explicit_refusals_rescued=sum(
                         r["raw_status"] == "abstained" and r["status"] == "answered" for r in rows.values()),
                     median_seconds=median(r["seconds"] for r in rows.values()))
        simple[name] = tally
    fields = ("answer", "source_id", "start", "end", "quote", "quote_start", "quote_end", "status")
    drift = [i for i, r in controls.items() if any(r.get(f) != historical[i].get(f) for f in fields)]
    return {"scope": "Development only; both arms actually generated. Same retrieved article and cached raw encoder "
                     "outputs shared by all policies. This cohort was used for selection.",
            "stage": stage, "question_n": len(controls), "arms": simple,
            "historical_incumbent_final_response_changed_ids": drift,
            "original_input_sha256": {m: file_sha256(path) for m, path in paths.items()}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("screen", "rest"))
    stage = parser.parse_args().stage
    write_new(OUT / ("paired-" + stage + ".json"), results(stage))
