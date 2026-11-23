"""Use only registered local QA predictions to prepare and run the English Gemma option review."""

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import statistics
import sys
from dataclasses import asdict
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation import english_option_review as policy
from app.modules.core.generation.english_consensus_reader import select_answer
from scripts import rag_growth_transfer as tr
from scripts.rag_growth_transfer_cross_domain import eligible
from scripts.rag_growth_transfer_diagnostics import wilson
from scripts.rag_growth_transfer_fit import verdict
from scripts.rag_growth_transfer_train_features import collect, panel, read_jsonl

MODEL = "onerag-growth-gemma"
ORIGIN = "http://127.0.0.1:18761"
WEIGHTS = "0a270ec9fe6b34f4a0d33992b6135117b484ebc4766ab76b51d4ae8c457e4c42"
MODEL_FILE = Path.home() / "Models/gemma-4-12b/gemma-4-12b-it-Q4_K_M.gguf"


def sha_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def source_hashes():
    names = [
        "scripts/rag_growth_transfer_option_review.py", "scripts/rag_growth_transfer.py",
        "scripts/rag_growth_transfer_train_features.py", "scripts/rag_growth_transfer_cross_domain.py",
        "scripts/rag_growth_transfer_fit.py", "scripts/rag_growth_transfer_diagnostics.py",
        "scripts/rag_growth_local.py", "app/lib/llm_client.py",
        "app/modules/core/generation/english_option_review.py",
        "app/modules/core/generation/english_calibrated_spans.py",
        "app/modules/core/generation/english_consensus_reader.py",
        "app/modules/core/generation/english_span_reader.py",
        "app/modules/core/generation/korean_span_reader.py",
        "app/modules/core/generation/english_span_proposals.py",
        "app/modules/core/retrieval/retrievers/local_span_retriever.py",
    ]
    return {p: tr.file_sha256(tr.ROOT / p) for p in names}


def load_evidence(directory, phase):
    receipt = tr.load(directory / (phase + "-evidence.json"))
    if receipt["protocol_sha256"] != tr.file_sha256(directory / "features-protocol.json") or any(
        tr.file_sha256(directory / p) != digest for p, digest in receipt["files"].items()
    ):
        raise ValueError("Source retrieval or reader predictions changed")
    return receipt


