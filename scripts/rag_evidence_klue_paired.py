"""Measure two frozen Korean evidence policies on identical sealed questions and articles, without reading labels."""

from __future__ import annotations

import argparse
import asyncio
import gc
from pathlib import Path
from typing import Any

from app.lib.llm_client import OllamaLLMClient
from app.modules.core.agent.extractive_reader import _CompletedResponse
from app.modules.core.generation.grounded_span import read_grounded_span
from app.modules.core.generation.korean_evidence_routing import KoreanConditionalEvidenceSelector
from app.modules.core.generation.korean_evidence_selection import KoreanEvidenceSelector
from app.modules.core.generation.korean_span_reader import KoreanSpanReader
from app.modules.core.generation.passage_sufficiency import PassageSufficiency
from scripts.rag_evidence_klue_run import MODEL, OUT, SHA, WEIGHTS, apply_rescue, load
from scripts.rag_growth_ko_eval import ReaderCorpus, checked_span, retrieve, write_new
from scripts.rag_growth_local import ROOT, file_sha256, local_http_client, verify_server

Row = dict[str, Any]
FROZEN = OUT / "selected-policy.json"
BOUNDARY = ROOT / "models/rag-growth-03/ko-boundary"
SUPPORT = ROOT / "models/rag-growth-03/ko-sufficiency"
WEIGHTS_FILE = OUT / "sentence-weights-balanced.json"
AMENDMENT = OUT / "additional-selection.json"


def addition() -> Row:
    return {"registration": file_sha256(OUT / "development-registration.json"),
            "routing_calibration": file_sha256(OUT / "routing-calibration.json"),
            "rule": "Between lexical, trained and conditional compare minimum strict stratum correct, "
                    "then summed correct, then fewer errors, then lexical, conditional, trained.",
            "timing": "Original/lexical screens known before confidence calibration. All screens and incumbent full "
                      "known before this selection receipt. Neither candidate full result had been opened.",
            "selection_and_paired_runner": file_sha256(Path(__file__)),
            "excluded_window": "Externally owned windows candidate missed its preregistered development screen."}


def source_identity() -> Row:
    paths = [Path(__file__), ROOT / "scripts/rag_evidence_klue_run.py", WEIGHTS_FILE,
             ROOT / "scripts/rag_evidence_klue_routing.py", OUT / "routing-calibration.json",
             ROOT / "app/modules/core/generation/korean_evidence_routing.py",
             ROOT / "app/modules/core/generation/korean_evidence_selection.py",
             ROOT / "app/modules/core/generation/grounded_span.py",
             ROOT / "app/modules/core/generation/korean_span_reader.py",
             ROOT / "app/modules/core/generation/passage_sufficiency.py",
             ROOT / "app/modules/core/agent/extractive_reader.py",
             ROOT / "app/lib/evidence_sentences.py", ROOT / "app/lib/llm_client.py",
             ROOT / "scripts/rag_growth_ko_eval.py", ROOT / "scripts/rag_growth_local.py",
             ROOT / "app/modules/core/retrieval/bm25_engine/index.py",
             ROOT / "app/modules/core/retrieval/bm25_engine/tokenizer.py"]
    for model in (BOUNDARY, SUPPORT):
        paths.extend(sorted(p for p in model.iterdir() if p.is_file() and p.name != "README.md"))
    return {"source_and_encoder_sha256": {str(p.relative_to(ROOT)): file_sha256(p) for p in paths},
            "gguf_sha256": SHA, "gguf_alias": MODEL, "device": "mps", "top_k": 1,
            "sufficiency_cutoff": 0.0, "rescue_margin": 4.0, "max_tokens": 100, "temperature": 0}


