"""Measure two local readers sequentially and select document support on two development domains."""

import argparse
import gc
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation.english_consensus_reader import select_answer
from app.modules.core.generation.english_evidence_selection import MODES, select_evidence
from scripts import rag_growth_transfer as tr
from scripts.rag_growth_transfer_diagnostics import wilson
from scripts.rag_growth_transfer_rerank import files, get_spans

MULTI_REV = "99531379f265b8404c91e64f9450814ceae7fdc7"
MULTI_SHA = "ec5fe733ca58b877eee8422a3a9a78bdccfa66eb39450400d5dd1ae03ab633d1"
THRESHOLDS = (-2, 0, 2)


def load_panel(name, args, panels):
    if name == "squad":
        if tr.file_sha256(args.squad) != tr.DATA_SHA:
            raise ValueError("Unexpected SQuAD source")
        docs, cases = tr.panels(tr.load(args.squad)["data"])["development"]
        if tr.json_sha256([docs, cases]) != tr.load(args.output.parent / "preregistration.json")["panels"]["development"]["manifest_sha256"]:
            raise ValueError("Previously registered SQuAD population changed")
        return docs, cases
    path = args.tydi / (name + ".json")
    if tr.file_sha256(path) != panels[name]["manifest_sha256"]:
        raise ValueError("Reserved TyDi inputs changed")
    data = tr.load(path)
    return data["documents"], data["cases"]


def predict(q, row, mode, threshold):
    needed = ("original",) if mode in ("baseline", "source_support") else (("multidomain",) if mode == "multidomain" else ("original", "multidomain"))
    if "retrieval_error" in row or any(not isinstance(row.get(key), list) for key in needed):
        return {"status": "error"}
    spans = {k: [tr.SpanAnswer(**s) for s in row[k]] for k in needed}
    if mode == "baseline":
        hit = select_answer(q, spans["original"], [], "deberta", -2)
    else:
        hit = select_evidence(q, spans.get("original", []), spans.get("multidomain", []), row["scores"], mode, threshold)
    return {"status": "abstained"} if hit is None else {"status": "answered", **asdict(hit)}


def grade(docs, cases, rows, mode, threshold):
    groups, errors = {"positive": [], "negative": []}, 0
    for c in cases:
        p = predict(c["question"], rows[c["id"]], mode, threshold)
        errors += p["status"] == "error"
        groups["negative" if c["impossible"] else "positive"].append(tr.grade(c,p,docs))
    return {"errors": errors, "metrics": {g: {"passed": sum(v), "n": len(v), "rate": sum(v) / len(v),
                                   "wilson95": wilson(sum(v),len(v))} for g,v in groups.items()}}


def eligible(baselines, scores):
    for name, base in baselines.items():
        b, c = base["metrics"], scores[name]["metrics"]
        changes = [c[k]["passed"] - b[k]["passed"] for k in b]
        if min(changes) < 0 or max(changes) <= 0 or scores[name]["errors"]:
            return False
    return True


