"""Fit only sentence ranking coefficients on pre-existing, article-disjoint official KLUE train groups."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.modules.core.generation.korean_evidence_selection import (
    FEATURES,
    KoreanEvidenceSelector,
    features,
    sentences,
)
from scripts.rag_growth_ko_eval import write_new
from scripts.rag_growth_local import ROOT, file_sha256
from scripts.rag_research_inputs import research_cache

DATA = research_cache() / "onerag-growth03-koreader/data"
OUT = ROOT / "output/rag-evidence-selection/klue"


def examples(path: Path) -> list[dict[str, Any]]:
    return [r for r in map(json.loads, path.read_bytes().splitlines()) if not r["is_impossible"]]


def references(row: dict[str, Any]) -> tuple[list[Any], set[int]]:
    units = sentences(row["context"])
    anchors = [(p, p + len(a)) for p, a in zip(row["answers"]["answer_start"], row["answers"]["text"], strict=True)
               if row["context"][p:p + len(a)] == a]
    return units, {i for i, line in enumerate(units) if any(line.start <= a < b <= line.end for a, b in anchors)}


def main() -> None:
    from sklearn.linear_model import LogisticRegression

    fit, validation = DATA / "fit.jsonl", DATA / "development.jsonl"
    train, check = examples(fit), examples(validation)
    if {r["context"] for r in train} & {r["context"] for r in check}:
        raise ValueError("Training and development articles overlap")
    hard = KoreanEvidenceSelector("lexical")
    x, y = [], []
    for row in train:
        units, good = references(row)
        if not good:
            continue
        f = features(row["question"], units)
        negatives = [i for i in hard.rank(row["question"], units) if i not in good]
        for pos in sorted(good):
            # The hard-only pilot underrepresented less similar article sentences on train development.
            for neg in [*negatives, *negatives[:2]]:
                delta = [a - b for a, b in zip(f[pos], f[neg], strict=True)]
                x.extend([delta, [-v for v in delta]])
                y.extend([1, 0])
    clf = LogisticRegression(C=1.0, fit_intercept=False, solver="liblinear", random_state=41).fit(x, y)
    params = OUT / "sentence-weights-balanced.json"
    write_new(params, {"features": list(FEATURES), "coefficients": clf.coef_[0].tolist(),
                       "fit_sha256": file_sha256(fit), "positive_articles": len(train), "pairwise_examples": len(x)})
    modes = {"lexical": hard, "trained": KoreanEvidenceSelector("trained", params)}
    metrics: dict[str, Any] = {}
    for mode, selector in modes.items():
        hits1, hits3, n = 0, 0, 0
        for item in check:
            units, good = references(item)
            ranking = selector.rank(item["question"], units)
            hits1 += bool(set(ranking[:1]) & good)
            hits3 += bool(set(ranking[:3]) & good)
            n += 1
        metrics[mode] = {"n_answerable": n, "gold_sentence_hit1": hits1, "gold_sentence_hit3": hits3}
    write_new(OUT / "train-development-balanced.json", {"partition": file_sha256(validation), "content_overlap": 0,
                                                "weights_sha256": file_sha256(params), "metrics": metrics})


if __name__ == "__main__":
    main()
