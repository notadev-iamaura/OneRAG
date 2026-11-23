"""Exploratory confidence routing between two measured KLUE prompts; fit its rule only on prior train calibration."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from app.modules.core.generation.korean_evidence_routing import confidence
from app.modules.core.generation.korean_evidence_selection import KoreanEvidenceSelector
from scripts.rag_evidence_klue_run import BASE, OUT, load
from scripts.rag_evidence_klue_train import DATA, references
from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import file_sha256

Row = dict[str, Any]
CUTOFF = OUT / "routing-calibration.json"
PARAMS = OUT / "sentence-weights-balanced.json"


def calibrate() -> None:
    weight = KoreanEvidenceSelector("trained", PARAMS)
    path = DATA / "calibration.jsonl"
    data = []
    for q in load(path):
        conf, first = confidence(weight, q["question"], q["context"])
        _, refs = references(q)
        data.append((conf, not q["is_impossible"] and first in refs))
    thresholds = sorted({c for c, _ in data})
    def objective(cut: float) -> tuple[float, int]:
        chosen = [right for c, right in data if c >= cut]
        tp = sum(chosen)
        # F0.5 favors showing evidence when the leading sentence is actually annotated.
        return (1.25 * tp / (len(chosen) + .25 * sum(v for _, v in data)), len(chosen))
    cut = max(thresholds, key=objective)
    chosen = [v for c, v in data if c >= cut]
    write_new(CUTOFF, {"train_heldout_sha": file_sha256(path), "n": len(data), "shown": len(chosen),
                       "top_sentence_correct_when_shown": sum(chosen), "cut": cut,
                       "source": file_sha256(Path(__file__)), "ranker": file_sha256(PARAMS),
                       "router": file_sha256(BASE.parents[1] / "app/modules/core/generation/korean_evidence_routing.py"),
                       "scope": "Additional diagnostic after seeing original/lexical 24 scores. No KLUE dev labels "
                                "or generated outputs used for fitting. Freeze before calculating dev complementarity."})


def evaluate(stage: str) -> None:
    cutoff = load(CUTOFF)
    router = BASE.parents[1] / "app/modules/core/generation/korean_evidence_routing.py"
    if (cutoff["source"] != file_sha256(Path(__file__)) or cutoff["ranker"] != file_sha256(PARAMS)
            or cutoff["router"] != file_sha256(router)):
        raise ValueError("Routing rule changed")
    docs = load(BASE / "panels/dev.corpus.json")
    body = {d["id"]: d["content"] for d in docs}
    qs = {q["id"]: q["question"] for q in load(BASE / "panels/dev.questions.json")}
    baseline = load(OUT / "original" / (stage + ".json"))
    candidate = {r["id"]: r for r in load(OUT / "trained" / (stage + ".json"))["rows"]}
    weights = KoreanEvidenceSelector("trained", PARAMS)
    rows = []
    for original in baseline["rows"]:
        key = original["id"]
        doc, = original["retrieved"]
        if candidate[key]["retrieved"] != [doc]:
            raise ValueError("Different source article")
        score, _ = confidence(weights, qs[key], body[doc])
        show = score >= cutoff["cut"]
        rows.append({**(candidate[key] if show else original), "displayed_hint": show})
    ids = {r["id"] for r in rows}
    labels = [r for r in load(BASE / "panels/dev.labels.json") if r["id"] in ids]
    write_new(OUT / ("routing-" + stage + ".json"), {"rows": rows, **grade(rows, labels, docs),
              "actual_highlighted": sum(r["displayed_hint"] for r in rows), "fresh_calls": 0,
              "calibration": file_sha256(CUTOFF)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("calibrate", "screen", "rest"))
    args = parser.parse_args()
    if args.stage == "calibrate":
        calibrate()
    else:
        evaluate(args.stage)
