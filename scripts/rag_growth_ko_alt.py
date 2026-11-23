"""Measure the released Korean RoBERTa-large span checkpoint on development data only."""

import argparse
import dataclasses
import hashlib
import json
import math
import sys
import time
from importlib.metadata import version
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation.korean_span_reader import KoreanSpanReader
from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import file_sha256, index_sha256

MODEL = "oceann315/klue-roberta-large-korquad-v1"
REVISION = "2f75d2cc5144ac6719e86e96eca9215a94014f97"
WEIGHT_SHA = "b55bdfc6c8ccc6a11aa3b8971474ba9b69ade8fbbf5f466808de1a7d8b3b1d2e"
PENALTIES = (0, 2, 4, "top1")


def choose(row, penalty, threshold):
    spans = row["spans"][:1] if penalty == "top1" else row["spans"]
    best = max(spans, key=lambda s: value(s, penalty))
    out = {"id": row["id"], "retrieved": row["retrieved"]}
    if threshold is not None and value(best, penalty) <= threshold:
        return {**out, "status": "abstained"}
    return {**out, "status": "answered", **best}


def value(span, penalty):
    return span["score"] if penalty == "top1" else span["score"] - penalty * math.log2(1 + span["document_index"])


def fit(raw, labels, docs):
    """Optimize the worse stratum, then macro accuracy; exact ties retain the earliest policy."""
    best_key = (-1.0, -1.0)
    best = None
    for penalty in PENALTIES:
        predicted = [choose(r, penalty, None) for r in raw]
        scores = [value(r, penalty) for r in predicted]
        for threshold in [min(scores)-1, *sorted(set(scores))]:
            measured = [choose(r, penalty, threshold) for r in raw]
            summary = grade(measured, labels, docs)["summary"]
            key = (min(summary[g]["percent"] for g in ("answerable", "unanswerable")), summary["balanced_percent"])
            if key > best_key:
                best_key, best = key, (penalty, threshold)
    return best


def score(raw, labels, docs):
    assigned = {}
    gold = {g["id"]: g for g in labels}
    for answerable in (False, True):
        ids = sorted((k for k, g in gold.items() if g["answerable"] == answerable),
                     key=lambda k: hashlib.sha256(("ko-alt-oof-1/"+k).encode()).hexdigest())
        assigned.update({key: i % 2 for i, key in enumerate(ids)})
    results, settings = [], []
    for test in (0, 1):
        train_rows = [r for r in raw if assigned[r["id"]] != test]
        train_labels = [gold[r["id"]] for r in train_rows]
        p, t = fit(train_rows, train_labels, docs)
        settings.append({"test_fold": test, "train_rows": len(train_rows), "penalty": p, "threshold": t})
        results.extend(choose(r, p, t) for r in raw if assigned[r["id"]] == test)
    unconditional = {str(p): grade([choose(r, p, None) for r in raw], labels, docs)["summary"]["answerable"]
                     for p in PENALTIES}
    all_p, all_t = fit(raw, labels, docs)
    return {"zero_threshold": grade([choose(r, 0, 0) for r in raw], labels, docs)["summary"],
            "unthresholded_grounded_answerable": unconditional,
            "two_fold_out_of_fold": grade(results, labels, docs)["summary"], "fold_settings": settings,
            "fitted_on_all_dev_for_possible_future_freeze": {"penalty": all_p, "threshold": all_t},
            "oof_policy_selection": "maximize worse grounded-answer/abstention rate, then balanced accuracy; "
                                    "ties go to first rank penalty, lowest threshold",
            "question_fold": assigned}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panels", type=Path, required=True)
    parser.add_argument("--ranks", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", default="cpu", choices=("cpu", "mps"))
    args = parser.parse_args()
    reservation = json.loads((args.panels / "reservation.json").read_bytes())

    def read(part):
        path = args.panels / f"dev.{part}.json"
        if file_sha256(path) != reservation["files"][path.name]:
            raise ValueError("Changed development reservation")
        return json.loads(path.read_bytes())

    corpus, questions = read("corpus"), read("questions")
    ranks = json.loads(args.ranks.read_bytes())
    if (ranks["index_sha256"] != index_sha256(corpus)
            or ranks["dev_questions_sha256"] != reservation["files"]["dev.questions.json"]):
        raise ValueError("Changed retrieval index or questions")
    docs = {d["id"]: d for d in corpus}
    by_id = ranks["retrieved"]
    if {q["id"] for q in questions} != set(by_id) or any(len(a) != 3 or len(set(a)) != 3
                                                          or set(a)-set(docs) for a in by_id.values()):
        raise ValueError("Incomplete development retrieval rankings")
    model = args.model_dir
    if file_sha256(model/"model.safetensors") != WEIGHT_SHA:
        raise ValueError("Unexpected released weights")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    identity = {"model": MODEL, "revision": REVISION, "weights_sha256": WEIGHT_SHA, "device": args.device,
                "precision": "float32", "packages": {k: version(k) for k in ("torch", "transformers", "tokenizers")},
                "dev_files": {k: v for k, v in reservation["files"].items() if k.startswith("dev.")},
                "rank_sha256": file_sha256(args.ranks), "reader_sha256": file_sha256(
                    Path(__file__).resolve().parents[1]/"app/modules/core/generation/korean_span_reader.py"),
                "experiment_sha256": file_sha256(Path(__file__)), "model_files": {
                    n: file_sha256(model/n) for n in ("config.json", "tokenizer.json", "tokenizer_config.json",
                                                      "special_tokens_map.json", "vocab.txt")}}
    plan, path = args.output_dir/"run-identity.json", args.output_dir/"dev-spans.jsonl"
    if plan.exists():
        if json.loads(plan.read_bytes()) != identity:
            raise ValueError("Recorded partial results came from another reader or data")
    else:
        if path.exists():
            raise ValueError("Existing span file has no experiment identity")
        write_new(plan, identity)
    raw = [json.loads(line) for line in path.read_bytes().splitlines()] if path.exists() else []
    if [r["id"] for r in raw] != [q["id"] for q in questions[:len(raw)]]:
        raise ValueError("Unexpected or duplicate measured cases")
    if len(raw) < len(questions):
        import torch
        torch.set_num_threads(2)
        reader = KoreanSpanReader(model, device=args.device)
        if any(p.dtype != torch.float32 for p in reader.model.parameters()):
            raise ValueError("Expected FP32 parameters")
        # The released Korean checkpoint pairs BertTokenizerFast with RoBERTa's single token-type embedding.
        reader.tokenizer.model_input_names = ["input_ids", "attention_mask"]
        with path.open("a", encoding="utf-8") as stream:
            for q in questions[len(raw):]:
                start = time.perf_counter()
                ids = by_id[q["id"]]
                spans = reader.predict_spans(q["question"], [docs[i] for i in ids])
                row = {"id": q["id"], "retrieved": ids, "spans": [dataclasses.asdict(s) for s in spans],
                       "latency_ms": (time.perf_counter()-start)*1000}
                stream.write(json.dumps(row, ensure_ascii=False)+"\n")
                stream.flush()
                raw.append(row)
                if len(raw) % 10 == 0:
                    print("Measured", len(raw), "/", len(questions), flush=True)
    # Open labels only after all measured predictions are durable.
    result = score(raw, read("labels"), corpus)
    write_new(args.output_dir/"dev-evaluation.json", {"identity": identity, **result})
    print(json.dumps(result["two_fold_out_of_fold"], ensure_ascii=False))


if __name__ == "__main__":
    main()
