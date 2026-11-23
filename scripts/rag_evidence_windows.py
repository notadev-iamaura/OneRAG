"""Measure local Qwen with its original verifier selecting windows of the same retrieved article."""

import argparse
import asyncio
import hashlib
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.lib.llm_client import OllamaLLMClient
from app.modules.core.agent.extractive_reader import _CompletedResponse
from app.modules.core.generation.korean_sentence_windows import (
    read_windows,
    select_anchored_windows,
    select_windows,
)
from app.modules.core.generation.passage_sufficiency import PassageSufficiency
from scripts import rag_evidence_klue_run as klue
from scripts.rag_growth_ko_eval import checked_span, grade, write_new
from scripts.rag_growth_local import ROOT, file_sha256, local_http_client, verify_server

PROFILE = klue.BASE / "ko/rescue-profile.json"
DEV_CONTEXT = ["qwen/rescue-dev.json", "qwen/qwen-single-dev.jsonl", "ko-alt/mps-fp32/dev-spans.jsonl",
               "qwen/sufficiency-metal.jsonl"]


def recorded_context():
    manifest = klue.load(klue.BASE / "panels/reservation.json")["files"]
    panels = klue.BASE / "panels"
    for filename in ("dev.questions.json", "dev.corpus.json"):
        if file_sha256(panels / filename) != manifest[filename]:
            raise ValueError("Development panel has changed")
    qs, docs = (klue.load(panels / name) for name in ("dev.questions.json", "dev.corpus.json"))
    by_id = {d["id"]: d for d in docs}
    states, raw, spans, scores = [klue.load(klue.BASE / name) for name in DEV_CONTEXT]
    maps = [{r["id"]: r for r in entries} for entries in (states["rows"], raw, spans, scores)]
    contexts = {}
    for q in qs:
        control, first, span, support = [rows[q["id"]] for rows in maps]
        source, = control["retrieved"]
        boundary = span["spans"][0]
        strength = support["scores"][0]
        if source != boundary["source_id"] or [source] != first["retrieved"] or source != support["ids"][0]:
            raise ValueError("Recorded retrieval and encoder traces disagree")
        measured = klue.apply_rescue(first, boundary, strength, q["question"])
        if any(measured.get(k) != control.get(k) for k in ("source_id", "answer", "start", "end", "status")):
            raise ValueError("Historical control is not reproducible")
        contexts[q["id"]] = (by_id[source], strength, boundary)
    return qs, docs, contexts


def registration(selector):
    paths = [Path(__file__), ROOT / "scripts/rag_evidence_klue_run.py",
             ROOT / "app/modules/core/generation/korean_sentence_windows.py",
             ROOT / "app/modules/core/generation/korean_adjudication.py", ROOT / "app/modules/core/generation/grounded_span.py",
             ROOT / "app/modules/core/generation/passage_sufficiency.py", PROFILE,
             klue.BASE / "panels/reservation.json", klue.BASE / "qwen/prior-comparison-plan.json",
             *(klue.BASE / name for name in DEV_CONTEXT)]
    verifier = Path(klue.load(PROFILE)["reader"]["sufficiency_model_dir"])
    expected = klue.load(klue.BASE / "gemma-profile/registration-v2.json")["sufficiency"]
    if any(file_sha256(verifier / name) != value for name, value in expected.items()):
        raise ValueError("The frozen verifier has changed")
    return {"files": {str(p.relative_to(ROOT)): file_sha256(p) for p in paths}, "gguf_sha256": klue.SHA,
            "verifier_sha256": expected, "search": "Same established top-1 BM25 and same 3,600 source characters.",
            "selector": selector,
            "selection": ("Score adjacent sentence pairs with existing relevance encoder on CPU." if selector == "verified" else
                          "Use the existing boundary location and question-term coverage to select evidence pairs; "
                          "keep the full original article when its existing relevance score is not positive."),
            "decision": "Screen on the historical 12+12. Continue to the other 56 if neither metric falls below baseline by more than one. "
                        "Choose a confirmed candidate by full-development metrics, not the screen or any held-out result."}


def prepare(selector, out):
    spec = registration(selector)
    dest = out / "development-registration.json"
    if dest.exists():
        if klue.load(dest) != spec:
            raise ValueError("Window selection has changed")
    else:
        write_new(dest, spec)
    if selector == "verified":
        import torch

        torch.set_num_threads(2)
        reader = PassageSufficiency(Path(klue.load(PROFILE)["reader"]["sufficiency_model_dir"]), "cpu")
    qs, _, contexts = recorded_context()
    shortlist = set(klue.load(klue.BASE / "qwen/prior-comparison-plan.json")["ids"])
    for i, q in enumerate(sorted(qs, key=lambda r: r["id"] not in shortlist), 1):
        doc, sufficient, boundary = contexts[q["id"]]
        path = out / "windows" / (q["id"] + ".json")
        if not path.exists():
            windows = (select_windows(q["question"], doc, reader.scores) if selector == "verified"
                       else select_anchored_windows(q["question"], doc, boundary, sufficient))
            write_new(path, {"id": q["id"], "source": doc["id"], "windows": windows,
                             "registration": file_sha256(dest)})
        if i % 8 == 0:
            print("scored", i, flush=True)


