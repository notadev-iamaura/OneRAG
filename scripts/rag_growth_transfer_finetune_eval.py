"""Calibrate on the two official training sources and measure the frozen locally fine-tuned QA model."""

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
from app.modules.core.generation.english_span_proposals import EnglishSpanProposer
from scripts import rag_growth_transfer as tr
from scripts.rag_growth_transfer_cross_domain import eligible
from scripts.rag_growth_transfer_diagnostics import wilson
from scripts.rag_growth_transfer_rerank import files, get_spans
from scripts.rag_growth_transfer_train_features import read_jsonl, save

LIMITS = (-4, -2, 0, 2, 4, 6)


def chosen(q, spans, t=-1e6):
    return select_answer(q, [tr.SpanAnswer(**v) for v in spans], [], "deberta", t)


def output(c, r, t, mode="tuned"):
    if not isinstance(r.get("original"), list):
        return {"status": "error"}
    old = chosen(c["question"], r["original"], -2)
    if mode == "baseline":
        selected = old
    else:
        if "tuned" not in r or not isinstance(r.get(mode), list):
            return {"status": "error"}
        proposed = chosen(c["question"], [group[0] for group in r[mode]])
        if proposed is None:
            return {"status": "error"}
        selected = old if abs(proposed.score - t) <= 2 else proposed if proposed.score > t else None
    return (
        {"status": "abstained"} if selected is None else {"status": "answered", **asdict(selected)}
    )


def grade(cases, docs, rows, t, mode):
    groups = {"positive": [], "negative": []}
    errors = 0
    for c in cases:
        pred = output(c, rows[c["id"]], t, mode)
        errors += pred["status"] == "error"
        groups["negative" if c["impossible"] else "positive"].append(tr.grade(c, pred, docs))
    return {
        "errors": errors,
        "metrics": {
            s: {
                "passed": sum(v),
                "n": len(v),
                "rate": sum(v) / len(v),
                "wilson95": wilson(sum(v), len(v)),
            }
            for s, v in groups.items()
        },
    }


def training_inputs(args):
    data = tr.load(args.output / "data.json")["splits"]
    docs, groups, ranks = {}, {}, {}
    for phase in ("calibration", "validation"):
        path = args.temp / (phase + ".json")
        if tr.file_sha256(path) != data[phase]["sha256"]:
            raise ValueError("Official-train calibration fold changed")
        for c in tr.load(path):
            doc = tr.key(c["content"])
            docs[doc] = {"id": doc, "title": c["title"], "content": c["content"]}
            groups.setdefault(phase + "-" + c["source"], []).append({**c, "source": doc})
            ranks[c["id"]] = [doc]
    return docs, groups, ranks


