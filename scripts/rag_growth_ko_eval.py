"""Evaluate a local reader on reserved Korean questions with the production sparse retriever."""

import argparse
import asyncio
import dataclasses
import hashlib
import importlib
import importlib.util
import inspect
import json
import math
import os
import sys
import time
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from tempfile import NamedTemporaryFile

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.rag_growth_gate import normalized
from scripts.rag_growth_ko_panels import encode
from scripts.rag_growth_local import ROOT, Corpus, file_sha256, local_http_client, verify_server

SPAN_FIELDS = ("answer", "source_id", "start", "end", "quote", "quote_start", "quote_end")
QWEN_ADAPTER = "scripts.rag_growth_qwen_reader:local_reader"


class ReaderCorpus:
    def __init__(self, documents):
        self.documents = {d["id"]: {k: d[k] for k in ("id", "title", "content")} for d in documents}
        if len(self.documents) != len(documents):
            raise ValueError("Duplicate corpus article ID")
        self.engine = Corpus(list(self.documents.values())).index


def retrieve(corpus, question, top_k=3):
    return [dict(corpus.documents[h["id"]]) for h in corpus.engine.search(question, top_k)]


async def evaluate_cases(corpus, questions, callback, top_k=3):
    """callback(question, retrieved documents) returns a grounded span, None, or raises on errors."""
    rows = []
    for q in questions:
        start = time.perf_counter()
        ids = []
        try:
            docs = retrieve(corpus, q["question"], top_k)
            ids = [d["id"] for d in docs]
            if not ids:
                raise ValueError("No retrieved articles")
            result = callback(q["question"], docs)
            if inspect.isawaitable(result):
                result = await result
            if result is None:
                row = {"status": "abstained"}
            else:
                fields = dataclasses.asdict(result) if dataclasses.is_dataclass(result) else result
                row = {"status": "answered", **{k: fields[k] for k in SPAN_FIELDS}}
                if isinstance(fields.get("score"), (int, float)) and math.isfinite(fields["score"]):
                    row["score"] = float(fields["score"])
        except Exception as exc:
            row = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}
        rows.append({"id": q["id"], "retrieved": ids, **row, "latency_ms": (time.perf_counter()-start)*1000})
    return rows


def confidence(k, n):
    if not n:
        return {"correct": k, "n": n, "percent": None, "wilson95_percent": None}
    p, z = k / n, 1.95996398454
    mid = (p + z*z/(2*n)) / (1 + z*z/n)
    half = z * math.sqrt((p*(1-p) + z*z/(4*n)) / n) / (1 + z*z/n)
    return {"correct": k, "n": n, "percent": 100*p,
            "wilson95_percent": [100*max(0, mid-half), 100*min(1, mid+half)]}


def checked_span(row, docs):
    key = row.get("source_id")
    if not isinstance(key, str) or key not in docs or key not in row["retrieved"]:
        return False
    a, b, c, d = (row.get(k) for k in ("start", "end", "quote_start", "quote_end"))
    body = docs[key]
    return (all(type(i) is int for i in (a, b, c, d)) and 0 <= c <= a < b <= d <= len(body)
            and body[a:b] == row.get("answer") and body[c:d] == row.get("quote"))


