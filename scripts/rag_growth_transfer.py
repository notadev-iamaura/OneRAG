"""Run local, source-verified extractive QA on article-disjoint SQuAD v2 development panels."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import unicodedata
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))

from app.modules.core.generation.english_span_reader import EnglishSpanReader
from app.modules.core.generation.korean_span_reader import SpanAnswer
from app.modules.core.retrieval.retrievers.local_span_retriever import LocalSpanRetriever
from scripts.rag_growth_local import file_sha256, json_sha256

DATA_SHA = "80a5225e94905956a6446d296ca1093975c4d3b3260f1d6c8f68bc2ab77182d8"
DATA_REV = "e0c66cfec263165fb3c15cb76a22175e371b71d7"
READER_REV = "ff971b7ff7946434a93edc8271fa4de35eab29f7"
READER_SHA = "6b812abad65a88f85d211877306e139c6ce643768b3138a7d490b46f010ceab8"
E5_REV = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
E5_SHA = "1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477"
SIZES = {"development": 24, "final": 32, "confirmation": 32}
THRESHOLDS = (-4, -2, 0, 2, 4, 6)


def key(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dump(path, payload):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def load(path):
    return json.loads(path.read_bytes())


def panels(articles, sizes=SIZES):
    ordered = sorted(articles, key=lambda a: key("onerag-squad-transfer-03/article/" + a["title"]))
    result = {}
    for index, (name, n) in enumerate(sizes.items()):
        chosen = ordered[index::len(sizes)]
        docs, available, all_questions = {}, [], set()
        for article in chosen:
            for paragraph in article["paragraphs"]:
                body = paragraph["context"]
                doc_id = key(body)
                if doc_id in docs:
                    raise ValueError("Duplicate passage in registered corpus")
                docs[doc_id] = {"id": doc_id, "title": article["title"].replace("_", " "), "content": body}
                for qa in paragraph["qas"]:
                    if qa["is_impossible"] != (not qa["answers"]):
                        raise ValueError("Inconsistent official answerability")
                    if any(body[a["answer_start"]:a["answer_start"] + len(a["text"])] != a["text"] for a in qa["answers"]):
                        raise ValueError("Official answer span differs from source")
                    available.append({"id": qa["id"], "question": qa["question"], "impossible": qa["is_impossible"],
                                      "source": doc_id, "answers": qa["answers"]})
        selected, used, counts = [], set(), {True: 0, False: 0}
        for case in sorted(available, key=lambda c: key("onerag-squad-transfer-03/question/" + c["id"])):
            question = normalize(case["question"])
            group = case["impossible"]
            if counts[group] < n and case["source"] not in used and question not in all_questions:
                selected.append(case)
                used.add(case["source"])
                all_questions.add(question)
                counts[group] += 1
        if counts != {True: n, False: n}:
            raise ValueError("Too few independent questions")
        result[name] = (dict(sorted(docs.items())), selected)
    seen_docs, seen_titles, seen_questions = set(), set(), set()
    for docs, cases in result.values():
        titles = {d["title"] for d in docs.values()}
        questions = {normalize(c["question"]) for c in cases}
        if docs.keys() & seen_docs or titles & seen_titles or questions & seen_questions:
            raise ValueError("Overlapping registered questions, articles or passages")
        seen_docs.update(docs)
        seen_titles.update(titles)
        seen_questions.update(questions)
    return result


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())






def predict(row, threshold, strategy):
    if row.get("error") or (strategy == "oracle" and row.get("oracle_error")):
        return {"status": "error"}
    if strategy == "oracle":
        span = row.get("oracle")
        return ({"status": "answered", **span} if span and span["score"] > threshold else {"status": "abstained"})
    ranked = row["hybrid"] if strategy == "candidate" else row["lexical"][:1 if strategy == "baseline" else 3]
    if not ranked:
        return {"status": "abstained"}
    spans = [replace(SpanAnswer(**row["spans"][doc]), document_index=rank) for rank, doc in enumerate(ranked)]
    chosen = EnglishSpanReader.choose(spans, .5)
    if chosen is None or chosen.score <= threshold:
        return {"status": "abstained"}
    return {"status": "answered", **asdict(chosen)}


def grade(case, pred, docs):
    if case["impossible"]:
        return pred["status"] == "abstained"
    if pred["status"] != "answered" or pred["source_id"] != case["source"]:
        return False
    body = docs[pred["source_id"]]["content"]
    return (
        body[pred["start"]:pred["end"]] == pred["answer"] and body[pred["quote_start"]:pred["quote_end"]] == pred["quote"]
        and pred["quote_start"] <= pred["start"] < pred["end"] <= pred["quote_end"]
        and any(normalize(pred["answer"]) == normalize(a["text"])
                and pred["quote_start"] <= a["answer_start"] and a["answer_start"] + len(a["text"]) <= pred["quote_end"]
                for a in case["answers"])
    )


def metrics(docs, cases, rows, threshold, strategy):
    if set(rows) != {c["id"] for c in cases}:
        raise ValueError("Incomplete QA panel")
    groups = {"positive": [], "negative": []}
    for c in cases:
        passed = grade(c, predict(rows[c["id"]], threshold, strategy), docs)
        groups["negative" if c["impossible"] else "positive"].append(passed)
    return {k: {"passed": sum(v), "n": len(v), "rate": sum(v) / len(v)} for k, v in groups.items()}


def run(args):
    import torch

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    torch.set_num_threads(4)
    if file_sha256(args.dataset) != DATA_SHA:
        raise ValueError("Unregistered SQuAD source")
    data = panels(load(args.dataset)["data"])
    root = args.output
    root.mkdir(parents=True, exist_ok=True)
    registered = {
        "data_sha256": DATA_SHA, "dataset_revision": DATA_REV, "reader_revision": READER_REV, "reader_sha256": READER_SHA,
        "embedding_revision": E5_REV, "device": args.device, "code_sha256": file_sha256(Path(__file__)),
        "reader_code": {name: file_sha256(ROOT / "app/modules/core/generation" / name)
                        for name in ("english_span_reader.py", "korean_span_reader.py")},
        "retriever_code": file_sha256(ROOT / "app/modules/core/retrieval/retrievers/local_span_retriever.py"),
        "model_files": {name: {p.name: file_sha256(p) for p in folder.iterdir()
                               if p.is_file() and p.name not in ("README.md",)}
                        for name, folder in (("reader", args.reader), ("embedding", args.embedding))},
        "panels": {name: {"manifest_sha256": json_sha256([docs, cases]), "documents": len(docs),
                           "distinct_titles": len({d["title"] for d in docs.values()}), "questions_per_stratum": SIZES[name],
                           "case_ids": [c["id"] for c in cases]} for name, (docs, cases) in data.items()},
        "selection": "Choose the highest minimum development-stratum accuracy, then mean accuracy, then threshold closest to zero.",
        "thresholds": THRESHOLDS, "baseline": "OneRAG lexical top-1, fixed null margin 0",
        "candidate": "OneRAG lexical/E5 top-40 equal RRF, top-3 reader, 0.5*log2(rank) margin penalty",
        "source": "https://rajpurkar.github.io/SQuAD-explorer/", "model": "https://huggingface.co/deepset/deberta-v3-large-squad2",
    }
    registered = json.loads(json.dumps(registered))
    if (registered["model_files"]["reader"]["model.safetensors"] != READER_SHA
            or registered["model_files"]["embedding"]["model.safetensors"] != E5_SHA):
        raise ValueError("Unregistered model weights")
    protocol_file = root / "preregistration.json"
    if args.phase == "prepare":
        dump(protocol_file, registered)
        return
    if load(protocol_file) != registered:
        raise ValueError("The registered dataset, model, code or device changed")
    selection_path = root / "frozen-policy.json"
    if args.phase != "development":
        selected = load(selection_path)
        if selected["protocol_sha256"] != file_sha256(protocol_file) or selected["development_sha256"] != file_sha256(root / "development.jsonl"):
            raise ValueError("Frozen policy differs from its development run")
    docs, cases = data[args.phase]
    destination = root / (args.phase + ".jsonl")
    if destination.exists():
        raise ValueError("This panel has already been opened")
    reader = EnglishSpanReader(args.reader, device=args.device)
    retrieval = LocalSpanRetriever(docs, args.embedding, args.device)
    rows = {}
    with destination.open("x", encoding="utf-8") as stream:
        for number, case in enumerate(cases):
            start = time.monotonic()
            try:
                lexical_all, hybrid_all, _ = retrieval.rankings(case["question"])
                lexical, hybrid = lexical_all[:3], hybrid_all[:3]
                hits = [docs[d] for d in dict.fromkeys(lexical + hybrid)]
                spans = {s.source_id: asdict(s) for s in reader.predict_spans(case["question"], hits)}
                if len(spans) != len(hits):
                    raise ValueError("Retrieved passage produced no valid span")
                row = {"id": case["id"], "lexical": lexical, "hybrid": hybrid, "spans": spans}
            except Exception as exc:
                row = {"id": case["id"], "error": type(exc).__name__ + ": " + str(exc)[:200]}
            if "error" not in row:
                # The oracle diagnostic runs separately after ordinary retrieval and answer scoring inputs are fixed.
                try:
                    oracle = row["spans"].get(case["source"])
                    if oracle is None:
                        oracle = asdict(reader.predict_spans(case["question"], [docs[case["source"]]])[0])
                    row["oracle"] = oracle
                except Exception as exc:
                    row["oracle_error"] = type(exc).__name__
            row["elapsed_ms"] = round(1000 * (time.monotonic() - start))
            rows[case["id"]] = row
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            if number % 8 == 0:
                print(args.phase, number + 1, "/", len(cases), "errors", sum("error" in r for r in rows.values()), flush=True)
    if args.phase == "development":
        trials = {v: metrics(docs, cases, rows, v, "candidate") for v in THRESHOLDS}
        def objective(v):
            rates = [g["rate"] for g in trials[v].values()]
            return min(rates), sum(rates), -abs(v)
        threshold = max(THRESHOLDS, key=objective)
        dump(selection_path, {"threshold": threshold, "development_grid": trials, "development_sha256": file_sha256(destination),
                              "protocol_sha256": file_sha256(protocol_file)})
    else:
        threshold = selected["threshold"]
    report = {"split": args.phase, "baseline": metrics(docs, cases, rows, 0, "baseline"),
              "candidate": metrics(docs, cases, rows, threshold, "candidate"), "threshold": threshold,
              "standard_bm25_reader": metrics(docs, cases, rows, threshold, "bm25"),
              "oracle_passage_diagnostic": metrics(docs, cases, rows, threshold, "oracle"),
              "errors": sum("error" in r for r in rows.values()), "questions": len(cases), "documents": len(docs),
              "positive_retrieval": {
                  name: sum(c["source"] in rows[c["id"]].get(name, []) for c in cases if not c["impossible"])
                  for name in ("lexical", "hybrid")
              }, "measured_sha256": file_sha256(destination), "policy_sha256": file_sha256(selection_path)}
    dump(root / (args.phase + "-report.json"), report)
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", *SIZES))
    for name in ("reader", "embedding", "dataset", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