async def measure(stage, selector, out):
    from openai import AsyncOpenAI

    plan_path = out / "development-registration.json"
    if registration(selector) != klue.load(plan_path):
        raise ValueError("Unregistered selection rule")
    qs, docs, contexts = recorded_context()
    known = set(klue.load(klue.BASE / "qwen/prior-comparison-plan.json")["ids"])
    cases = [q for q in qs if (q["id"] in known) == (stage == "screen")]
    if stage == "rest" and not klue.load(out / "screen.json")["eligible"]:
        raise ValueError("Window screen did not qualify for full development")
    source = {d["id"]: d["content"] for d in docs}
    origin = "http://127.0.0.1:18759"
    registration_sha = file_sha256(plan_path)
    async with local_http_client(origin) as client:
        await verify_server(client, klue.MODEL, klue.WEIGHTS, klue.SHA)
        llm = OllamaLLMClient({"model": klue.MODEL, "base_url": origin, "timeout": 120})
        llm._client = AsyncOpenAI(base_url=origin + "/v1", api_key="local", http_client=client, max_retries=0)
        trace: dict = {}

        async def observe(response):
            if response.request.url.path.endswith("/chat/completions"):
                trace["calls"] += 1
                trace["prompt_sha256"] = hashlib.sha256(response.request.content).hexdigest()
                await response.aread()
                if response.status_code == 200:
                    data = response.json()
                    choice, = data["choices"]
                    trace.update(text=choice["message"].get("content"), finish=choice["finish_reason"], usage=data.get("usage"))

        client.event_hooks["response"].append(observe)
        for i, q in enumerate(cases, 1):
            qid = q["id"]
            path = out / "responses" / (qid + ".json")
            if path.exists():
                if klue.load(path)["registration"] != registration_sha:
                    raise ValueError("Cached answer belongs to another selection rule")
                continue
            doc, support, boundary = contexts[qid]
            proposal = klue.load(out / "windows" / (qid + ".json"))
            if proposal["source"] != doc["id"] or proposal["registration"] != registration_sha:
                raise ValueError("Retrieved article or selection rule has changed")
            trace.clear()
            trace["calls"] = 0
            row = {"id": qid, "retrieved": [doc["id"]]}
            try:
                answer = await read_windows(_CompletedResponse(llm), q["question"], doc, proposal["windows"])
                row.update({"status": "answered", **answer} if answer is not None else {"status": "abstained"})
                row = klue.apply_rescue(row, boundary, support, q["question"])
                if row["status"] == "answered" and not checked_span(row, source):
                    raise ValueError("Invalid citation")
            except Exception as exc:
                row = {"id": qid, "retrieved": [doc["id"]], "status": "error", "error": str(exc)[:240]}
            write_new(path, {**row, "request": dict(trace), "registration": registration_sha})
            if i % 8 == 0:
                print("measured", stage, i, flush=True)
    ids = {q["id"] for q in (cases if stage == "screen" else qs)}
    rows = [klue.load(out / "responses" / (q["id"] + ".json")) for q in qs if q["id"] in ids]
    labels_path = klue.BASE / "panels/dev.labels.json"
    if file_sha256(labels_path) != klue.load(klue.BASE / "panels/reservation.json")["files"][labels_path.name]:
        raise ValueError("Reference labels changed")
    labels = [r for r in klue.load(labels_path) if r["id"] in ids]
    actual = grade(rows, labels, docs)
    baseline = grade([r for r in klue.load(klue.BASE / "qwen/rescue-dev.json")["rows"] if r["id"] in ids],
                     labels, docs)["summary"]
    eligible = all(actual["summary"][g]["correct"] >= baseline[g]["correct"] - 1 for g in ("answerable", "unanswerable"))
    write_new(out / (stage + ".json"), {**actual, "baseline": baseline, "eligible": eligible, "rows": rows})
    print(stage, eligible, *(actual["summary"][g]["correct"] for g in ("answerable", "unanswerable")), flush=True)


if __name__ == "__main__":
    os.environ.update(ENVIRONMENT="test", LANGFUSE_ENABLED="false", HF_HUB_OFFLINE="1", PYTHON_DOTENV_DISABLED="1")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "screen", "rest"))
    parser.add_argument("--selector", required=True, choices=("anchored", "verified"))
    args = parser.parse_args()
    folder = ROOT / "output/rag-evidence-selection" / ("window-" + args.selector)
    if args.stage == "prepare":
        prepare(args.selector, folder)
    else:
        asyncio.run(measure(args.stage, args.selector, folder))
