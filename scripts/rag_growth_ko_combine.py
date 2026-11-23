"""Cross-fit auditable fallback rules on complete, source-aligned Korean development predictions."""

import argparse
import hashlib
import itertools
import json
import math
import sys
from collections import Counter
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.rag_growth_ko_eval import SPAN_FIELDS, checked_span, grade, write_new
from scripts.rag_growth_local import file_sha256

QWEN_WEIGHTS = "96b9c0af5c77a4ecaabe3983175112b5ece763261c1ece12b2494b692a70dad7"
SEED = "onerag-ko-combine-oof-v1"
FALLBACK = {"off": None, "first_s0": (1, 0), "first_s3": (1, 3), "best_two_s3": (2, 3)}
GRID = [{"narrow": n, "veto": v, "fallback": f}
        for n, v, f in itertools.product((False, True), (False, True), FALLBACK)]


def inputs(args):
    reservation = json.loads((args.panels / "reservation.json").read_bytes())
    files = {k: reservation["files"][f"dev.{k}.json"] for k in ("corpus", "questions", "labels")}
    for k, sha in files.items():
        if file_sha256(args.panels / f"dev.{k}.json") != sha:
            raise ValueError("Modified development panel")
    return {"development_sha256": files, "extractor_sha256": file_sha256(args.encoder),
            "sufficiency_sha256": file_sha256(args.sufficiency), "program_sha256": file_sha256(Path(__file__)),
            "qwen_weights_sha256": QWEN_WEIGHTS, "fold_seed": SEED, "n_folds": 2, "grid": GRID,
            "selection": "maximize minimum grounded/abstention rate, then macro average, fewer actions, "
                         "earlier grid order", "fallback_margin_strictly_above": 4,
            "veto": "only an answered Qwen span with no intersecting rank-one encoder span and sufficiency <= 0",
            "narrow": "use a proper subspan at the same actual offsets in the same article"}


def registered(args):
    info = inputs(args)
    lines = args.qwen.read_bytes().splitlines(keepends=True)
    n = len(lines) if not lines or lines[-1].endswith(b"\n") else len(lines)-1
    write_new(args.output / "registration.json",
              {**info, "qwen_prefix_rows": n, "qwen_prefix_sha256": hashlib.sha256(b"".join(lines[:n])).hexdigest()})


def load(args):
    registration = json.loads((args.output/"registration.json").read_bytes())
    if any(registration[k] != v for k, v in inputs(args).items()):
        raise ValueError("Registered inputs, policy or code changed")
    raw = args.qwen.read_bytes().splitlines(keepends=True)
    if hashlib.sha256(b"".join(raw[:registration["qwen_prefix_rows"]])).hexdigest() != registration["qwen_prefix_sha256"]:
        raise ValueError("The measured Qwen prefix changed after registration")
    qs, doclist, labels = (json.loads((args.panels/f"dev.{k}.json").read_bytes())
                          for k in ("questions", "corpus", "labels"))
    ids = [q["id"] for q in qs]
    docs = {d["id"]: d["content"] for d in doclist}
    qwen, encoder, verifier = ([json.loads(line) for line in lines] for lines in
                              (raw, args.encoder.read_bytes().splitlines(), args.sufficiency.read_bytes().splitlines()))
    if (len(ids) != 80 or len(set(ids)) != 80 or [g["id"] for g in labels] != ids
            or any([r["id"] for r in rows] != ids for rows in (qwen, encoder, verifier))
            or Counter(g["answerable"] for g in labels) != {True: 40, False: 40}):
        raise ValueError("Need complete, ordered 40+40 development only")
    records = []
    for a, b, c in zip(qwen, encoder, verifier, strict=True):
        ranked = b["retrieved"]
        if (len(ranked) != 3 or len(set(ranked)) != 3 or a["retrieved"] != ranked[:1] or c["ids"] != ranked[:2]
                or a["weights"] != QWEN_WEIGHTS or len(c["scores"]) != 2 or not all(math.isfinite(s) for s in c["scores"])
                or [s["source_id"] for s in b["spans"]] != ranked):
            raise ValueError("Model outputs or retrieved sources do not align")
        if a["status"] not in ("answered", "error", "abstained"):
            raise ValueError("Unrecognized reader state")
        if a["status"] == "answered" and not checked_span(a, docs):
            raise ValueError("Unverified Qwen offsets")
        if a["status"] != "answered" and any(a.get(k) for k in SPAN_FIELDS):
            raise ValueError("Unanswered Qwen record contains a citation")
        for i, s in enumerate(b["spans"]):
            if (s["document_index"] != i or not math.isfinite(s["score"])
                    or not checked_span({**s, "retrieved": ranked}, docs)):
                raise ValueError("Unverified extractive span")
        records.append((a, b["spans"], c["scores"]))
    return records, doclist, labels


