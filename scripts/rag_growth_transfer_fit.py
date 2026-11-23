"""Train a small logistic ranker and abstention model on official training articles using nested cross-fitting."""

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation import english_calibrated_spans as cal
from app.modules.core.generation.english_consensus_reader import select_answer
from scripts import rag_growth_transfer as tr
from scripts.rag_growth_transfer_cross_domain import eligible
from scripts.rag_growth_transfer_diagnostics import wilson
from scripts.rag_growth_transfer_train_features import panel, read_jsonl

THRESHOLDS = (0.35, 0.5, 0.65)
MODES = ("guarded", "learned")


@dataclass
class Sample:
    case: dict
    answers: list
    vectors: list
    exact: list
    incumbent: tr.SpanAnswer | None
    incumbent_ok: bool
    gold_retrieved: bool
    error: bool
    incumbent_error: bool


def verdict(span):
    return {"status": "abstained"} if span is None else {"status": "answered", **asdict(span)}


def samples(args, name):
    root = args.output
    phase = "development" if name in {"squad", "development"} else name
    receipt = tr.load(root / (phase + "-evidence.json"))
    if receipt["protocol_sha256"] != tr.file_sha256(root / "features-protocol.json") or any(
        tr.file_sha256(root / p) != sha for p, sha in receipt["files"].items()
    ):
        raise ValueError("Collected evidence changed")
    docs, cases = panel(args, name)
    sources = [
        read_jsonl(root / (name + "-" + k + ".jsonl")) for k in ("ranks", "incumbent", "proposals")
    ]
    if any(r.keys() != {c["id"] for c in cases} for r in sources):
        raise ValueError("Incomplete question coverage")
    out = []
    for c in cases:
        ranks, orig, props = (g[c["id"]] for g in sources)
        ids = ranks["docs"]
        old = []
        incumbent = None
        old_error = not isinstance(orig["original"], list)
        if not old_error:
            old = [tr.SpanAnswer(**s) for s in orig["original"]]
            incumbent = select_answer(c["question"], old, [], "deberta", -2)
        error = old_error or "error" in props
        ans, vec = [], []
        if not error:
            alternatives = [[tr.SpanAnswer(**s) for s in v] for v in props["proposals"]]
            ans, vec = cal.features(
                c["question"], [docs[d] for d in ids], ranks["rrf"], alternatives, old
            )
        flags = [tr.grade(c, verdict(a), docs) for a in ans]
        out.append(
            Sample(
                c,
                ans,
                vec,
                flags,
                incumbent,
                not old_error and tr.grade(c, verdict(incumbent), docs),
                c["source"] in ids,
                error,
                old_error,
            )
        )
    return out


def model(x, y, weights):
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    x, y, w = np.asarray(x, dtype=float), np.asarray(y, dtype=int), np.asarray(weights, dtype=float)
    if set(y) != {0, 1}:
        raise ValueError("A model fit requires positive and negative official train examples")
    total = w.sum()
    for label in (0, 1):
        w[y == label] *= total * 0.5 / w[y == label].sum()
    mean = np.average(x, axis=0, weights=w)
    scale = np.sqrt(np.average((x - mean) ** 2, axis=0, weights=w))
    scale[scale < 1e-6] = 1
    lr = LogisticRegression(C=1.0, solver="liblinear", max_iter=400, random_state=712)
    lr.fit((x - mean) / scale, y, sample_weight=w)
    return {
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "weights": lr.coef_[0].tolist(),
        "intercept": float(lr.intercept_[0]),
    }


def ranker(data):
    x, y, w = [], [], []
    for row in data:
        if row.error:
            continue
        count = Counter(row.exact)
        for vector, target in zip(row.vectors, row.exact, strict=True):
            x.append(vector)
            y.append(target)
            w.append(1 / (len(count) * count[target]))
    return model(x, y, w)


def view(row, rank):
    return cal.question_evidence(row.answers, row.vectors, rank, row.incumbent)


def fit_bundle(data, folds):
    """Train on data only. The judge sees first-stage scores from held-out articles."""
    x, y = [], []
    for held in sorted(set(folds)):
        train = [v for v, g in zip(data, folds, strict=True) if g != held]
        second = [v for v, g in zip(data, folds, strict=True) if g == held and not v.error]
        rank = ranker(train)
        for row in second:
            _, vector = view(row, rank)
            x.append(vector)
            y.append(not row.case["impossible"])
    return {"ranker": ranker(data), "judge": model(x, y, [1] * len(x))}


def fold_ids(rows):
    groups = {}
    for impossible in (False, True):
        part = sorted(
            (r.case["id"] for r in rows if r.case["impossible"] == impossible),
            key=lambda q: tr.key("onerag-official-train-crossfit/" + q),
        )
        groups.update({qid: i % 4 for i, qid in enumerate(part)})
    return [groups[r.case["id"]] for r in rows]


def answer_probability(row, bundle):
    if row.error:
        return None, 0.0
    answer, vector = view(row, bundle["ranker"])
    return answer, cal.probability(bundle["judge"], vector)


