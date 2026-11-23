"""Try the product's local passage reranker on development before a separately reserved TyDi assessment."""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation.english_consensus_reader import select_answer
from app.modules.core.retrieval.interfaces import SearchResult
from scripts import rag_growth_transfer as tr
from scripts.rag_growth_transfer_diagnostics import wilson

REV = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
SHA = "821d1aa69520101d6e0737f78a042ae25b19e5cb9160701909d10434f4aeb0ae"
DEPTHS = (1, 3)
THRESHOLDS = (-2, 0, 2)


def get_spans(question, ids, docs, reader):
    try:
        spans = reader.predict_spans(question, [docs[d] for d in ids])
        if [s.source_id for s in spans] != ids:
            raise ValueError("Missing or reordered reader result")
        return [asdict(s) for s in spans]
    except Exception as error:
        return {"error": type(error).__name__ + ": " + str(error)[:180]}


def grade_policy(rows, docs, cases, key, threshold):
    grouped = {"positive": [], "negative": []}
    errors = 0
    for case in cases:
        evidence = rows[case["id"]][key]
        if isinstance(evidence, dict):
            pred = {"status": "error"}
            errors += 1
        else:
            picked = select_answer(case["question"], [tr.SpanAnswer(**s) for s in evidence], [], "deberta", threshold)
            pred = {"status": "abstained"} if picked is None else {"status": "answered", **asdict(picked)}
        grouped["negative" if case["impossible"] else "positive"].append(tr.grade(case, pred, docs))
    return {"errors": errors, "metrics": {key: {"passed": sum(v), "n": len(v), "rate": sum(v) / len(v),
                    "wilson95": wilson(sum(v), len(v))} for key, v in grouped.items()}}


def files(folder):
    return {p.name: tr.file_sha256(p) for p in folder.iterdir() if p.is_file() and p.name != "README.md"}