def apply(record, rule):
    qwen, spans, scores = record
    first = spans[0]
    if qwen["status"] == "error":
        return dict(qwen), "error_preserved"
    if qwen["status"] == "answered":
        inside = qwen["start"] <= first["start"] < first["end"] <= qwen["end"]
        if rule["narrow"] and inside and len(first["answer"]) < len(qwen["answer"]):
            return {**qwen, **{k: first[k] for k in SPAN_FIELDS}}, "narrowed"
        overlap = first["start"] < qwen["end"] and qwen["start"] < first["end"]
        if rule["veto"] and not overlap and scores[0] <= 0:
            return {"id": qwen["id"], "retrieved": qwen["retrieved"], "status": "abstained"}, "vetoed"
    elif (rescue := FALLBACK[rule["fallback"]]) is not None:
        depth, threshold = rescue
        considered = [s["source_id"] for s in spans[:depth]]
        i = max(range(depth), key=lambda idx: scores[idx])
        if scores[i] > threshold and spans[i]["score"] > 4:
            return {"id": qwen["id"], "retrieved": considered, "status": "answered",
                    **{k: spans[i][k] for k in SPAN_FIELDS}}, "rescued"
        return {**qwen, "retrieved": considered}, "unchanged"
    return dict(qwen), "unchanged"


def evaluate(records, gold, docs, rule):
    rows, actions = zip(*(apply(r, rule) for r in records), strict=True)
    result = grade(rows, gold, docs)
    return rows, list(actions), result


def fit(records, gold, docs):
    best_key, selected = None, None
    for rule in GRID:
        _, _, result = evaluate(records, gold, docs, rule)
        s = result["summary"]
        complexity = int(rule["narrow"]) + int(rule["veto"]) + int(rule["fallback"] != "off")
        key = (min(s["answerable"]["percent"], s["unanswerable"]["percent"]), s["balanced_percent"], -complexity)
        if best_key is None or key > best_key:
            best_key, selected = key, rule
    return selected


def report(rows, actions, gold, docs, baseline):
    graded = grade(rows, gold, docs)
    summary = graded["summary"]
    answered = sum(r["status"] == "answered" for r in rows)
    paired = {}
    for flag, name in ((True, "answerable"), (False, "unanswerable")):
        pairs = [(baseline[o["id"]], o["correct"]) for o in graded["outcomes"] if o["answerable"] == flag]
        paired[name] = {"n": len(pairs), "improved": sum(not a and b for a,b in pairs),
                        "regressed": sum(a and not b for a,b in pairs)}
    return {"summary": summary, "coverage": {"answered": answered, "total": len(rows), "rate": answered/len(rows)},
            "strict_precision": {"correct_grounded_answers": summary["answerable"]["correct"], "answered": answered,
                                 "rate": summary["answerable"]["correct"]/answered if answered else None},
            "paired_vs_qwen": paired, "actions": dict(Counter(actions))}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phase", choices=("prepare", "development"))
    for key in ("panels", "qwen", "encoder", "sufficiency", "output"):
        ap.add_argument("--"+key, required=True, type=Path)
    args = ap.parse_args()
    if args.phase == "prepare":
        registered(args)
        return
    records, docs, labels = load(args)
    assigned = {}
    for pos in (False, True):
        ordered = sorted((g["id"] for g in labels if g["answerable"] == pos),
                         key=lambda cid: hashlib.sha256((SEED + "/" + cid).encode()).hexdigest())
        assigned.update({cid: i%2 for i,cid in enumerate(ordered)})
    baseline_rows, actions, base = evaluate(records, labels, docs, GRID[0])
    original = {o["id"]: o["correct"] for o in base["outcomes"]}
    held, switches, selections = {}, {}, []
    for fold in (0,1):
        train = [i for i,g in enumerate(labels) if assigned[g["id"]] != fold]
        rule = fit([records[i] for i in train], [labels[i] for i in train], docs)
        test = [i for i,g in enumerate(labels) if assigned[g["id"]] == fold]
        pred, labels_actions, measured = evaluate([records[i] for i in test], [labels[i] for i in test], docs, rule)
        for i,row,action in zip(test,pred,labels_actions,strict=True):
            held[i], switches[i] = row,action
        selections.append({"test_fold": fold, "rule": rule, "training_n": len(train), "test": measured["summary"]})
    fitted = fit(records,labels,docs)
    fitted_rows, fitted_actions, _ = evaluate(records,labels,docs,fitted)
    ordered_held = [held[i] for i in range(len(records))]
    evaluated = {"scope": "previously exposed public KLUE development, no final panel loaded",
                 "qwen_rows_sha256": file_sha256(args.qwen), "registration_sha256": file_sha256(args.output/"registration.json"),
                 "qwen_baseline": report(baseline_rows, actions, labels, docs, original), "folds": selections,
                 "out_of_fold": report(ordered_held, list(switches.values()), labels, docs, original),
                 "whole_dev_selection": {"rule": fitted, "in_sample": report(fitted_rows, fitted_actions, labels, docs, original)},
                 "row_decisions": [{"id":g["id"], "fold":assigned[g["id"]], "out_of_fold_action":switches[i],
                                    "out_of_fold_status":held[i]["status"], "fit_action":fitted_actions[i]}
                                   for i,g in enumerate(labels)]}
    write_new(args.output/"development.json", evaluated)
    print(json.dumps({k: [evaluated[k]["summary"][group]["correct"] for group in ("answerable", "unanswerable")]
                      for k in ("qwen_baseline","out_of_fold")}))


if __name__ == "__main__":
    main()
