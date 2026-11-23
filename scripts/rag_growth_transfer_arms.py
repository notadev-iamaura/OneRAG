"""Measure frozen SQuAD policies independently with the exact product reader's document batches."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation.english_consensus_reader import select_answer
from scripts import rag_growth_transfer as tr
from scripts.rag_growth_transfer_diagnostics import wilson


def predict_arm(question, ids, docs, reader, threshold, *, mode="deberta", cached=None):
    """Share forward results only when the whole ordered batch and reader are identical."""
    key = (id(reader), tuple(ids))
    try:
        if cached is not None and key in cached:
            spans = cached[key]
        else:
            spans = reader.predict_spans(question, [docs[d] for d in ids])
            if [s.source_id for s in spans] != list(ids):
                raise ValueError("Reader did not return one span for every requested document")
            if cached is not None:
                cached[key] = spans
        if mode == "baseline":
            result = reader.choose(spans, 0.5)
            if result is not None and result.score <= threshold:
                result = None
        else:
            result = select_answer(question, spans, [], "deberta", threshold)
        if result is None:
            return {"status": "abstained"}
        return {"status": "answered", **asdict(result)}
    except Exception as error:
        return {"status": "error", "reason": type(error).__name__ + ": " + str(error)[:180]}


def protocol(root):
    selection = tr.load(root / "selected-for-final.json")
    if (selection["iteration"], selection["mode"], selection["threshold"]) != (2, "deberta", -2):
        raise ValueError("This exact-arm runner supports only the frozen single DeBERTa policy")
    before = tr.load(root / "two-reader/preregistration.json")
    if any(tr.file_sha256(tr.ROOT / name) != digest for name, digest in before["code"].items()):
        raise ValueError("Previously registered product or evaluator code changed")
    return {"development_selection_sha256": tr.file_sha256(root / "selected-for-final.json"),
            "upstream_registration_sha256": tr.file_sha256(root / "two-reader/preregistration.json"),
            "review_sha256": tr.file_sha256(root / "review/development-report.json"),
            "use_review": tr.load(root / "review/development-report.json")["adopt"],
            "threshold": selection["threshold"], "mode": selection["mode"], "code_sha256": tr.file_sha256(Path(__file__)),
            "arms": {"baseline": "BM25 top-1 DeBERTa unmodified span margin >0",
                     "lexical": "BM25 top-6 same selected DeBERTa policy",
                     "candidate": "BM25/E5 RRF top-6 selected DeBERTa",
                     "oracle": "separate original reference passage; diagnostic only"}}


def summarize(docs, cases, rows):
    if {case["id"] for case in cases} != rows.keys():
        raise ValueError("Incomplete measurement")
    result = {}
    for arm in ("baseline", "lexical", "candidate", "oracle", "oracle_forced"):
        counts = {}
        for label, impossible in (("positive", False), ("negative", True)):
            subset = [c for c in cases if c["impossible"] == impossible]
            pairs = [(tr.grade(c, rows[c["id"]]["baseline"], docs), tr.grade(c, rows[c["id"]][arm], docs)) for c in subset]
            n, passed = len(pairs), sum(y for _, y in pairs)
            counts[label] = {"passed": passed, "n": n, "rate": passed / n, "wilson95": wilson(passed, n),
                             "errors": sum(rows[c["id"]][arm]["status"] == "error" for c in subset),
                             "wins_vs_baseline": sum(b and not a for a,b in pairs),
                             "losses_vs_baseline": sum(a and not b for a,b in pairs)}
        result[arm] = counts
    return result


def measure(phase, corpus, root, reader, embed_dir, device, frozen, secondary):
    docs, cases = corpus
    dest = root / "independent-arms"
    if tr.json_sha256([docs, cases]) != tr.load(root / "preregistration.json")["panels"][phase]["manifest_sha256"]:
        raise ValueError("Registered corpus or questions changed")
    search = tr.LocalSpanRetriever(docs, embed_dir, device)
    path = dest / (phase + ".jsonl")
    rows = {}
    with path.open("x", encoding="utf-8") as stream:
        for i, case in enumerate(cases):
            started = time.monotonic()
            q, cache = case["question"], {}
            lexical = [r["id"] for r in search.bm25.search(q, 40)][:6]
            baseline = predict_arm(q, lexical[:1], docs, reader, 0, mode="baseline", cached=cache)
            lex = predict_arm(q, lexical, docs, reader, frozen["threshold"], cached=cache)
            hybrid = []
            try:
                _, hybrid_order, _ = search.rankings(q)
                hybrid = hybrid_order[:6]
                candidate = predict_arm(q, hybrid, docs, reader, frozen["threshold"], cached=cache)
            except Exception as error:
                candidate = {"status": "error", "reason": type(error).__name__ + ": " + str(error)[:180]}
            row = {"id": case["id"], "lexical_ids": lexical, "hybrid_ids": hybrid,
                   "baseline": baseline, "lexical": lex, "candidate": candidate}
            if secondary is not None and candidate["status"] != "error":
                try:
                    first = cache[id(reader), tuple(hybrid)]
                    second = secondary.predict_spans(q, [docs[d] for d in hybrid])
                    if [s.source_id for s in second] != hybrid:
                        raise ValueError("Second reader did not return every requested document")
                    row["review_spans"] = [[asdict(s) for s in seq] for seq in (first, second)]
                except Exception as error:
                    row["review_error"] = type(error).__name__ + ": " + str(error)[:180]
            # Keep supplied source information physically downstream of both ordinary retrieval policies.
            row["oracle"] = predict_arm(q, [case["source"]], docs, reader, frozen["threshold"], cached=cache)
            row["oracle_forced"] = predict_arm(q, [case["source"]], docs, reader, -1e6, cached=cache)
            row["elapsed_ms"] = round(1000 * (time.monotonic() - started))
            rows[case["id"]] = row
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            if i % 8 == 0:
                print(phase, i + 1, "/", len(cases), flush=True)
    report = {"split": phase, "arms": summarize(docs, cases, rows), "measured_sha256": tr.file_sha256(path),
              "protocol_sha256": tr.file_sha256(dest / "preregistration.json"),
              "retrieval_source_positive": {arm: sum(not c["impossible"] and c["source"] in rows[c["id"]][arm][:k] for c in cases)
                                            for arm,k in (("hybrid_ids", 6), ("lexical_ids", 6))}}
    tr.dump(dest / (phase + "-report.json"), report)
    print(phase, json.dumps(report["arms"]["candidate"]), flush=True)


def run(args):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    dest = args.output / "independent-arms"
    dest.mkdir(exist_ok=True)
    expected = protocol(args.output)
    registration = dest / "preregistration.json"
    if args.phase == ["prepare"]:
        if any(p.exists() for d in (dest, args.output / "two-reader", args.output)
               for s in ("final", "confirmation") for p in [d / (s + ".jsonl")]):
            raise ValueError("Selection must precede both independent panels")
        tr.dump(registration, expected)
        return
    if "prepare" in args.phase or len(set(args.phase)) != len(args.phase) or tr.load(registration) != expected:
        raise ValueError("Expected unchanged preregistration and unique phases")
    if args.dataset is None or args.reader is None or args.embedding is None:
        raise ValueError("--dataset --reader and --embedding are required for actual inference")
    if any((dest / (phase + ".jsonl")).exists() for phase in args.phase):
        raise ValueError("An input panel has already been opened")
    upstream = tr.load(args.output / "two-reader/preregistration.json")
    paths = {"deberta": args.reader, "embedding": args.embedding}
    if expected["use_review"]:
        if not args.second:
            raise ValueError("The adopted review requires --second")
        paths["roberta"] = args.second
    if any({p.name: tr.file_sha256(p) for p in directory.iterdir() if p.is_file() and p.name != "README.md"}
           != upstream["weights"][name] for name, directory in paths.items()):
        raise ValueError("Unregistered model or tokenizer")
    if tr.file_sha256(args.dataset) != tr.DATA_SHA or args.device != upstream["device"]:
        raise ValueError("Unregistered official dataset or inference device")
    import torch

    torch.set_num_threads(4)
    panels = tr.panels(tr.load(args.dataset)["data"])
    reader = tr.EnglishSpanReader(args.reader, device=args.device)
    second = tr.EnglishSpanReader(args.second, device=args.device) if expected["use_review"] else None
    for phase in args.phase:
        measure(phase, panels[phase], args.output, reader, args.embedding, args.device, expected, second)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", *tr.SIZES), nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    for name in ("reader", "dataset", "embedding", "second"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    run(parser.parse_args())