def material(args, phase):
    previous = args.output.parent / "supervised"
    directory = previous if phase == "development" else args.output.parent / "gemma-options-confirmation-cache"
    load_evidence(directory, phase)
    fitted = tr.load(previous / "calibrator.json")
    if fitted["train_evidence_sha256"] != tr.file_sha256(previous / "train-evidence.json"):
        raise ValueError("Official-training-only ranker changed")
    groups, audit = {}, {}
    for name in ["squad", "development"] if phase == "development" else ["confirmation"]:
        proxy = argparse.Namespace(**{**vars(args), "output": directory})
        docs, cases = panel(proxy, name)
        cache = [read_jsonl(directory / (name + "-" + k + ".jsonl")) for k in ("ranks", "incumbent", "proposals")]
        if any(set(source) != {c["id"] for c in cases} for source in cache):
            raise ValueError("Source files do not cover each scored question")
        rows, ceiling, sizes, prompt_lengths, doc_counts = [], 0, [], [], []
        for c in cases:
            qid, question = c["id"], c["question"]
            rank, incumbent, source = (entry[qid] for entry in cache)
            ids = rank["docs"]
            if len(ids) != 12 or len(set(ids)) != 12 or len(incumbent["original"]) != 6 or len(source["proposals"]) != 12:
                raise ValueError("Incomplete top-12 search or local reader inference")
            old = [tr.SpanAnswer(**s) for s in incumbent["original"]]
            proposed = [[tr.SpanAnswer(**s) for s in group] for group in source["proposals"]]
            options = policy.shortlist(question, [docs[i] for i in ids], rank["rrf"], proposed, old, fitted["ranker"])
            prompt = policy.make_prompt(question, options, docs)
            baseline = verdict(select_answer(question, old, [], "deberta", -2))
            # Gold is consulted after generating the prompt, strictly for oracle/paired diagnostics.
            positive = not c["impossible"]
            ceiling += positive and any(tr.grade(c, verdict(s), docs) for s in options)
            sizes.append(len(options))
            prompt_lengths.append(len(prompt))
            doc_counts.append(len({s.source_id for s in options}))
            rows.append((c, options, prompt, baseline))
        groups[name] = docs, rows
        audit[name] = {
            "question_count": len(rows), "positive_count": sum(not c["impossible"] for c in cases),
            "shown_exact_positive_ceiling": ceiling, "shown_counts": [min(sizes), max(sizes)],
            "distinct_documents_min_median_max": [min(doc_counts), statistics.median(doc_counts), max(doc_counts)],
            "prompt_characters_min_median_max": [min(prompt_lengths), statistics.median(prompt_lengths), max(prompt_lengths)],
            "prompt_and_source_coordinates_sha256": sha_text(json.dumps([
                [c["id"], sha_text(prompt), [asdict(s) for s in opts]] for c, opts, prompt, _ in rows
            ], ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
        }
    return groups, audit


def summary(results):
    return {name: {"errors": sum(p["status"] == "error" for _, p, _ in cases),
                   "metrics": {kind: metric([ok for c, _, ok in cases if c["impossible"] == impossible])
                               for kind, impossible in (("positive", False), ("negative", True))}}
            for name, cases in results.items()}


def metric(values):
    passed, n = sum(values), len(values)
    return {"passed": passed, "n": n, "rate": passed / n, "wilson95": wilson(passed, n)}


def run_confirmation_cache(args):
    if not tr.load(args.output / "development-report.json")["adopt"]:
        raise ValueError("Unqualified development result; confirmation remains sealed")
    dst = args.output.parent / "gemma-options-confirmation-cache"
    dst.mkdir(exist_ok=False)
    previous = args.output.parent / "supervised"
    for k in ("features-protocol.json", "train.json", "calibrator.json"):
        shutil.copyfile(previous / k, dst / k)
    shutil.copyfile(args.output / "development-report.json", dst / "development-report.json")
    # Reuse the registered physical search + both pretrained reader passes on all new articles.
    collect(argparse.Namespace(**{**vars(args), "output": dst, "phase": "confirmation"}))


async def run(args):
    previous = args.output.parent / "supervised"
    protocol = {
        "model": MODEL, "origin": ORIGIN, "gguf_sha256": WEIGHTS, "code_sha256": source_hashes(),
        "calibrator_sha256": tr.file_sha256(previous / "calibrator.json"),
        "full_pool_ceiling_report_sha256": tr.file_sha256(previous / "development-report.json"),
        "development_source_sha256": tr.file_sha256(previous / "development-evidence.json"),
        "confirmation_corpus_registration_sha256": tr.file_sha256(args.output.parent / "cross-domain/panels.json"),
        "development_panels": {"squad": 48, "development": 32}, "confirmation_questions": 48,
        "temperature": 0, "max_tokens": 8, "system_prompt_sha256": sha_text(policy.SYSTEM),
        "decision": "Every development question receives one call. Strict answer+source+quote or native abstention. "
        "No declines in four development strata, one gain per domain, zero errors for fresh 24+24 confirmation.",
    }
    lock = args.output / "registration.json"
    if args.phase == "prepare":
        _, audit = material(args, "development")
        tr.dump(lock, {**protocol, "development_shortlist": audit})
        return
    registered = tr.load(lock)
    if {k: v for k, v in registered.items() if k != "development_shortlist"} != protocol:
        raise ValueError("Option review differs from registration")
    if args.phase == "confirmation-cache":
        run_confirmation_cache(args)
        return
    if args.phase == "confirmation" and not tr.load(args.output / "development-report.json")["adopt"]:
        raise ValueError("Confirmation not eligible")
    groups, audit = material(args, args.phase)
    if args.phase == "development" and registered["development_shortlist"] != audit:
        raise ValueError("Changed candidate options or prompts")
    from openai import AsyncOpenAI

    from app.lib.llm_client import OllamaLLMClient
    from scripts.rag_growth_local import local_http_client, verify_server

    stream_path = args.output / (args.phase + "-predictions.jsonl")
    results, baselines = {}, {}
    async with local_http_client(ORIGIN) as http:
        await verify_server(http, MODEL, args.model_file, WEIGHTS)
        model = OllamaLLMClient({"model": MODEL, "base_url": ORIGIN, "temperature": 0})
        model._client = AsyncOpenAI(base_url=ORIGIN + "/v1", api_key="not-needed", http_client=http,
                                    max_retries=0, timeout=120)
        with stream_path.open("x") as stream:
            for name, (docs, rows) in groups.items():
                results[name], baselines[name] = [], []
                for idx, (case, options, prompt, base) in enumerate(rows, 1):
                    selected = None
                    try:
                        selected, chosen = await policy.review(model, prompt, options)
                        pred = verdict(chosen)
                    except Exception as exc:
                        pred = {"status": "error", "error": type(exc).__name__ + ": " + str(exc)[:160]}
                    results[name].append((case, pred, tr.grade(case, pred, docs)))
                    baselines[name].append((case, base, tr.grade(case, base, docs)))
                    row = {"id": case["id"], "group": name, "selection": selected, "prompt_sha256": sha_text(prompt),
                           "options": [asdict(s) for s in options], "prediction": pred, "baseline": base}
                    stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                    stream.flush()
                    if idx % 8 == 0:
                        print(name, idx, flush=True)
    scores, old = summary(results), summary(baselines)
    decision = eligible(old, scores) if args.phase == "development" else None
    tr.dump(args.output / (args.phase + "-report.json"),
            {"baseline": old, "candidate": scores, "adopt": decision, "shown": audit,
             "predictions_sha256": tr.file_sha256(stream_path), "registration_sha256": tr.file_sha256(lock)})
    print(scores, decision, flush=True)


if __name__ == "__main__":
    os.environ.update(ENVIRONMENT="test", LANGFUSE_ENABLED="false", HF_HUB_OFFLINE="1")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "development", "confirmation-cache", "confirmation"))
    for k in ("output", "squad", "tydi", "reader", "multi", "embedding", "train"):
        parser.add_argument("--" + k, type=Path, required=k in ("output", "squad", "tydi"))
    parser.add_argument("--model-file", type=Path, default=MODEL_FILE)
    parser.add_argument("--device", default="mps", choices=("mps", "cpu"))
    asyncio.run(run(parser.parse_args()))