def select() -> None:
    if load(AMENDMENT) != addition():
        raise ValueError("Additional candidate selection differs from preregistration")
    registration = OUT / "development-registration.json"
    values = {}
    for name in ("original", "lexical", "trained"):
        path = OUT / name / "rest.json"
        value = load(path)
        if len(value["rows"]) != 80 or any(r["registration"] != file_sha256(registration) for r in value["rows"]):
            raise ValueError("Development predictions have different registration")
        summary = value["summary"]
        values[name] = {"positive": summary["answerable"]["correct"], "negative": summary["unanswerable"]["correct"],
                        "errors": summary["statuses"].get("error", 0), "dev_sha256": file_sha256(path)}
    routed = OUT / "routing-rest.json"
    summary = load(routed)["summary"]
    values["conditional"] = {"positive": summary["answerable"]["correct"], "negative": summary["unanswerable"]["correct"],
                             "errors": summary["statuses"].get("error", 0), "dev_sha256": file_sha256(routed)}
    def objective(name: str) -> tuple[int, int, int, int]:
        p = values[name]
        return (min(p["positive"], p["negative"]), p["positive"] + p["negative"], -p["errors"],
                {"lexical": 2, "conditional": 1, "trained": 0}[name])
    selected = max(("lexical", "trained", "conditional"), key=objective)
    identity = source_identity()
    write_new(OUT / "control-policy.json", {"mode": "original", "identity": identity,
                                           "development_sha256": values["original"]["dev_sha256"]})
    write_new(FROZEN, {"selected": selected, "development": values, "identity": identity,
                       "additional_selection_sha256": file_sha256(AMENDMENT),
                       "selection_registration_sha256": file_sha256(registration)})


def prepare(output: Path, qs: list[Row], docs: list[Row]) -> dict[str, Row]:
    import torch

    torch.set_num_threads(2)
    corpus = ReaderCorpus(docs)
    selected = {q["id"]: retrieve(corpus, q["question"], 1)[0] for q in qs}
    del corpus
    cache = output / "encoders.json"
    if cache.exists():
        records = load(cache)
        if list(records) != sorted(selected) or any(r["doc"] != selected[q]["id"] for q, r in records.items()):
            raise ValueError("Saved passages differ from the same immutable corpus")
        return dict(records)
    records = {key: {"doc": doc["id"]} for key, doc in selected.items()}
    # Run each existing model once per unique question/passage and share identical results between the two arms.
    for purpose in ("support", "boundary"):
        encoder: Any = (PassageSufficiency(SUPPORT, "mps") if purpose == "support"
                        else KoreanSpanReader(BOUNDARY, device="mps"))
        for q in qs:
            row = records[q["id"]]
            doc = selected[q["id"]]
            try:
                if purpose == "support":
                    row["support"] = encoder.scores(q["question"], [doc])[0]
                else:
                    row["proposal"] = vars(encoder.predict_spans(q["question"], [doc])[0])
            except Exception as exc:
                row[purpose + "_error"] = f"{type(exc).__name__}: {exc}"
        del encoder
        gc.collect()
        torch.mps.empty_cache()
    write_new(cache, records)
    return records


