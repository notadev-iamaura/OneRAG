"""Fit a source-mention ranker on previous KLUE training articles and measure it without another model call."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.modules.core.generation.korean_evidence_mentions import FEATURES, mentions, select_mention
from scripts.rag_evidence_klue_run import BASE, load
from scripts.rag_evidence_klue_train import DATA, examples
from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import ROOT, file_sha256

OUT = ROOT / "output/rag-evidence-selection/mentions"


def repeated(rows):
    for row in rows:
        answers = row["answers"]
        offsets: dict[str, set[int]] = {}
        for text, pos in zip(answers["text"], answers["answer_start"], strict=True):
            if row["context"][pos:pos + len(text)] == text:
                offsets.setdefault(text, set()).add(pos)
        for text, gold in offsets.items():
            options = mentions(row["question"], row["context"], text)
            if any(o.start in gold for o in options) and any(o.start not in gold for o in options):
                yield options, gold


def calibration(cases, weights, margin):
    correct_first = moves_to_gold = moves_from_gold = 0
    for options, gold in cases:
        scores = {c.start: sum(w * v for w, v in zip(weights, c.features, strict=True)) for c in options}
        top = max(scores, key=scores.__getitem__)
        original = options[0].start
        moved = scores[top] > scores[original] + margin
        correct_first += (top if moved else original) in gold
        moves_to_gold += moved and original not in gold and top in gold
        # Also simulate a reader that selected an annotated occurrence to start with.
        moves_from_gold += top not in gold and any(scores[top] > scores[o] + margin for o in scores if o in gold)
    return {"n": len(cases), "first_correct_after": correct_first, "new_correct": moves_to_gold,
            "lost_initially_correct": moves_from_gold}


def fit():
    from sklearn.linear_model import LogisticRegression

    paths = [DATA / (name + ".jsonl") for name in ("fit", "calibration", "development")]
    partitions = [examples(path) for path in paths]
    articles = [{r["context"] for r in rows} for rows in partitions]
    if any(a & b for i, a in enumerate(articles) for b in articles[i + 1:]):
        raise ValueError("Overlapping training, calibration and development articles")
    pairs, y = [], []
    for options, gold in repeated(partitions[0]):
        for pos in (o for o in options if o.start in gold):
            for neg in (o for o in options if o.start not in gold):
                delta = [v - w for v, w in zip(pos.features, neg.features, strict=True)]
                pairs.extend([delta, [-v for v in delta]])
                y.extend([1, 0])
    trained = LogisticRegression(C=1, fit_intercept=False, solver="liblinear", random_state=19).fit(pairs, y)
    weights = trained.coef_[0].tolist()
    valid, test = [list(repeated(rows)) for rows in partitions[1:]]
    margins = [0., .25, .5, .75, 1., 1.5, 2., 3., 4., 6.]
    metrics = [calibration(valid, weights, t) for t in margins]
    index = max(range(len(margins)), key=lambda i: (
        metrics[i]["new_correct"] - 2 * metrics[i]["lost_initially_correct"], metrics[i]["new_correct"], margins[i]))
    threshold = margins[index]
    write_new(OUT / "mention-weights.json", {"features": list(FEATURES), "coefficients": weights, "margin": threshold,
              "training_pairs": len(y) // 2, "source_sha256": {p.name: file_sha256(p) for p in paths},
              "implementation": file_sha256(ROOT / "app/modules/core/generation/korean_evidence_mentions.py"),
              "runner": file_sha256(Path(__file__)), "calibration": dict(zip(margins, metrics, strict=True)),
              "train_development": calibration(test, weights, threshold)})


def apply(rows: list[dict[str, Any]], qs, docs, params):
    by_id = {d["id"]: d for d in docs}
    questions = {q["id"]: q["question"] for q in qs}
    result = []
    for row in rows:
        if row["status"] == "answered":
            if row["source_id"] not in row["retrieved"]:
                raise ValueError("Reader cited an unretrieved source")
            row = select_mention(questions[row["id"]], by_id[row["source_id"]], row, params["coefficients"], params["margin"])
        result.append(row)
    return result


def development():
    ws = OUT / "mention-weights.json"
    params = load(ws)
    paths = [BASE / "panels" / ("dev." + name + ".json") for name in ("questions", "corpus", "labels")]
    for path in paths:
        if file_sha256(path) != load(BASE / "panels/reservation.json")["files"][path.name]:
            raise ValueError("Development panel changed")
    qs, docs, labels = map(load, paths)
    original_path = BASE / "qwen/rescue-dev.json"
    baseline = load(original_path)
    result = apply(baseline["rows"], qs, docs, params)
    metrics = grade(result, labels, docs)
    moved = sum(a != b for a, b in zip(result, baseline["rows"], strict=True))
    write_new(OUT / "development.json", {"weights_sha256": file_sha256(ws), "source_rows_sha256": file_sha256(original_path),
              "moved": moved, "rows": result, **metrics, "baseline": baseline["summary"]})
    print(json.dumps({g: metrics["summary"][g]["correct"] for g in ("answerable", "unanswerable")}), "moves", moved)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("fit", "development"))
    if parser.parse_args().stage == "fit":
        fit()
    else:
        development()