def grade(rows, labels, documents):
    gold = {label["id"]: label for label in labels}
    if len(labels) != len(gold) or len(rows) != len(gold) or {r["id"] for r in rows} != set(gold):
        raise ValueError("Missing, repeated or unknown question results")
    docs = {d["id"]: d["content"] for d in documents}
    tally, statuses = Counter(), Counter()
    outcomes = []
    for row in rows:
        label, status = gold[row["id"]], row["status"]
        if status not in ("answered", "abstained", "error"):
            raise ValueError("Unknown reader response status")
        ids = row["retrieved"]
        if len(ids) != len(set(ids)) or any(cid not in docs for cid in ids):
            raise ValueError("Repeated or unknown retrieved article")
        source, pos = label["source_id"], label["answerable"]
        has_reference = source is not None
        if ((pos or has_reference) and source not in docs) or type(pos) is not bool or pos != bool(label["answers"]):
            raise ValueError("Invalid reserved label")
        group = "answerable" if pos else "unanswerable"
        tally[group] += 1
        tally[group + "_reference_n"] += has_reference
        hit = source in ids
        tally[group + "_hit"] += hit
        statuses[status] += 1
        correct = False
        em = False
        if status == "answered" and isinstance(row.get("answer"), str):
            em = pos and normalized(row["answer"]) in {normalized(a) for a in label["answers"]}
            # Anchor the quote to the actual annotated occurrence in the reference article.
            if em and source == row.get("source_id") and checked_span(row, docs):
                correct = any(row["quote_start"] <= s["start"] < s["end"] <= row["quote_end"]
                              and row["start"] < s["end"] and s["start"] < row["end"] for s in label["spans"])
        elif status == "abstained":
            correct = not pos and bool(ids) and not any(row.get(k) for k in (*SPAN_FIELDS, "citations", "cited_evidence"))
        tally["answerable_answered"] += pos and status == "answered"
        tally["exact"] += em
        tally[group + "_ok"] += correct
        tally[group + "_covered_ok"] += correct and hit
        outcomes.append({"id": row["id"], "answerable": pos,
                         "source_retrieved": hit if has_reference else None, "correct": correct})
    summary = {}
    for group in ("answerable", "unanswerable"):
        summary[group] = confidence(tally[group + "_ok"], tally[group])
        summary[group + "_reference_retrieved"] = confidence(tally[group + "_hit"], tally[group + "_reference_n"])
        summary[group + "_with_reference_retrieved"] = confidence(tally[group + "_covered_ok"], tally[group + "_hit"])
    summary["overall"] = confidence(tally["answerable_ok"]+tally["unanswerable_ok"], len(rows))
    summary["answerable_text_exact"] = confidence(tally["exact"], tally["answerable"])
    summary["balanced_percent"] = (sum(summary[g]["percent"] for g in ("answerable", "unanswerable")) / 2
                                   if tally["answerable"] and tally["unanswerable"] else None)
    summary["statuses"] = dict(statuses)
    summary["answered_precision"] = confidence(tally["answerable_ok"], statuses["answered"])
    summary["answerable_answered"] = confidence(tally["answerable_answered"], tally["answerable"])
    summary["both_at_least_80"] = all(
        tally[group] > 0 and 5*tally[group+"_ok"] >= 4*tally[group] for group in ("answerable", "unanswerable")
    )
    return {"summary": summary, "outcomes": outcomes}


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent) as temp:
        temp.write(encode(data))
        temp.flush()
        os.link(temp.name, path)


def policy_identity(args):
    if not 1 <= args.top_k <= 512:
        raise ValueError("Invalid retrieval depth")
    paths = [Path(__file__), ROOT / "scripts/rag_growth_gate.py", ROOT / "scripts/rag_growth_ko_panels.py",
             ROOT / "scripts/rag_growth_local.py", *args.policy_file]
    for name in ("index.py", "tokenizer.py", "linked_titles.py"):
        paths.append(ROOT / "app/modules/core/retrieval/bm25_engine" / name)
    profile = getattr(args, "agent_profile", None)
    if profile is not None:
        from scripts.rag_growth_profile import profile_identity
        if args.adapter or args.model_file or args.model_dir:
            raise ValueError("Choose one agent profile or standalone reader")
        reader = json.loads(profile.read_bytes())["reader"]
        if args.top_k != reader.get("top_k", 3) or args.device != reader.get("device", "cpu"):
            raise ValueError("Set --top-k and --device to match the agent profile")
        model = profile_identity(profile)
    elif args.adapter:
        module, separator, function = args.adapter.partition(":")
        if not separator or not function or args.model_file is None or args.model_dir is not None:
            raise ValueError("An importable adapter and --model-file are required for a custom policy")
        spec = importlib.util.find_spec(module)
        if not spec or not spec.origin:
            raise ValueError("Missing adapter module")
        paths.append(Path(spec.origin))
        if args.adapter == QWEN_ADAPTER:
            paths.extend([ROOT / "app/modules/core/generation/grounded_span.py", ROOT / "app/lib/llm_client.py"])
        model = {args.model_file.name: file_sha256(args.model_file)}
    else:
        if not args.model_dir or args.model_file:
            raise ValueError("Provide --model-dir for the Korean span reader")
        paths.append(ROOT / "app/modules/core/generation/korean_span_reader.py")
        model = {str(p.relative_to(args.model_dir)): file_sha256(p) for p in sorted(args.model_dir.rglob("*"))
                 if p.is_file() and not any(part.startswith(".") for part in p.relative_to(args.model_dir).parts)}
        if "reader_config.json" not in model or not any(x.endswith(".safetensors") for x in model):
            raise ValueError("Missing local reader weights or frozen threshold")
    return {"adapter": "AgentFactory" if profile else args.adapter or "KoreanSpanReader.read",
            "top_k": args.top_k, "device": args.device,
            "model_files": model, "policy_files": {str(p.resolve()): file_sha256(p) for p in paths},
            "packages": {k: version(k) for k in ("rank-bm25", "kiwipiepy", "kiwipiepy_model", "numpy", "torch",
                                                 "transformers")},
            "reservation_sha256": file_sha256(args.panels / "reservation.json")}