async def measure(questions_path: Path, corpus_path: Path, output: Path, frozen_sha: str, *, cache_only: bool) -> None:
    from openai import AsyncOpenAI

    if file_sha256(FROZEN) != frozen_sha or load(FROZEN)["identity"] != source_identity():
        raise ValueError("Frozen selection or model sources differ")
    selected = load(FROZEN)["selected"]
    qs, docs = load(questions_path), load(corpus_path)
    if (not qs or len(qs) != len({r["id"] for r in qs}) or any(set(r) != {"id", "question"} for r in qs)
            or len(docs) != len({r["id"] for r in docs})):
        raise ValueError("Unexpected unlabeled confirmation inputs")
    manifest = {"freeze": frozen_sha, "questions": file_sha256(questions_path), "corpus": file_sha256(corpus_path),
                "n": len(qs), "mode": selected}
    receipt = output / "started.json"
    if receipt.exists():
        if load(receipt) != manifest:
            raise ValueError("Previous run used different inputs")
    else:
        write_new(receipt, manifest)
    encoder_path = output / "encoders.json"
    encoder_receipt = output / "encoders-receipt.json"
    if cache_only:
        cached = prepare(output, qs, docs)
        if len(cached) != len(qs):
            raise ValueError("Incomplete encoder cache")
        write_new(encoder_receipt, {"encoders": file_sha256(encoder_path), "start": file_sha256(receipt)})
        return
    saved = load(encoder_receipt)
    if saved != {"encoders": file_sha256(encoder_path), "start": file_sha256(receipt)}:
        raise ValueError("Independent encoders or sealed inputs differ from the recorded preparation")
    cached = load(encoder_path)
    doc_by_id = {d["id"]: d for d in docs}
    bodies = {d["id"]: d["content"] for d in docs}
    reader = (KoreanConditionalEvidenceSelector(WEIGHTS_FILE, OUT / "routing-calibration.json")
              if selected == "conditional" else KoreanEvidenceSelector(selected, WEIGHTS_FILE))
    origin = "http://127.0.0.1:18759"
    async with local_http_client(origin) as client:
        await verify_server(client, MODEL, WEIGHTS, SHA)
        sdk = OllamaLLMClient({"model": MODEL, "base_url": origin, "timeout": 120})
        sdk._client = AsyncOpenAI(base_url=origin+"/v1", api_key="not-needed", http_client=client, max_retries=0)
        model = _CompletedResponse(sdk)
        outputs: dict[str, list[Row]] = {"control": [], "candidate": []}
        for i, q in enumerate(qs):
            cache = cached[q["id"]]
            doc = doc_by_id[cache["doc"]]
            # Alternate the first arm between questions to avoid correlating position with processing time.
            for arm in (("control", "candidate") if i % 2 == 0 else ("candidate", "control")):
                path = output / "rows" / f"{i:04d}-{arm}.json"
                if path.exists():
                    row = load(path)
                    if row["id"] != q["id"] or row["retrieved"] != [doc["id"]]:
                        raise ValueError("Saved output differs from registered question/passage")
                else:
                    row = {"id": q["id"], "retrieved": [doc["id"]], "attempts": 1}
                    try:
                        span = await (reader.read(model, q["question"], [doc]) if arm == "candidate"
                                      else read_grounded_span(model, q["question"], [doc]))
                        first = {**row, **({"status": "answered", **span} if span else {"status": "abstained"})}
                        # The original product consults sufficiency only on an explicit first-pass refusal.
                        if span is None and "support_error" in cache:
                            raise ValueError(cache["support_error"])
                        if (span is not None or cache.get("support", 0) > 0) and "boundary_error" in cache:
                            raise ValueError(cache["boundary_error"])
                        row = apply_rescue(first, cache.get("proposal", {}), cache.get("support", 0), q["question"])
                        if row["status"] == "answered" and not checked_span(row, bodies):
                            raise ValueError("Unverified new passage or quote")
                    except Exception as exc:
                        row = {"id": q["id"], "retrieved": [doc["id"]], "status": "error",
                               "attempts": 1, "error": f"{type(exc).__name__}: {exc}"[:300]}
                    write_new(path, row)
                outputs[arm].append(row)
            if (i+1) % 8 == 0:
                print("paired", i+1, "/", len(qs), flush=True)
    for arm, rows in outputs.items():
        write_new(output / f"{arm}.json", {"rows": rows, "arm": arm, **manifest})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("register-addition", "select", "prepare", "measure"))
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--freeze-sha")
    args = parser.parse_args()
    if args.stage == "register-addition":
        if any((OUT / mode / "rest.json").exists() for mode in ("lexical", "trained")):
            raise ValueError("Candidate full result is already available")
        write_new(AMENDMENT, addition())
    elif args.stage == "select":
        select()
    elif args.questions and args.corpus and args.output and args.freeze_sha:
        asyncio.run(measure(args.questions, args.corpus, args.output, args.freeze_sha, cache_only=args.stage == "prepare"))
    else:
        parser.error("Unlabeled input paths, output and frozen SHA are required")


if __name__ == "__main__":
    main()
