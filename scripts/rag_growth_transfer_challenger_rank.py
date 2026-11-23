"""Retrieve actual candidates without handing scores, labels or annotated sources to the searcher."""

import argparse
import json
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_growth_transfer as tr
from scripts.rag_growth_transfer_reserve import reserve


def load_challenger(dataset: Path, panel: Path):
    docs, cases, info = reserve(dataset, panel.parent.parent)
    if tr.load(panel) != info or tr.json_sha256([docs, cases]) != info["manifest_sha256"]:
        raise ValueError("Reserved challenger or SQuAD context changed")
    return docs, cases


def rank(args):
    import torch

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    torch.set_num_threads(2)
    docs, cases = load_challenger(args.dataset, args.panel)
    files = {p.name: tr.file_sha256(p) for p in args.embedding.iterdir() if p.is_file() and p.name != "README.md"}
    if files != tr.load(args.panel.parent.parent / "preregistration.json")["model_files"]["embedding"]:
        raise ValueError("Unexpected E5 weights or tokenizer")
    retrieval = tr.LocalSpanRetriever(docs, args.embedding, args.device)
    output = args.panel.parent / "rankings.jsonl"
    with output.open("x") as stream:
        for case in cases:
            _, order, _ = retrieval.rankings(case["question"])
            stream.write(json.dumps({"id": case["id"], "hybrid": order[:6]}) + "\n")
    tr.dump(args.panel.parent / "ranking-provenance.json", {
        "panel_sha256": tr.file_sha256(args.panel), "rankings_sha256": tr.file_sha256(output),
        "embedding_revision": tr.E5_REV, "files": files, "device": args.device, "questions": len(cases),
        "script_sha256": tr.file_sha256(Path(__file__)),
        "retriever_sha256": tr.file_sha256(tr.ROOT / "app/modules/core/retrieval/retrievers/local_span_retriever.py"),
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "panel", "embedding"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "mps"), required=True)
    rank(parser.parse_args())
