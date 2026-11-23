"""Compare a development-selected Korean evidence rule with the original reader on a locked new panel."""

import argparse
import importlib
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))

from app.modules.core.generation import tydi_evidence_context as ctx
from app.modules.core.generation import tydi_evidence_selection as source
from scripts import rag_evidence_replication_gate as gate
from scripts import rag_evidence_tydi as exp
from scripts import rag_evidence_tydi_cache as cache
from scripts import rag_evidence_tydi_windows as windows
from scripts.rag_growth_ko_eval import write_new
from scripts.rag_growth_local import file_sha256

PANEL = "tydi-replication"
PANELS = cache.OUT.parent / "panels"
CONTROL = [cache.OLD / "run/selected.json", ROOT / "app/modules/core/generation/korean_passage_selection.py"]


def frozen_sources():
    primary = cache.OUT / "v3/registration.json"
    pins = cache.read(primary)["code_sha256"]
    common = [Path(__file__), Path(ctx.__file__), Path(windows.__file__), primary, cache.OLD / "run/policy-registration.json"]
    for file, key in pins.items():
        if file_sha256(ROOT / file) != key:
            raise ValueError("Original QA, retrieval, scoring or selection source changed before replication")
        common.append(ROOT / file)
    return common


def reserve(output, selector, proofs):
    if not proofs or not selector.is_file():
        raise ValueError("A development-selected policy module and proof are required")
    code = selector.resolve()
    if code.parent != ROOT / "app/modules/core/generation" or not code.name.startswith("tydi_evidence_"):
        raise ValueError("Expected a Korean evidence-selection product module")
    if not callable(getattr(importlib.import_module("app.modules.core.generation." + code.stem), "decide", None)):
        raise ValueError("Selected policy must implement decide(case, window_readings)")
    info = {"selector": str(code.relative_to(ROOT)), "candidate_sources": gate.primary.sources([code, *proofs]),
            "start_before_corpus_or_question_inference": True, "rule": "All 32 new queries, identical true top-eight search. "
            "No independent labels before both original rows are written. No retry or candidate replacement."}
    registration = output / "selection.json"
    common = frozen_sources()
    write_new(registration, info)
    gate.start(PANELS, PANEL, CONTROL, [code, *proofs], [*common, registration],
               output / "final.baseline.json", output / "final.candidate.json")


def checked_lock(output):
    cfg = cache.read(output / "selection.json")
    startfile, scorefile = gate.primary.paths(PANELS, PANEL)
    lock = cache.read(startfile)
    if any(lock[k] != v for k, v in gate.identity(PANELS, PANEL).items()):
        raise ValueError("Registered replication or independent scorer changed")
    gate.check_sources(lock)
    if (cfg["candidate_sources"] != lock["candidate_sources"]
            or gate.primary.sources(CONTROL) != lock["control_sources"]
            or gate.primary.sources([*frozen_sources(), output / "selection.json"]) != lock["common_sources"]
            or lock["control_rows"] != str((output / "final.baseline.json").resolve())
            or lock["candidate_rows"] != str((output / "final.candidate.json").resolve())):
        raise ValueError("Source or output identity does not match the independent lock")
    return cfg, lock, scorefile


def predict(case, raw, decision):
    result = {"id": case.question["id"], "retrieved": [d["id"] for d in case.docs]}
    try:
        if case.error or raw.get("error"):
            raise ValueError(case.error or raw["error"])
        span = decision(case, raw["windows"])
        if span is None:
            result.update(status="abstained")
        else:
            if not 0 <= span.document_index < len(case.docs):
                raise ValueError("Selected source is outside the fixed retrieval pool")
            source.valid(case.docs[span.document_index], span)
            result.update(status="answered", **asdict(span))
    except Exception as exc:
        result.update(status="error", error=f"{type(exc).__name__}: {exc}"[:200])
    return result


def run(output, audit):
    cfg, lock, scorefile = checked_lock(output)
    panel = PANELS / PANEL
    if audit:
        if not scorefile.exists():
            raise ValueError("Wait for independent grading before opening annotations")
        _, cases, part = exp.load_cached("final", panel, output)
        gold = {r["id"]: r for r in part("labels")}
        raw = exp.lines(output / "final.window-readings.jsonl")
        expanded = []
        for case in cases:
            w = raw[case.question["id"]]
            if "error" in w:
                expanded.append(replace(case, error=w["error"]))
                continue
            limits = [ctx.ContextWindow(g["document_index"], g["start"], g["end"]) for g in w["windows"]]
            gs = [[exp.SpanAnswer(**s) for s in g["readings"]] for g in w["windows"]]
            expanded.append(replace(case, candidates=ctx.expand(case.docs, case.candidates, limits, gs)))
        write_new(output / "final.ceiling.json", {"shared_score_sha256": file_sha256(scorefile),
                  "full_passage": exp.diagnostics(cases, gold), "with_contexts": exp.diagnostics(expanded, gold)})
        return
    if scorefile.exists():
        raise ValueError("Replication was already scored")
    # The common collector checks input and model hashes before genuine top-eight retrieval.
    cache.collect("final", panel, output)
    _, cases, _ = exp.load_cached("final", panel, output)
    if len(cases) != 32:
        raise ValueError("Expected all 32 new questions")
    write_new(Path(lock["control_rows"]), exp.predictions(cases, "baseline", None))
    decision = importlib.import_module("app.modules.core.generation." + Path(cfg["selector"]).stem).decide
    model = windows.reader()
    rows = []
    with (output / "final.window-readings.jsonl").open("x") as handle:
        for i, case in enumerate(cases, 1):
            raw = {"id": case.question["id"]}
            try:
                raw["windows"], _ = windows.read_case(model, case)
            except Exception as exc:
                raw["error"] = f"{type(exc).__name__}: {exc}"[:200]
            handle.write(json.dumps(raw, ensure_ascii=False) + "\n")
            handle.flush()
            rows.append(predict(case, raw, decision))
            if i % 8 == 0:
                print("replication window QA", i, flush=True)
    write_new(Path(lock["candidate_rows"]), rows)
    print("Ready for independent score:", len(rows), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phase", choices=("start", "run", "audit"))
    ap.add_argument("--output", type=Path, default=cache.OUT / "replication")
    ap.add_argument("--selector-file", type=Path)
    ap.add_argument("--candidate-proof", type=Path, action="append", default=[])
    args = ap.parse_args()
    if args.phase == "start":
        if args.selector_file is None:
            ap.error("start requires --selector-file and --candidate-proof")
        reserve(args.output, args.selector_file, args.candidate_proof)
    else:
        run(args.output, audit=args.phase == "audit")
