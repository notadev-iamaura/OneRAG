"""Evaluate a second reader on the registered English transfer questions and freeze a development policy."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation.english_consensus_reader import select_answer
from scripts import rag_growth_transfer as tr

ROBERTA_REV = "78fb38a59ea3cb6902e04d96da93efc87aeeff76"
ROBERTA_SHA = "63ff07ecdc769a0a44051e261492f0e6b7827711aa723560d4435236a54ee708"
MODES = ("deberta", "roberta", "consensus")
LIMITS = (-6, -2, 0, 2, 6)


def prediction(case, row, mode, threshold, corpus_mode="hybrid"):
    if "error" in row or (corpus_mode == "oracle" and "oracle_error" in row):
        return {"status": "error"}
    if corpus_mode == "oracle":
        pair = row["oracle"]
    else:
        docs = row[corpus_mode][:6]
        pair = {name: [row[name][doc] for doc in docs] for name in ("deberta", "roberta")}
    spans = {k: [replace(tr.SpanAnswer(**span), document_index=i) for i, span in enumerate(v)] for k, v in pair.items()}
    selected = select_answer(case["question"], spans["deberta"], spans["roberta"], mode, threshold)
    return {"status": "answered", **asdict(selected)} if selected else {"status": "abstained"}


def measure(docs, cases, rows, mode, threshold, corpus_mode="hybrid"):
    if set(rows) != {c["id"] for c in cases}:
        raise ValueError("Missing or unexpected case IDs")
    values = {"positive": [], "negative": []}
    for case in cases:
        value = tr.grade(case, prediction(case, rows[case["id"]], mode, threshold, corpus_mode), docs)
        values["negative" if case["impossible"] else "positive"].append(value)
    return {k: {"passed": sum(v), "n": len(v), "rate": sum(v) / len(v)} for k, v in values.items()}


def infer(question, docs, lexical, hybrid, readers, cached):
    ordered = list(dict.fromkeys(lexical + hybrid))
    result = {"lexical": lexical, "hybrid": hybrid}
    for name, reader in readers.items():
        previous = cached.get("spans", {}) if name == "deberta" else {}
        missing = [docs[doc] for doc in ordered if doc not in previous]
        spans = {s.source_id: asdict(s) for s in reader.predict_spans(question, missing)} if missing else {}
        spans.update({doc: previous[doc] for doc in ordered if doc in previous})
        if spans.keys() != set(ordered):
            raise ValueError("Missing local reader output")
        result[name] = spans
    return result


def run(args):
    import torch

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    torch.set_num_threads(4)
    root = args.output
    stage = root / "two-reader"
    stage.mkdir(exist_ok=True)
    previous = tr.load(root / "preregistration.json")
    weights = {}
    for name, directory in (("deberta", args.reader), ("roberta", args.second), ("embedding", args.embedding)):
        weights[name] = {p.name: tr.file_sha256(p) for p in directory.iterdir() if p.is_file() and p.name != "README.md"}
    if (weights["deberta"] != previous["model_files"]["reader"] or weights["embedding"] != previous["model_files"]["embedding"]
            or weights["roberta"]["model.safetensors"] != ROBERTA_SHA or tr.file_sha256(args.dataset) != tr.DATA_SHA):
        raise ValueError("Unregistered input file or model")
    panels = tr.panels(tr.load(args.dataset)["data"])
    if any(tr.json_sha256([docs, cases]) != previous["panels"][name]["manifest_sha256"] for name, (docs, cases) in panels.items()):
        raise ValueError("Reserved benchmark population changed")
    protocol = {
        "registered_panels": tr.file_sha256(root / "preregistration.json"), "source_sha256": tr.DATA_SHA,
        "previous_development_sha256": tr.file_sha256(root / "development.jsonl"), "secondary_model_revision": ROBERTA_REV,
        "weights": weights, "device": args.device,
        "code": {str(p.relative_to(tr.ROOT)): tr.file_sha256(p) for p in (
            Path(__file__).resolve(), Path(tr.__file__).resolve(),
            tr.ROOT / "app/modules/core/generation/english_consensus_reader.py",
            tr.ROOT / "app/modules/core/generation/english_span_reader.py",
            tr.ROOT / "app/modules/core/generation/korean_span_reader.py",
            tr.ROOT / "app/modules/core/retrieval/retrievers/local_span_retriever.py")},
        "modes": list(MODES), "thresholds": list(LIMITS), "candidate_depth": 6, "rank_penalty": .5,
        "selection": "Maximize minimum stratum accuracy, then sum, then smaller distance from zero, then simpler model.",
    }
    registration = stage / "preregistration.json"
    if args.phase == "prepare":
        tr.dump(registration, protocol)
        return
    if tr.load(registration) != protocol:
        raise ValueError("Evaluation sources or code changed")
    freeze_path = stage / "frozen-policy.json"
    if args.phase != "development":
        chosen = tr.load(freeze_path)
        if chosen["protocol_sha256"] != tr.file_sha256(registration) or chosen["development_sha256"] != tr.file_sha256(stage / "development.jsonl"):
            raise ValueError("Frozen selection mismatch")
    output = stage / (args.phase + ".jsonl")
    if output.exists() or (args.phase != "development" and (root / (args.phase + ".jsonl")).exists()):
        raise ValueError("Panel already exposed")
    fallback = {}
    if args.phase == "development":
        fallback = {r["id"]: r for r in map(json.loads, (root / "development.jsonl").read_text().splitlines())}
    docs, cases = panels[args.phase]
    readers = {name: tr.EnglishSpanReader(path, device=args.device) for name, path in (("deberta", args.reader), ("roberta", args.second))}
    search = tr.LocalSpanRetriever(docs, args.embedding, args.device)
    rows = {}
    with output.open("x", encoding="utf-8") as stream:
        for i, case in enumerate(cases):
            start = time.monotonic()
            cached = fallback.get(case["id"], {})
            try:
                lex, hybrid, _ = search.rankings(case["question"])
                if cached and (lex[:3] != cached["lexical"] or hybrid[:3] != cached["hybrid"]):
                    raise ValueError("Initial retrieved candidates changed")
                row = infer(case["question"], docs, lex[:6], hybrid[:6], readers, cached)
            except Exception as exc:
                row = {"error": type(exc).__name__ + ": " + str(exc)[:200]}
            if "error" not in row:
                try:
                    oracle = {}
                    for name, reader in readers.items():
                        gold = row[name].get(case["source"])
                        if not gold:
                            gold = asdict(reader.predict_spans(case["question"], [docs[case["source"]]])[0])
                        oracle[name] = [gold]
                    row["oracle"] = oracle
                except Exception as exc:
                    row["oracle_error"] = type(exc).__name__
            row.update(id=case["id"], elapsed_ms=round(1000 * (time.monotonic() - start)))
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            rows[case["id"]] = row
            if i % 8 == 0:
                print(args.phase, i + 1, "/", len(cases), "errors", sum("error" in r for r in rows.values()), flush=True)
    if args.phase == "development":
        trial = [(m, t, measure(docs, cases, rows, m, t)) for m in MODES for t in LIMITS]
        def objective(item):
            m, t, rates = item
            scores = [r["rate"] for r in rates.values()]
            return min(scores), sum(scores), -abs(t), -MODES.index(m)
        mode, threshold, _ = max(trial, key=objective)
        tr.dump(freeze_path, {"mode": mode, "threshold": threshold, "grid": trial, "protocol_sha256": tr.file_sha256(registration),
                              "development_sha256": tr.file_sha256(output)})
    else:
        mode, threshold = chosen["mode"], chosen["threshold"]
    primary = measure(docs, cases, rows, mode, threshold)
    v1rows = {k: {"id": k, "error": r["error"]} if "error" in r else
              {"id": k, "hybrid": r["hybrid"][:3], "lexical": r["lexical"][:3], "spans": r["deberta"]} for k, r in rows.items()}
    v1_threshold = tr.load(root / "frozen-policy.json")["threshold"]
    report = {
        "mode": mode, "threshold": threshold, "candidate": primary, "strict_pass": all(x["rate"] >= .8 for x in primary.values()),
        "ordinary_bm25_depth1": tr.metrics(docs, cases, v1rows, 0, "baseline"),
        "ordinary_bm25_depth6_with_selected_reader": measure(docs, cases, rows, mode, threshold, "lexical"),
        "previous_hybrid_depth3": tr.metrics(docs, cases, v1rows, v1_threshold, "candidate"),
        "oracle_passage_only": measure(docs, cases, rows, mode, threshold, "oracle"),
        "oracle_forced_positive_ceiling": measure(docs, cases, rows, mode, -1e6, "oracle")["positive"],
        "positive_recall6": sum(not c["impossible"] and c["source"] in rows[c["id"]].get("hybrid", []) for c in cases),
        "errors": sum("error" in r for r in rows.values()), "measured_sha256": tr.file_sha256(output),
        "policy_sha256": tr.file_sha256(freeze_path),
    }
    tr.dump(stage / (args.phase + "-report.json"), report)
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", *tr.SIZES))
    for key in ("reader", "second", "embedding", "dataset", "output"):
        parser.add_argument("--" + key, required=True, type=Path)
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    run(parser.parse_args())
