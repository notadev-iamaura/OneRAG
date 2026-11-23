"""Prospective development-only check of same-model QA on short contiguous evidence windows."""

import argparse
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))

from app.modules.core.generation import tydi_evidence_context as ctx
from app.modules.core.generation.tydi_evidence_spans import KoreanEvidenceProposer
from scripts import rag_evidence_tydi as experiment
from scripts.rag_evidence_tydi_cache import OLD, OUT, READER, read
from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import file_sha256


def run(stage, primary, out):
    out.mkdir(parents=True, exist_ok=True)
    cfg = {
        "source_sha256": {f: file_sha256(ROOT / f) for f in (
            "scripts/rag_evidence_tydi_context.py", "app/modules/core/generation/tydi_evidence_context.py",
            "app/modules/core/generation/tydi_evidence_spans.py", "app/modules/core/generation/tydi_evidence_selection.py",
            "scripts/rag_evidence_tydi.py", "app/modules/core/generation/english_span_proposals.py")},
        "primary_registration_sha256": file_sha256(primary / "registration.json"),
        "dev_cache_sha256": file_sha256(primary / "dev.cache.json"),
        "gate": "Same selected primary mode, training-only weights, full-passage support and raw original "
                "QA threshold. Reread all questions and documents uniformly, no oracle. Report ceilings and decisions. "
                "Independent replication remains separately locked; this CLI only reads official-train development.",
        "windows": "Two anchors per source: local query-gram IDF and original reader maximum. Read the anchor "
                   "with the higher-scoring immediate neighbor. If both are the entire document, read the anchor. "
                   "Deduplicate intervals, skip single-sentence paragraphs. Keep six genuine hypotheses per window.",
    }
    lock = out / "registration.json"
    if stage == "register":
        write_new(lock, cfg)
        return
    if read(lock) != cfg:
        raise ValueError("Sentence-context policy changed")
    incumbent = read(primary / "selected.json")
    if (incumbent["ranker_sha256"] != file_sha256(primary / "ranker.json")
            or incumbent["registration_sha256"] != cfg["primary_registration_sha256"]):
        raise ValueError("Original trained policy must be selected and frozen first")
    import torch

    torch.set_num_threads(4)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    docs, cases, load_part = experiment.load_cached("dev", OLD / "panels", primary)
    started = {"primary_choice_sha256": file_sha256(primary / "selected.json"), "context_sha256": file_sha256(lock)}
    write_new(out / "dev.started.json", started)
    model = KoreanEvidenceProposer(READER, "cpu")
    fresh = []
    path = out / "dev.spans.jsonl"
    with path.open("x") as f:
        for i, case in enumerate(cases, 1):
            qid = case.question["id"]
            try:
                if case.error:
                    raise ValueError(case.error)
                win, expanded = ctx.reread(model, case.question["question"], case.docs, case.candidates)
                new = replace(case, candidates=expanded)
                raw = {"id": qid, "windows": [asdict(w) for w in win],
                       "candidates": [[asdict(s) for s in group] for group in expanded]}
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:200]
                new, raw = replace(case, error=error), {"id": qid, "error": error}
            fresh.append(new)
            f.write(json.dumps(raw, ensure_ascii=False) + "\n")
            f.flush()
            if i % 8 == 0:
                print("context reread", i, flush=True)
    del model
    labels = load_part("labels")
    gold = {label["id"]: label for label in labels}
    ranker = read(primary / "ranker.json")
    rows = experiment.predictions(fresh, incumbent["mode"], ranker)
    previous = experiment.predictions(cases, incumbent["mode"], ranker)
    write_new(out / "dev.candidate.json", rows)
    write_new(out / "dev.baseline.json", previous)
    report = {**started, "source_predictions_sha256": file_sha256(path),
              "incumbent": grade(previous, labels, docs), "candidate": grade(rows, labels, docs),
              "full_passages": experiment.diagnostics(cases, gold), "with_contexts": experiment.diagnostics(fresh, gold)}
    write_new(out / "dev.metrics.json", report)
    print(experiment.counts(report["incumbent"]), experiment.counts(report["candidate"]),
          report["full_passages"], report["with_contexts"], flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=("register", "dev"))
    p.add_argument("--primary", type=Path, default=OUT / "v3")
    p.add_argument("--output", type=Path, default=OUT / "sentence-context")
    args = p.parse_args()
    run(args.stage, args.primary, args.output)