def metrics(rows, decisions, mode, threshold):
    correct = {"positive": [], "negative": []}
    ceiling = 0
    for row, (answer, p) in zip(rows, decisions, strict=True):
        if mode == "baseline":
            ok = row.incumbent_ok
        elif row.error:
            ok = False
        else:
            result = cal.decide(answer, p, row.incumbent, mode, threshold)
            if result == row.incumbent:
                ok = row.incumbent_ok
            elif result is None:
                ok = row.case["impossible"]
            else:
                ok = row.exact[row.answers.index(result)]
        correct["negative" if row.case["impossible"] else "positive"].append(ok)
        if not row.case["impossible"]:
            ceiling += bool(any(row.exact) or row.incumbent_ok)
    return {
        "errors": sum(r.incumbent_error if mode == "baseline" else r.error for r in rows),
        "retrieved_gold": sum(r.gold_retrieved for r in rows if not r.case["impossible"]),
        "candidate_set_ceiling": ceiling,
        "metrics": {
            k: {
                "passed": sum(v),
                "n": len(v),
                "rate": sum(v) / len(v),
                "wilson95": wilson(sum(v), len(v)),
            }
            for k, v in correct.items()
        },
    }


def run(args):
    root = args.output
    protocol = {
        "train_sha256": tr.file_sha256(root / "train.json"),
        "features_sha256": tr.file_sha256(root / "features-protocol.json"),
        "source_sha256": tr.file_sha256(Path(__file__)),
        "selector_sha256": tr.file_sha256(Path(cal.__file__)),
        "rank_features": list(cal.NAMES),
        "modes": list(MODES),
        "thresholds": list(THRESHOLDS),
        "folds": 4,
        "packages": {
            name: version(name) for name in ("numpy", "scikit-learn", "transformers", "torch")
        },
        "algorithm": "Two L2 logistic regressions C=1.0; balanced class weights, equal question totals for candidate labels. "
        "Train source/answer/span-exact ranker; train answerability on article-out-of-fold ranker features. "
        "Nested, stratified four-fold article evaluation on official train only selects one decision policy, by "
        "maximum minimum stratum, then sum, simpler guarded, then probability threshold closest to .5. "
        "Four development strata must not drop and both domains must improve with no candidate errors.",
    }
    receipt = root / "training-protocol.json"
    if args.phase == "prepare":
        tr.dump(receipt, protocol)
        return
    if tr.load(receipt) != protocol:
        raise ValueError("Frozen training code or source changed")
    if args.phase == "fit":
        data = samples(args, "train")
        folds = fold_ids(data)
        oof = {}
        for held in range(4):
            kept = [r for r, g in zip(data, folds, strict=True) if g != held]
            bundle = fit_bundle(kept, [g for g in folds if g != held])
            for r, g in zip(data, folds, strict=True):
                if g == held:
                    oof[r.case["id"]] = answer_probability(r, bundle)
        ordered = [oof[r.case["id"]] for r in data]
        trials = [
            {"mode": m, "threshold": t, "out_of_fold": metrics(data, ordered, m, t)}
            for m in MODES
            for t in THRESHOLDS
        ]

        def objective(c):
            rates = [x["rate"] for x in c["out_of_fold"]["metrics"].values()]
            return min(rates), sum(rates), -MODES.index(c["mode"]), -abs(0.5 - c["threshold"])

        chosen = max(trials, key=objective)
        fitted = fit_bundle(data, folds)
        fitted.update(
            chosen,
            protocol_sha256=tr.file_sha256(receipt),
            train_evidence_sha256=tr.file_sha256(root / "train-evidence.json"),
            trials=trials,
            fold_by_train_id={r.case["id"]: f for r, f in zip(data, folds, strict=True)},
            training_baseline=metrics(data, ordered, "baseline", 0.5),
        )
        tr.dump(root / "calibrator.json", fitted)
        print(chosen)
        return
    fitted = tr.load(root / "calibrator.json")
    if fitted["protocol_sha256"] != tr.file_sha256(receipt) or fitted[
        "train_evidence_sha256"
    ] != tr.file_sha256(root / "train-evidence.json"):
        raise ValueError("Training fit differs from registered evidence")
    if args.phase == "confirmation" and not tr.load(root / "development-report.json")["adopt"]:
        raise ValueError("No qualifying development evidence")
    base, new = {}, {}
    for n in ["squad", "development"] if args.phase == "development" else ["confirmation"]:
        rows = samples(args, n)
        decisions = [answer_probability(r, fitted) for r in rows]
        base[n] = metrics(rows, decisions, "baseline", 0.5)
        new[n] = metrics(rows, decisions, fitted["mode"], fitted["threshold"])
        with (root / (n + "-verdicts.jsonl")).open("x") as f:
            for r, (a, p) in zip(rows, decisions, strict=True):
                actual = (
                    {"status": "error"}
                    if r.error
                    else verdict(cal.decide(a, p, r.incumbent, fitted["mode"], fitted["threshold"]))
                )
                f.write(
                    json.dumps(
                        {"id": r.case["id"], "answerability_probability": p, "prediction": actual},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    result = {
        "baseline": base,
        "candidate": new,
        "adopt": eligible(base, new) if args.phase == "development" else None,
        "calibrator_sha256": tr.file_sha256(root / "calibrator.json"),
        "protocol_sha256": tr.file_sha256(receipt),
        "evidence_sha256": tr.file_sha256(root / (args.phase + "-evidence.json")),
    }
    tr.dump(root / (args.phase + "-report.json"), result)
    print(result)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=("prepare", "fit", "development", "confirmation"))
    for key in ("output", "train", "squad", "tydi"):
        p.add_argument("--" + key, required=True, type=Path)
    run(p.parse_args())