def read_part(args, reservation, part):
    name = f"{args.split}.{part}.json"
    raw = (args.panels / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != reservation["files"][name]:
        raise ValueError(f"Reserved input changed: {name}")
    return json.loads(raw)


async def run(args):
    if args.split != "freeze" and (not args.output or args.output.exists()):
        raise ValueError("Use an unoccupied --output")
    identity = policy_identity(args)
    if args.split == "freeze":
        if not args.freeze:
            raise ValueError("--freeze is required")
        write_new(args.freeze, identity)
        return
    if args.adapter == QWEN_ADAPTER:
        async with local_http_client("http://127.0.0.1:18759") as client:
            await verify_server(client, "onerag-growth-qwen", args.model_file, identity["model_files"][args.model_file.name])
    if args.split == "final":
        if not args.freeze or json.loads(args.freeze.read_bytes()) != identity:
            raise ValueError("Create a matching policy freeze before opening the final panel")
        write_new(args.freeze.with_name(args.freeze.name + ".started"),
                  {"freeze_sha256": file_sha256(args.freeze), "output": str(args.output)})
    reservation = json.loads((args.panels / "reservation.json").read_bytes())
    documents = read_part(args, reservation, "corpus")
    questions = read_part(args, reservation, "questions")
    if any(set(q) != {"id", "question"} for q in questions):
        raise ValueError("The inference question file may not contain labels")
    if getattr(args, "agent_profile", None) is not None:
        from scripts.rag_growth_profile import run_profile
        rows = await run_profile(documents, questions, args.agent_profile, identity["model_files"])
    else:
        corpus = ReaderCorpus(documents)
        if args.adapter:
            module, _, name = args.adapter.partition(":")
            callback = getattr(importlib.import_module(module), name)
        else:
            from app.modules.core.generation.korean_span_reader import KoreanSpanReader
            callback = KoreanSpanReader(args.model_dir, device=args.device).read
        rows = await evaluate_cases(corpus, questions, callback, args.top_k)
    labels = read_part(args, reservation, "labels")
    evaluation = grade(rows, labels, documents)
    write_new(args.output, {"split": args.split, "identity": identity, "rows": rows, **evaluation})
    print(json.dumps(evaluation["summary"], ensure_ascii=False))
    if getattr(args, "require_target", False) and not evaluation["summary"]["both_at_least_80"]:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panels", type=Path, required=True)
    parser.add_argument("--split", choices=("dev", "freeze", "final"), required=True)
    for name in ("model-dir", "model-file", "agent-profile", "freeze", "output"):
        parser.add_argument("--"+name, type=Path)
    parser.add_argument("--adapter", help="Importable module:function. Accepts question and retrieved documents only.")
    parser.add_argument("--policy-file", type=Path, default=[], action="append")
    parser.add_argument("--top-k", default=3, type=int)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--require-target", action="store_true", help="Exit 1 if either strict rate is below 80 percent.")
    try:
        asyncio.run(run(parser.parse_args()))
    except (OSError, ValueError, ImportError) as exc:
        parser.exit(2, f"Evaluation failed: {exc}\n")


if __name__ == "__main__":
    main()
