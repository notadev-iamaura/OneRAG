"""Measure one fixed local generative adjudicator on retrieved English encoder disagreements."""

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation.english_span_review import review_input, review_spans
from scripts import rag_growth_local as local
from scripts import rag_growth_transfer as tr
from scripts import rag_growth_transfer_ensemble as ens

GGUF_SHA = "96b9c0af5c77a4ecaabe3983175112b5ece763261c1ece12b2494b692a70dad7"
MODEL = "onerag-growth-qwen"


async def run(args):
    os.environ.update(ENVIRONMENT="test", LANGFUSE_ENABLED="false")
    from openai import AsyncOpenAI

    from app.lib.llm_client import OllamaLLMClient
    from app.lib.request_cost import bind_request_cost_ledger

    root = args.output
    source = root / "two-reader"
    dest = root / "review"
    dest.mkdir(exist_ok=True)
    frozen = tr.load(source / "frozen-policy.json")
    if frozen["mode"] != "deberta" or tr.file_sha256(args.dataset) != tr.DATA_SHA or not 0 < args.port < 65536:
        raise ValueError("The reviewer requires the fixed DeBERTa policy and registered public dataset")
    protocol = {"model": MODEL, "gguf_sha256": GGUF_SHA, "temperature": 0, "max_tokens": 144,
                "trigger": "DeBERTa and RoBERTa differ on selected document/answer or abstention at the fixed threshold.",
                "inputs": "Only the question and bounded verbatim passages around the top spans of the two readers.",
                "encoder_policy_sha256": tr.file_sha256(source / "frozen-policy.json"),
                "encoder_development_sha256": tr.file_sha256(source / "development.jsonl"),
                "code_sha256": tr.file_sha256(Path(__file__)),
                "reviewer_sha256": tr.file_sha256(tr.ROOT / "app/modules/core/generation/english_span_review.py"),
                "adoption": "Strict development improvement in the lower stratum; no decrease in either stratum."}
    registration = dest / "preregistration.json"
    if args.phase == "prepare":
        tr.dump(registration, protocol)
        return
    if tr.load(registration) != protocol:
        raise ValueError("Review protocol changed")
    if args.phase != "development" and not tr.load(dest / "development-report.json")["adopt"]:
        raise ValueError("Generative review did not pass development")
    docs, cases = tr.panels(tr.load(args.dataset)["data"])[args.phase]
    parent = tr.load(source / (args.phase + "-report.json"))
    parent_file = source / (args.phase + ".jsonl")
    if parent["measured_sha256"] != tr.file_sha256(parent_file):
        raise ValueError("Encoder measurements changed")
    rows = {r["id"]: r for r in map(json.loads, parent_file.read_text().splitlines())}
    if rows.keys() != {c["id"] for c in cases}:
        raise ValueError("Incomplete upstream measurements")
    threshold = frozen["threshold"]
    observed, delta, triggered, tokens = {"positive": [], "negative": []}, {"gain": 0, "loss": 0}, 0, 0
    origin = f"http://127.0.0.1:{args.port}"
    output = dest / (args.phase + ".jsonl")
    async with local.local_http_client(origin) as http:
        props = (await http.get("/props")).raise_for_status().json()
        await local.verify_server(http, MODEL, Path(props["model_path"]), GGUF_SHA)
        model = OllamaLLMClient({"model": MODEL, "base_url": origin, "temperature": 0, "max_tokens": 144})
        model._client = AsyncOpenAI(base_url=origin + "/v1", api_key="not-needed", http_client=http, max_retries=0, timeout=120)
        with output.open("x", encoding="utf-8") as handle:
            for case in cases:
                started = time.monotonic()
                row = rows[case["id"]]
                called = False
                old = ens.prediction(case, row, "deberta", threshold)
                with bind_request_cost_ledger() as usage:
                    if "error" in row:
                        pred = {"status": "error", "reason": row["error"]}
                    else:
                        ranked = row["hybrid"]
                        passages = [docs[d] for d in ranked]
                        spans = [[replace(tr.SpanAnswer(**row[k][d]), document_index=i) for i, d in enumerate(ranked)]
                                 for k in ("deberta", "roberta")]
                        try:
                            _, excerpts = review_input(case["question"], passages, *spans, threshold)
                            called = bool(excerpts)
                            result, _ = await review_spans(case["question"], passages, *spans, threshold, model)
                            pred = {"status": "abstained"} if result is None else {"status": "answered", **asdict(result)}
                        except Exception as exc:
                            pred = {"status": "error", "reason": type(exc).__name__ + ": " + str(exc)[:180]}
                triggered += called
                tokens += usage.total_tokens
                before, after = tr.grade(case, old, docs), tr.grade(case, pred, docs)
                observed["negative" if case["impossible"] else "positive"].append(after)
                delta["gain"] += after and not before
                delta["loss"] += before and not after
                handle.write(json.dumps({"id": case["id"], "review_called": called, "model_calls": usage.call_count,
                                         "tokens": usage.total_tokens, "elapsed_ms": round(1000 * (time.monotonic() - started)),
                                         "prediction": pred}, ensure_ascii=False) + "\n")
                handle.flush()
    rates = {k: {"passed": sum(v), "n": len(v), "rate": sum(v) / len(v)} for k, v in observed.items()}
    originals = parent["candidate"]
    adopt = (all(rates[k]["rate"] >= originals[k]["rate"] for k in rates)
             and min(v["rate"] for v in rates.values()) > min(v["rate"] for v in originals.values()))
    report = {"split": args.phase, "adopt": adopt if args.phase == "development" else None,
              "candidate": rates, "encoder_only": originals, "review_calls": triggered, "total_tokens": tokens,
              "paired_changes": delta, "measured_sha256": tr.file_sha256(output),
              "protocol_sha256": tr.file_sha256(registration), "upstream_sha256": tr.file_sha256(parent_file)}
    tr.dump(dest / (args.phase + "-report.json"), report)
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", *tr.SIZES))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18759)
    asyncio.run(run(parser.parse_args()))
