"""Paired local development measurement for changing only Korean evidence sentence priority."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from app.lib.llm_client import OllamaLLMClient
from app.modules.core.agent.extractive_reader import (
    _CompletedResponse,
    refine_boundaries,
    supported_quantities,
)
from app.modules.core.generation.grounded_span import read_grounded_span
from app.modules.core.generation.korean_evidence_selection import KoreanEvidenceSelector
from scripts.rag_growth_ko_eval import ReaderCorpus, checked_span, grade, retrieve, write_new
from scripts.rag_growth_local import ROOT, file_sha256, local_http_client, verify_server

OUT = ROOT / "output/rag-evidence-selection/klue"
BASE = ROOT / "output/rag-growth-03"
WEIGHTS = Path.home() / "Models/moe/Qwen3.6-35B-A3B-UD-Q2_K_XL.gguf"
SHA = "96b9c0af5c77a4ecaabe3983175112b5ece763261c1ece12b2494b692a70dad7"
MODEL = "onerag-growth-qwen"
MODES = ("original", "lexical", "trained")
Row = dict[str, Any]


def load(p: Path) -> Any:
    raw = p.read_bytes()
    return [json.loads(line) for line in raw.splitlines()] if p.suffix == ".jsonl" else json.loads(raw)


def registration() -> Row:
    paths = [
        Path(__file__), ROOT / "scripts/rag_evidence_klue_train.py", OUT / "sentence-weights-balanced.json",
        OUT / "train-development-balanced.json", ROOT / "app/modules/core/generation/korean_evidence_selection.py",
        ROOT / "app/modules/core/generation/grounded_span.py", ROOT / "app/modules/core/agent/extractive_reader.py",
        ROOT / "app/lib/llm_client.py", ROOT / "scripts/rag_growth_ko_eval.py", ROOT / "scripts/rag_growth_local.py",
        BASE / "panels/reservation.json", BASE / "qwen/rescue-dev.json",
        BASE / "qwen/qwen-single-dev.jsonl", BASE / "ko-alt/mps-fp32/dev-spans.jsonl",
        BASE / "qwen/sufficiency-metal.jsonl", BASE / "qwen/prior-comparison-plan.json",
    ]
    return {"modes": list(MODES), "model_sha256": SHA, "endpoint": "http://127.0.0.1:18759", "model": MODEL,
            "policy": "Identical first retrieved article, source/clause ordering, grounded decoder, boundary "
                      "correction, sufficiency>0, rescue margin>4 and question quantity validation. Change only the "
                      "question-specific source sentence hints. Each request has one completed-response generation.",
            "measurement": "Run the established 24 and its remaining 56, using the same inputs and all three arms. "
                           "Pick the candidate with greatest min(strict positive, strict negative) then total "
                           "correct, fewer errors, lexical on exact tie. Record the frozen candidate on a separately "
                           "reserved unseen cohort even if it does not beat the incumbent. Never pool cohorts.",
            "files": {str(p.relative_to(ROOT)): file_sha256(p) for p in paths}}


def apply_rescue(first: Row, proposal: Row, sufficient: float, question: str) -> Row:
    if first["status"] == "answered":
        return refine_boundaries(first, proposal)
    if (first["status"] == "abstained" and sufficient > 0 and proposal["score"] > 4
            and supported_quantities(question, proposal["quote"])):
        return {**first, **proposal, "status": "answered"}
    return first


def context() -> tuple[list[Row], list[Row], dict[str, tuple[Row, float, Row]]]:
    manifest = load(BASE / "panels/reservation.json")
    def part(name: str) -> list[Row]:
        filename = "dev." + name + ".json"
        p = BASE / "panels" / filename
        if file_sha256(p) != manifest["files"][filename]:
            raise ValueError("Development panel changed")
        return list(load(p))
    qs, docs = part("questions"), part("corpus")
    corpus = ReaderCorpus(docs)
    raw = {r["id"]: r for r in load(BASE / "qwen/qwen-single-dev.jsonl")}
    prior = {r["id"]: r for r in load(BASE / "qwen/rescue-dev.json")["rows"]}
    span = {r["id"]: r for r in load(BASE / "ko-alt/mps-fp32/dev-spans.jsonl")}
    support = {r["id"]: r for r in load(BASE / "qwen/sufficiency-metal.jsonl")}
    result = {}
    for case in qs:
        key = case["id"]
        doc, = retrieve(corpus, case["question"], 1)
        proposal, strength = span[key]["spans"][0], support[key]["scores"][0]
        if (doc["id"] != proposal["source_id"] or doc["id"] != support[key]["ids"][0]
                or [doc["id"]] != prior[key]["retrieved"] or raw[key]["retrieved"] != prior[key]["retrieved"]):
            raise ValueError("Original passage or cached verifier differs")
        verified = apply_rescue(raw[key], proposal, strength, case["question"])
        if any(verified.get(k) != prior[key].get(k) for k in (
            "answer", "source_id", "status", "start", "end", "quote_start", "quote_end", "quote")):
            raise ValueError("Cached correction does not exactly reconstruct prior product behavior")
        result[key] = (doc, strength, proposal)
    return qs, docs, result


async def measure(mode: str, stage: str) -> None:
    from openai import AsyncOpenAI

    reg = registration()
    if load(OUT / "development-registration.json") != reg:
        raise ValueError("Development registration differs")
    arm = OUT / mode
    if (arm / f"{stage}.json").exists():
        raise ValueError("Stage already measured")
    qs, docs, caches = context()
    screened = set(load(BASE / "qwen/prior-comparison-plan.json")["ids"])
    cases = [q for q in qs if (q["id"] in screened) == (stage == "screen")]
    reader = None if mode == "original" else KoreanEvidenceSelector(mode, OUT / "sentence-weights-balanced.json")
    by_id = {d["id"]: d["content"] for d in docs}
    origin = reg["endpoint"]
    async with local_http_client(origin) as client:
        await verify_server(client, MODEL, WEIGHTS, SHA)
        capture: Row = {}
        async def observe(response: Any) -> None:
            if response.request.url.path.endswith("/chat/completions"):
                capture["calls"] += 1
                capture["prompt_sha256"] = hashlib.sha256(response.request.content).hexdigest()
                await response.aread()
                if response.is_success:
                    data = response.json()
                    choice, = data["choices"]
                    capture.update(raw=choice["message"].get("content"), finish=choice["finish_reason"],
                                   usage=data.get("usage"))
        client.event_hooks["response"].append(observe)
        sdk = OllamaLLMClient({"model": MODEL, "base_url": origin, "timeout": 120})
        sdk._client = AsyncOpenAI(base_url=origin+"/v1", api_key="not-needed", http_client=client, max_retries=0)
        model = _CompletedResponse(sdk)
        rows = []
        for n, case in enumerate(cases, 1):
            key, question = case["id"], case["question"]
            path = arm / (stage + "-rows") / (key + ".json")
            if path.exists():
                cached = load(path)
                if cached["id"] != key or cached["registration"] != file_sha256(OUT / "development-registration.json"):
                    raise ValueError("Cached question has different registration")
                rows.append(cached)
                continue
            doc, strength, proposal = caches[key]
            start = time.monotonic()
            capture.clear()
            capture["calls"] = 0
            first: Row = {"id": key, "retrieved": [doc["id"]]}
            try:
                predicted = await (reader.read(model, question, [doc]) if reader
                                   else read_grounded_span(model, question, [doc]))
                first.update({"status": "answered", **predicted} if predicted else {"status": "abstained"})
                row = apply_rescue(first, proposal, strength, question)
                if row["status"] == "answered" and not checked_span(row, by_id):
                    raise ValueError("Final citation offsets differ from retrieved source")
            except Exception as exc:
                row = {"id": key, "retrieved": [doc["id"]], "status": "error", "error": str(exc)[:280]}
            row.update(raw_status=first.get("status", "error"), request=dict(capture),
                       seconds=round(time.monotonic()-start, 3), registration=file_sha256(OUT / "development-registration.json"))
            write_new(path, row)
            rows.append(row)
            if n % 8 == 0:
                print(mode, stage, n, "/", len(cases), flush=True)
    if stage == "rest":
        rows += load(arm / "screen.json")["rows"]
    ids = {r["id"] for r in rows}
    ordered = {r["id"]: r for r in rows}
    rows = [ordered[q["id"]] for q in qs if q["id"] in ids]
    label_path = BASE / "panels/dev.labels.json"
    if file_sha256(label_path) != load(BASE / "panels/reservation.json")["files"][label_path.name]:
        raise ValueError("Different grader labels")
    labels = [r for r in load(label_path) if r["id"] in ids]
    score = grade(rows, labels, docs)
    write_new(arm / (stage + ".json"), {"rows": rows, **score, "stage": stage, "mode": mode})
    print(mode, stage, [(g, score["summary"][g]["correct"]) for g in ("answerable", "unanswerable")],
          score["summary"]["statuses"], flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("register", "screen", "rest"))
    parser.add_argument("--mode", choices=MODES, default="original")
    args = parser.parse_args()
    if args.stage == "register":
        write_new(OUT / "development-registration.json", registration())
    else:
        asyncio.run(measure(args.mode, args.stage))


if __name__ == "__main__":
    main()
