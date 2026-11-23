"""Collect genuine search top 12, five alternative local spans per passage, and the incumbent output."""

import argparse
import gc
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation.english_span_proposals import EnglishSpanProposer
from scripts import rag_growth_transfer as tr
from scripts.rag_growth_transfer_rerank import files, get_spans


def read_jsonl(path):
    return {r["id"]: r for r in map(json.loads, path.read_text().splitlines())}


def panel(args, name):
    if name == "train":
        path = args.train
        expected = tr.load(args.output / "train.json")["corpus_sha256"]
    elif name == "squad":
        if tr.file_sha256(args.squad) != tr.DATA_SHA:
            raise ValueError("SQuAD data changed")
        return tr.panels(tr.load(args.squad)["data"])["development"]
    else:
        path = args.tydi / (name + ".json")
        expected = tr.load(args.output.parent / "cross-domain/panels.json")["panels"][name][
            "manifest_sha256"
        ]
    if tr.file_sha256(path) != expected:
        raise ValueError("Registered corpus changed")
    data = tr.load(path)
    return data["documents"], data["cases"]


def save(path, rows):
    with path.open("x") as f:
        for r in rows.values():
            f.write(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n")


def collect(args):
    import torch

    os.environ.update(HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    torch.set_num_threads(2)
    d = args.output
    upstream = tr.load(d.parent / "cross-domain/preregistration.json")
    weights = {
        k: files(p)
        for k, p in (
            ("original", args.reader),
            ("multidomain", args.multi),
            ("embedding", args.embedding),
        )
    }
    if weights != upstream["model_files"]:
        raise ValueError("Unregistered weights or tokenizer")
    cfg = {
        "train_sha256": tr.file_sha256(d / "train.json"),
        "validation_sha256": tr.file_sha256(d.parent / "cross-domain/panels.json"),
        "model_files": weights,
        "device": args.device,
        "retrieval_depth": 12,
        "proposals_per_document": 5,
        "code": {
            str(p.relative_to(tr.ROOT)): tr.file_sha256(p)
            for p in (
                Path(__file__).resolve(),
                tr.ROOT / "app/modules/core/generation/english_span_proposals.py",
                tr.ROOT / "app/modules/core/generation/english_span_reader.py",
                tr.ROOT / "app/modules/core/generation/korean_span_reader.py",
                tr.ROOT / "app/modules/core/retrieval/retrievers/local_span_retriever.py",
            )
        },
    }
    registered = d / "features-protocol.json"
    if args.phase == "prepare":
        tr.dump(registered, cfg)
        return
    if tr.load(registered) != cfg:
        raise ValueError("Frozen candidate inference changed")
    if args.phase in ("development", "confirmation") and not (d / "calibrator.json").exists():
        raise ValueError("A training-only frozen model is required before development inference")
    if args.phase == "confirmation" and not tr.load(d / "development-report.json")["adopt"]:
        raise ValueError("No eligible model; confirmation stays closed")
    names = ["squad", "development"] if args.phase == "development" else [args.phase]
    allsets = {n: panel(args, n) for n in names}

    def release():
        gc.collect()
        if args.device == "mps":
            torch.mps.empty_cache()

    ranks = {}
    for n, (docs, cases) in allsets.items():
        idx = tr.LocalSpanRetriever(docs, args.embedding, args.device)
        ranks[n] = {}
        for c in cases:
            order = idx.rankings(c["question"])
            ids = order[1][:12]
            ranks[n][c["id"]] = {"id": c["id"], "docs": ids, "rrf": [order[2][key] for key in ids]}
        del idx
        release()
        save(d / (n + "-ranks.jsonl"), ranks[n])
        print(n, "retrieved", len(cases), flush=True)
    if args.phase == "development":
        receipt = tr.load(d.parent / "cross-domain/development-report.json")
        for n in names:
            path = d.parent / "cross-domain" / (n + "-predictions.jsonl")
            if tr.file_sha256(path) != receipt["predictions_sha256"][n]:
                raise ValueError("Independent incumbent predictions changed")
            historical = read_jsonl(path)
            if any(ranks[n][qid]["docs"][:6] != r["candidates"] for qid, r in historical.items()):
                raise ValueError("Old top-six candidates differ from this corpus")
            save(
                d / (n + "-incumbent.jsonl"),
                {qid: {"id": qid, "original": r["original"]} for qid, r in historical.items()},
            )
    else:
        old = tr.EnglishSpanReader(args.reader, device=args.device)
        for n, (docs, cases) in allsets.items():
            out = {}
            for i, c in enumerate(cases):
                qid = c["id"]
                out[qid] = {
                    "id": qid,
                    "original": get_spans(c["question"], ranks[n][qid]["docs"][:6], docs, old),
                }
                if i % 16 == 15:
                    print("incumbent", n, i + 1, flush=True)
            save(d / (n + "-incumbent.jsonl"), out)
        del old
        release()
    model = EnglishSpanProposer(args.multi, device=args.device)
    for n, (docs, cases) in allsets.items():
        with (d / (n + "-proposals.jsonl")).open("x") as f:
            for i, c in enumerate(cases):
                qid = c["id"]
                try:
                    opts = model.propose(c["question"], [docs[k] for k in ranks[n][qid]["docs"]])
                    row = {"id": qid, "proposals": [[asdict(s) for s in doc] for doc in opts]}
                except Exception as error:
                    row = {"id": qid, "error": type(error).__name__ + ": " + str(error)[:140]}
                f.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                f.flush()
                if i % 16 == 15:
                    print("new proposals", n, i + 1, flush=True)
    del model
    release()
    tr.dump(
        d / (args.phase + "-evidence.json"),
        {
            "protocol_sha256": tr.file_sha256(registered),
            "files": {
                p: tr.file_sha256(d / p)
                for n in names
                for p in (n + "-ranks.jsonl", n + "-incumbent.jsonl", n + "-proposals.jsonl")
            },
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=("prepare", "train", "development", "confirmation"))
    for key in ("reader", "multi", "embedding", "squad", "tydi", "train", "output"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--device", choices=("cpu", "mps"), default="mps")
    collect(p.parse_args())