def run(args):
    import torch

    os.environ.update(HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    torch.set_num_threads(2)
    root = args.output
    panels = tr.load(root / "panels.json")["panels"]
    paths = {"original": args.reader, "multidomain": args.multi, "embedding": args.embedding}
    inputs = {k: files(p) for k,p in paths.items()}
    original = tr.load(root.parent / "two-reader/preregistration.json")["weights"]
    if (inputs["original"] != original["deberta"] or inputs["embedding"] != original["embedding"]
            or inputs["multidomain"]["model.safetensors"] != MULTI_SHA or tr.file_sha256(args.squad) != tr.DATA_SHA):
        raise ValueError("Unexpected reader, tokenizer or public input")
    registered = {"panel_registration_sha256": tr.file_sha256(root / "panels.json"), "multidomain_revision": MULTI_REV,
                  "model_files": inputs, "modes": list(MODES), "thresholds": list(THRESHOLDS), "device": args.device,
                  "sources": {str(p.relative_to(tr.ROOT)): tr.file_sha256(p) for p in (
                      Path(__file__).resolve(), tr.ROOT / "scripts/rag_growth_transfer_rerank.py",
                      tr.ROOT / "app/modules/core/generation/english_evidence_selection.py",
                      tr.ROOT / "app/modules/core/generation/english_consensus_reader.py",
                      tr.ROOT / "app/modules/core/generation/english_span_reader.py",
                      tr.ROOT / "app/modules/core/generation/korean_span_reader.py",
                      tr.ROOT / "app/modules/core/retrieval/retrievers/local_span_retriever.py")},
                  "selection": "Require zero candidate errors, no lower correct count in any of four development strata, "
                               "and at least one gained correct response in each domain. Among qualifying profiles "
                               "favor the highest minimum of the four rates, then sum, then simplest mode, then threshold nearest zero. "
                               "A single confirmation can open for a qualifying candidate only."}
    receipt = root / "preregistration.json"
    if args.phase == "prepare":
        tr.dump(receipt, registered)
        return
    if tr.load(receipt) != registered:
        raise ValueError("Registered files or code changed")
    if args.phase == "confirmation":
        chosen = tr.load(root / "development-report.json")
        if not chosen["adopt"] or chosen["protocol_sha256"] != tr.file_sha256(receipt):
            raise ValueError("No qualifying development improvement; confirmation stays sealed")
        names = ["confirmation"]
    else:
        names = ["squad", "development"]
    if any((root / (n + "-predictions.jsonl")).exists() for n in names):
        raise ValueError("An evaluation has already been opened")
    work = {n: load_panel(n,args,panels) for n in names}
    rows = {}
    def release():
        gc.collect()
        if args.device == "mps":
            torch.mps.empty_cache()
    for name, (docs,cases) in work.items():
        index = tr.LocalSpanRetriever(docs, args.embedding, args.device)
        batch = {}
        for case in cases:
            qid = case["id"]
            try:
                _, order, support = index.rankings(case["question"])
                ids = order[:6]
                batch[qid] = {"id": qid, "candidates": ids, "scores": [support[d] for d in ids]}
            except Exception as e:
                batch[qid] = {"id": qid, "retrieval_error": type(e).__name__, "candidates": [], "scores": []}
        rows[name] = batch
        del index
        release()
        print(name, "retrieved", len(batch), flush=True)
    used = ["original", "multidomain"] if args.phase != "confirmation" or chosen["mode"] != "source_support" else ["original"]
    for k in used:
        reader = tr.EnglishSpanReader(paths[k], device=args.device)
        for n,(docs,cases) in work.items():
            for i,c in enumerate(cases):
                row = rows[n][c["id"]]
                if "retrieval_error" not in row:
                    row[k] = get_spans(c["question"], row["candidates"], docs, reader)
                if i % 16 == 15:
                    print(k, n, i + 1, "/", len(cases), flush=True)
        del reader
        release()
    for n, measurements in rows.items():
        with (root / (n + "-predictions.jsonl")).open("x") as fp:
            for r in measurements.values():
                fp.write(json.dumps(r,ensure_ascii=False) + "\n")
    base = {n: grade(*work[n],r,"baseline",-2) for n,r in rows.items()}
    if args.phase == "development":
        trials = []
        for m in MODES:
            for t in THRESHOLDS:
                scores = {n: grade(*work[n],r,m,t) for n,r in rows.items()}
                trials.append({"mode": m,"threshold": t,"scores": scores,"eligible": eligible(base,scores)})
        def objective(item):
            rates = [v["rate"] for g in item["scores"].values() for v in g["metrics"].values()]
            return item["eligible"], min(rates), sum(rates), -MODES.index(item["mode"]), -abs(item["threshold"])
        best = max(trials, key=objective)
        report = {"adopt": best["eligible"], "mode": best["mode"], "threshold": best["threshold"], "best": best["scores"], "tested_grid": trials}
    else:
        report = {"mode": chosen["mode"], "threshold": chosen["threshold"],
                  "candidate": grade(*work["confirmation"],rows["confirmation"],chosen["mode"],chosen["threshold"]),
                  "development_selection_sha256": tr.file_sha256(root / "development-report.json")}
    report.update(baseline=base, protocol_sha256=tr.file_sha256(receipt),
                  predictions_sha256={n: tr.file_sha256(root / (n + "-predictions.jsonl")) for n in names})
    tr.dump(root / (args.phase + "-report.json"), report)
    print(json.dumps({k:v for k,v in report.items() if k != "tested_grid"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase",choices=("prepare","development","confirmation"))
    for name in ("reader","multi","embedding","squad","tydi","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--device",choices=("cpu","mps"),default="mps")
    run(parser.parse_args())