def run(args):
    import torch
    from safetensors.torch import load_file

    os.environ.update(HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    torch.set_num_threads(2)
    d = args.output
    root = d.parent
    prev = tr.load(root / "cross-domain/preregistration.json")
    if any(
        files(path) != prev["model_files"][name]
        for name, path in (
            ("original", args.legacy),
            ("multidomain", args.base),
            ("embedding", args.embedding),
        )
    ):
        raise ValueError("Unexpected local checkpoint")
    cfg = {
        "training_plan_sha256": tr.file_sha256(d / "preregistration.json"),
        "code_sha256": tr.file_sha256(Path(__file__)),
        "feature_collector_sha256": tr.file_sha256(root / "supervised/features-protocol.json"),
        "frozen_paired_policy": "If tuned margin within 2 of calibrated threshold, use original, otherwise take tuned answer over threshold or abstain.",
        "thresholds": list(LIMITS),
        "device": args.device,
    }
    registration = d / "evaluation-protocol.json"
    if args.phase == "prepare":
        tr.dump(registration, cfg)
        return
    if tr.load(registration) != cfg:
        raise ValueError("Evaluation contract changed")
    fitted = tr.load(d / "training-result.json")
    adapter = args.temp / "trained-adapter.safetensors"
    if (
        not fitted["complete"]
        or fitted["adapter_sha256"] != tr.file_sha256(adapter)
        or fitted["protocol_sha256"] != cfg["training_plan_sha256"]
    ):
        raise ValueError("No complete, unchanged fine-tune is available")
    if args.phase != "calibrate":
        lock = tr.load(d / "frozen-calibration.json")
        if lock["adapter_sha256"] != fitted["adapter_sha256"] or lock[
            "protocol_sha256"
        ] != tr.file_sha256(registration):
            raise ValueError("The trained policy was not frozen")
    if args.phase == "confirmation" and not tr.load(d / "development-report.json")["adopt"]:
        raise ValueError("No eligible fine-tuned policy; confirmation remains sealed")
    datasets = {}
    if args.phase == "calibrate":
        docs, subsets, ranks = training_inputs(args)
        for key, cases in subsets.items():
            datasets[key] = (docs, cases, {c["id"]: ranks[c["id"]] for c in cases})
    else:
        names = ("squad", "development") if args.phase == "development" else ("confirmation",)
        for n in names:
            if n == "squad":
                if tr.file_sha256(args.squad) != tr.DATA_SHA:
                    raise ValueError("SQuAD corpus changed")
                docs, cases = tr.panels(tr.load(args.squad)["data"])["development"]
            else:
                path = args.tydi / (n + ".json")
                if (
                    tr.file_sha256(path)
                    != tr.load(root / "cross-domain/panels.json")["panels"][n]["manifest_sha256"]
                ):
                    raise ValueError("Reserved TyDi material changed")
                s = tr.load(path)
                docs, cases = s["documents"], s["cases"]
            if n == "confirmation":
                retrieval = tr.LocalSpanRetriever(docs, args.embedding, args.device)
                ranks = {c["id"]: retrieval.rankings(c["question"])[1][:12] for c in cases}
                del retrieval
                gc.collect()
                if args.device == "mps":
                    torch.mps.empty_cache()
            else:
                path = root / "supervised" / (n + "-ranks.jsonl")
                if (
                    tr.file_sha256(path)
                    != tr.load(root / "supervised/development-evidence.json")["files"][path.name]
                ):
                    raise ValueError("Previously collected top-12 changed")
                ranks = {k: r["docs"] for k, r in read_jsonl(path).items()}
            datasets[n] = (docs, cases, ranks)
    if (d / (args.phase + "-predictions.jsonl")).exists():
        raise ValueError("This phase has already been opened")
    allrows = {}
    legacy = (
        tr.EnglishSpanReader(args.legacy, device=args.device)
        if args.phase != "development"
        else None
    )
    for n, (docs, cases, ranks) in datasets.items():
        if legacy is None:
            path = root / "supervised" / (n + "-incumbent.jsonl")
            if (
                tr.file_sha256(path)
                != tr.load(root / "supervised/development-evidence.json")["files"][path.name]
            ):
                raise ValueError("Real incumbent predictions changed")
            cached = read_jsonl(path)
        for c in cases:
            qid = c["id"]
            ids = ranks[qid]
            prior = (
                cached[qid]["original"]
                if legacy is None
                else get_spans(c["question"], ids[:6], docs, legacy)
            )
            allrows[qid] = {"id": qid, "group": n, "candidates": ids, "original": prior}
    del legacy
    gc.collect()
    if args.device == "mps":
        torch.mps.empty_cache()
    reader = EnglishSpanProposer(args.base, device=args.device)
    for mode in ("pretrained", "tuned") if args.phase == "calibrate" else ("tuned",):
        if mode == "tuned":
            delta = load_file(str(adapter), device="cpu")
            if set(delta) != set(fitted["selected_layer_names"]):
                raise ValueError("Unexpected trainable parameters in adapter")
            updated = reader.model.load_state_dict(delta, strict=False)
            if updated.unexpected_keys:
                raise ValueError("Unknown tuned model parameter")
            del delta
        for n, (docs, cases, ranks) in datasets.items():
            if mode == "pretrained" and not n.startswith("validation-"):
                continue
            for i, c in enumerate(cases):
                qid = c["id"]
                try:
                    options = reader.propose(c["question"], [docs[key] for key in ranks[qid]])
                    allrows[qid][mode] = [[asdict(s) for s in group] for group in options]
                except Exception as error:
                    allrows[qid][mode] = {"error": type(error).__name__ + ": " + str(error)[:160]}
                if i % 16 == 15:
                    print(args.phase, mode, n, i + 1, flush=True)
    del reader
    gc.collect()
    if args.device == "mps":
        torch.mps.empty_cache()
    path = d / (args.phase + "-predictions.jsonl")
    save(path, allrows)
    if args.phase == "calibrate":

        def scores(prefix, threshold, mode):
            return {
                n: grade(c, docs, allrows, threshold, mode)
                for n, (docs, c, _) in datasets.items()
                if n.startswith(prefix + "-")
            }

        grid = [(t, scores("calibration", t, "tuned")) for t in LIMITS]

        def goal(item):
            t, measures = item
            r = [m["rate"] for g in measures.values() for m in g["metrics"].values()]
            return min(r), sum(r), -abs(t)

        t, chosen_rates = max(grid, key=goal)
        report = {
            "threshold": t,
            "calibration": chosen_rates,
            "grid": grid,
            "train_validation": {
                mode: scores("validation", t, mode) for mode in ("baseline", "pretrained", "tuned")
            },
        }
        dest = d / "frozen-calibration.json"
    else:
        t = lock["threshold"]
        b = {n: grade(c, docs, allrows, t, "baseline") for n, (docs, c, _) in datasets.items()}
        s = {n: grade(c, docs, allrows, t, "tuned") for n, (docs, c, _) in datasets.items()}
        report = {
            "threshold": t,
            "candidate": s,
            "baseline": b,
            "adopt": eligible(b, s) if args.phase == "development" else None,
        }
        with (d / (args.phase + "-verdicts.jsonl")).open("x") as f:
            for n, (_, cases, _) in datasets.items():
                for c in cases:
                    qid = c["id"]
                    f.write(
                        json.dumps(
                            {"id": qid, "panel": n, "prediction": output(c, allrows[qid], t)},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
        dest = d / (args.phase + "-report.json")
    report.update(
        protocol_sha256=tr.file_sha256(registration),
        adapter_sha256=fitted["adapter_sha256"],
        predictions_sha256=tr.file_sha256(path),
    )
    tr.dump(dest, report)
    print(args.phase, t, report.get("adopt"), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=("prepare", "calibrate", "development", "confirmation"))
    for k in ("base", "legacy", "embedding", "temp", "squad", "tydi", "output"):
        p.add_argument("--" + k, type=Path, required=True)
    p.add_argument("--device", choices=("cpu", "mps"), default="mps")
    run(p.parse_args())
