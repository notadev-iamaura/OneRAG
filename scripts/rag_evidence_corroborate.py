"""Compare local source-span repairs on the original KLUE development predictions."""

from __future__ import annotations

from pathlib import Path

from app.modules.core.generation.korean_corroborated_evidence import (
    corroborate_misplaced_citation,
    select_supported_extent,
)
from scripts.rag_evidence_klue_run import BASE, OUT, load
from scripts.rag_evidence_windows import recorded_context
from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import ROOT, file_sha256

TARGET = OUT.parent / "corroborated"
MODES = ("corroborate", "extent", "both")


def select(mode, question, doc, support, boundary, row, generated, raw):
    if (row["status"] == "error" and mode in ("corroborate", "both")
            and row.get("error", "").removeprefix("ValueError: ") == "Answer is absent from the cited sentence"):
        # Reconcile an incorrect existing sentence attribution only after the model returned an otherwise complete answer.
        span = corroborate_misplaced_citation(doc, raw, boundary, support)
        if span is not None:
            return {"id": row["id"], "retrieved": row["retrieved"], "status": "answered", **span}
    if row["status"] == "answered" and mode in ("extent", "both"):
        return select_supported_extent(question, doc, row, generated, boundary)
    return row


def development():
    paths = [Path(__file__), ROOT / "app/modules/core/generation/korean_corroborated_evidence.py",
             ROOT / "app/modules/core/generation/korean_evidence_selection.py", ROOT / "app/modules/core/generation/grounded_span.py",
             OUT / "original/rest.json", BASE / "panels/reservation.json", BASE / "qwen/qwen-single-dev.jsonl"]
    reg = {"files": {str(p.relative_to(ROOT)): file_sha256(p) for p in paths},
           "design": "Developed after inspecting the historical development failures. Compare original, independently "
                     "corroborated citations, typed extents, and their combination. No new model calls or refusal changes. "
                     "Freeze policy before independent replication. Prioritize strict correct, then fewer changes."}
    write_new(TARGET / "development-registration.json", reg)
    qs, docs, context = recorded_context()
    raw = {r["id"]: r for r in load(BASE / "qwen/qwen-single-dev.jsonl")}
    original = load(OUT / "original/rest.json")
    labels = load(BASE / "panels/dev.labels.json")
    if file_sha256(BASE / "panels/dev.labels.json") != load(BASE / "panels/reservation.json")["files"]["dev.labels.json"]:
        raise ValueError("Development labels changed")
    ref = {r["id"]: r for r in original["rows"]}
    measures = {}
    for mode in MODES:
        predictions = []
        for q in qs:
            k = q["id"]
            row, first = ref[k], raw[k]
            doc, support, boundary = context[k]
            request = row["request"]
            complete_text = request.get("raw") if request.get("finish") == "stop" and request.get("calls") == 1 else None
            generated = first if first["status"] == "answered" else None
            predictions.append(select(mode, q["question"], doc, support, boundary, row, generated, complete_text))
        scores = grade(predictions, labels, docs)
        outcome = {o["id"]: o["correct"] for o in original["outcomes"]}
        flips = [o for o in scores["outcomes"] if o["correct"] != outcome[o["id"]]]
        changed = sum(any(r.get(f) != ref[r["id"]].get(f) for f in ("answer", "start", "end", "status")) for r in predictions)
        measures[mode] = {"correct": [scores["summary"][g]["correct"] for g in ("answerable", "unanswerable")],
                          "changes": changed, "flips": flips}
        write_new(TARGET / (mode + "-development.json"), {"rows": predictions, **scores, "flips": flips})
    best = max(MODES, key=lambda m: (min(measures[m]["correct"]), sum(measures[m]["correct"]), -measures[m]["changes"]))
    write_new(TARGET / "selected.json", {"selection": best, "development": measures,
              "source_registration_sha256": file_sha256(TARGET / "development-registration.json")})
    print({mode: m["correct"] for mode, m in measures.items()}, "selected", best)


if __name__ == "__main__":
    development()