async def run(args):
    os.environ.update(HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    root = args.output
    dest = root / "minilm"
    dest.mkdir(exist_ok=True)
    inputs = {"reranker": files(args.reranker), "deberta": files(args.reader), "embedding": files(args.embedding)}
    before = tr.load(root / "two-reader/preregistration.json")["weights"]
    if inputs["reranker"]["model.safetensors"] != SHA or any(inputs[name] != before[name] for name in ("deberta", "embedding")):
        raise ValueError("Unregistered reader, reranker or embedding")
    tidy = tr.load(root / "tydi-preregistration.json")
    if tr.file_sha256(args.tydi) != tidy["manifest_sha256"] or tr.file_sha256(args.dataset) != tr.DATA_SHA:
        raise ValueError("Unexpected evaluation panel")
    cfg = {
        "source": "https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2", "reranker_revision": REV,
        "inputs": inputs, "device": args.device, "depths": list(DEPTHS), "thresholds": list(THRESHOLDS),
        "tydi_sha256": tidy["manifest_sha256"], "dev_rankings_sha256": tr.file_sha256(root / "independent-arms/development.jsonl"),
        "code": {str(p.relative_to(tr.ROOT)): tr.file_sha256(p) for p in (
            Path(__file__).resolve(), tr.ROOT / "app/modules/core/generation/english_span_reader.py",
            tr.ROOT / "app/modules/core/generation/korean_span_reader.py", tr.ROOT / "app/modules/core/generation/english_consensus_reader.py",
            tr.ROOT / "app/modules/core/retrieval/retrievers/local_span_retriever.py", tr.ROOT / "app/modules/core/retrieval/rerankers/local_reranker.py")},
        "retrieval": "Search all supplied passages, rerank top 20 by the product's MiniLM reranker then read top 1 or top 3.",
        "selection": "Highest min stratum then sum, then fewer passages then smallest absolute threshold. "
                     "Use MiniLM for TyDi only with a higher minimum, no stratum loss on development, and zero errors. "
                     "Otherwise use the preselected DeBERTa hybrid top-six policy, without running MiniLM on TyDi."}
    registration = dest / "preregistration.json"
    if args.phase == "prepare":
        tr.dump(registration, cfg)
        return
    if tr.load(registration) != cfg:
        raise ValueError("Previously registered configuration changed")
    if args.phase == "development":
        docs, cases = tr.panels(tr.load(args.dataset)["data"])["development"]
        previous = {r["id"]: r["hybrid_ids"] for r in map(json.loads, (root / "independent-arms/development.jsonl").read_text().splitlines())}
        if previous.keys() != {c["id"] for c in cases}:
            raise ValueError("Incomplete upstream retrieval")
        depths = DEPTHS
    else:
        chosen = tr.load(dest / "development-report.json")
        if chosen["protocol_sha256"] != tr.file_sha256(registration):
            raise ValueError("Development protocol changed")
        frozen = tr.load(args.tydi)
        docs, cases = frozen["documents"], frozen["cases"]
        depths = [chosen["depth"]] if chosen["adopt"] else []
        previous = {}
    import torch

    from app.modules.core.retrieval.rerankers.local_reranker import LocalReranker

    torch.set_num_threads(2)
    retriever = tr.LocalSpanRetriever(docs, args.embedding, args.device)
    reranker = LocalReranker(model_name=str(args.reranker), device="cpu", batch_size=4) if depths else None
    if reranker:
        await reranker.initialize()
    reader = tr.EnglishSpanReader(args.reader, device=args.device)
    rows = {}
    output = dest / (args.phase + ".jsonl")
    with output.open("x") as stream:
        for case in cases:
            q, qid = case["question"], case["id"]
            ids = retriever.rankings(q)[1][:20]
            if previous and previous[qid] != ids[:6]:
                raise ValueError("Fresh rankings differ from registered incumbent")
            row = {"id": qid, "hybrid": ids}
            try:
                hits = [SearchResult(id=d, content=docs[d]["content"], score=0.0, metadata={}) for d in ids]
                if reranker:
                    errors_before = reranker.stats["failed_requests"]
                    ranked = await reranker.rerank(q, hits)
                    if errors_before != reranker.stats["failed_requests"] or {h.id for h in ranked} != set(ids):
                        raise ValueError("Reranker failed or returned unexpected documents")
                    row["reranked"] = [h.id for h in ranked]
                for k in depths:
                    row[str(k)] = get_spans(q, row["reranked"][:k], docs, reader)
            except Exception as exc:
                for k in depths:
                    row[str(k)] = {"error": type(exc).__name__ + ": " + str(exc)[:180]}
            if not previous:
                row["baseline"] = get_spans(q, ids[:6], docs, reader)
            rows[qid] = row
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
    if args.phase == "development":
        previous_metrics = tr.load(root / "independent-arms/development-report.json")["arms"]["candidate"]
        candidates = [(k, t, grade_policy(rows, docs, cases, str(k), t)) for k in depths for t in THRESHOLDS]
        def objective(item):
            k, t, scores = item
            rates = [s["rate"] for s in scores["metrics"].values()]
            return min(rates), sum(rates), -k, -abs(t)
        depth, threshold, result = max(candidates, key=objective)
        observed = result["metrics"]
        adopt = (not result["errors"] and all(observed[s]["rate"] >= previous_metrics[s]["rate"] for s in observed)
                 and min(v["rate"] for v in observed.values()) > min(v["rate"] for v in previous_metrics.values()))
        report = {"depth": depth, "threshold": threshold, "adopt": adopt, "baseline": previous_metrics,
                  "candidate": result, "tested_grid": candidates}
    else:
        incumbent = grade_policy(rows, docs, cases, "baseline", -2)
        report = {"selected": "MiniLM + DeBERTa" if depths else "original frozen DeBERTa",
                  "depth": depths[0] if depths else 6, "threshold": chosen["threshold"] if depths else -2,
                  "baseline": incumbent, "candidate": grade_policy(rows, docs, cases, str(depths[0]), chosen["threshold"]) if depths else incumbent}
    report.update(protocol_sha256=tr.file_sha256(registration), measured_sha256=tr.file_sha256(output))
    tr.dump(dest / (args.phase + "-report.json"), report)
    print(json.dumps({k: v for k, v in report.items() if k != "tested_grid"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "development", "tydi"))
    for name in ("reader", "reranker", "dataset", "embedding", "tydi", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--device", choices=("cpu", "mps"), default="mps")
    asyncio.run(run(parser.parse_args()))
