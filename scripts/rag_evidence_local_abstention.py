"""Test one fixed full-article plus local-evidence abstention policy on the original KLUE development set."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation import korean_adjudication, passage_sufficiency
from scripts import rag_evidence_klue_run as klue
from scripts import rag_evidence_windows as windows
from scripts.rag_growth_ko_eval import checked_span, grade, write_new
from scripts.rag_growth_local import file_sha256

OUT = klue.OUT.parent / "local-abstention"
POLICY = klue.OUT.parent / "coverage/development.json"
ORIGINAL = klue.OUT / "original/rest.json"
MODEL = klue.ROOT / "models/rag-growth-03/ko-sufficiency"
Row = dict[str, Any]


def registration() -> Row:
    original_model = klue.load(klue.BASE / "gemma-profile/registration-v2.json")["sufficiency"]
    if any(file_sha256(MODEL / f) != h for f,h in original_model.items()):
        raise ValueError("The local checkpoint differs from the registered original")
    files = [Path(__file__), Path(korean_adjudication.__file__), Path(passage_sufficiency.__file__), POLICY, ORIGINAL,
             Path(windows.__file__), klue.BASE / "panels/reservation.json", klue.BASE / "qwen/sufficiency-metal.jsonl",
             klue.ROOT / "scripts/rag_growth_ko_eval.py"]
    return {"files_sha256": {str(p.relative_to(klue.ROOT)): file_sha256(p) for p in files}, "model_sha256": original_model,
            "policy": "Only if the original and the coverage policy both answered and the existing full-document "
                      "relevance margin <=0, score the answer-containing sentence(s), previous+answer sentence(s), "
                      "and answer sentence(s)+next. Keep the exact title and original characters. Deduplicate identical "
                      "ranges at article boundaries. Abstain if all scores <=0. Inference/evidence failures are "
                      "errors. All other statuses and citations stay as measured.",
            "device": "cpu/fp32/2 torch threads/serial queries", "scope": "One fixed candidate; all 40+40 development",
            "success": "No lost answerable correct cases, strictly improved genuine abstention, no extra errors.",
            "heldout": "No access to questions, labels or responses in any confirmation panel."}


def ranges(doc: Row, row: Row) -> list[tuple[int, int]]:
    text = doc["content"]
    if not checked_span(row, {doc["id"]: text}):
        raise ValueError("The initial answer or citation is not an exact source interval")
    sentences = [(a, a+len(s)) for a,s in korean_adjudication._sentences(text)]
    left = next((i for i,(a,b) in enumerate(sentences) if a <= row["start"] < b), None)
    right = next((i for i,(a,b) in enumerate(sentences) if a < row["end"] <= b), None)
    if left is None or right is None or left > right:
        raise ValueError("The answer falls outside a sentence")
    groups = [(left,right), (max(0,left-1),right), (left,min(len(sentences)-1,right+1))]
    return list(dict.fromkeys((sentences[i][0], sentences[j][1]) for i,j in groups))


def decide(row: Row, old: Row, score: float, margins: list[float]) -> Row:
    if not math.isfinite(score):
        raise ValueError("Nonfinite document sufficiency")
    if row["status"] != "answered" or old["status"] != "answered" or score > 0:
        return row
    if not margins or not all(math.isfinite(v) for v in margins):
        raise ValueError("The local evidence check did not complete")
    if all(v <= 0 for v in margins):
        return {"id": row["id"], "retrieved": row["retrieved"], "status": "abstained"}
    return row


def run(phase: str) -> None:
    reg = OUT / "registration.json"
    if phase == "register":
        write_new(reg, registration())
        return
    if klue.load(reg) != registration():
        raise ValueError("The registered model, cutoff, or policy changed")
    qs, docs, state = windows.recorded_context()
    reference = {r["id"]: r for r in klue.load(POLICY)["rows"]}
    old = {r["id"]: r for r in klue.load(ORIGINAL)["rows"]}
    cases = [q for q in qs if reference[q["id"]]["status"] == old[q["id"]]["status"] == "answered"
             and state[q["id"]][1] <= 0]
    if not (len(qs) == len(reference) == len(old) == 80) or len(cases) != 5:
        raise ValueError("Registered development profile changed")
    cache = OUT / "local-scores.json"
    if phase == "measure":
        import torch
        torch.set_num_threads(2)
        model = passage_sufficiency.PassageSufficiency(MODEL, "cpu")
        records = {}
        for q in cases:
            key = q["id"]
            doc, full, _ = state[key]
            measured: Row = {"source_id": doc["id"], "full": full}
            try:
                intervals = ranges(doc, reference[key])
                views = [{**doc, "content": doc["content"][a:b]} for a,b in intervals]
                scores = model.scores(q["question"], views)
                if len(scores) != len(intervals) or not all(math.isfinite(v) for v in scores):
                    raise ValueError("Incomplete local window scoring")
                measured.update(ranges=intervals, margins=scores)
            except Exception as exc:
                measured["error"] = f"{type(exc).__name__}: {exc}"[:320]
            records[key] = measured
        write_new(cache, {"registration_sha256": file_sha256(reg), "rows": records, "dtype": str(next(model.model.parameters()).dtype),
                          "device": str(model.device), "torch": torch.__version__, "threads": torch.get_num_threads()})
        return
    measured = klue.load(cache)
    if measured["registration_sha256"] != file_sha256(reg) or set(measured["rows"]) != {q["id"] for q in cases}:
        raise ValueError("The measurement cache differs from the preregistration")
    labels = klue.BASE / "panels/dev.labels.json"
    if file_sha256(labels) != klue.load(klue.BASE / "panels/reservation.json")["files"][labels.name]:
        raise ValueError("Official development labels changed")
    rows, changed = [], []
    for q in qs:
        key = q["id"]
        src = reference[key]
        record = measured["rows"].get(key, {})
        if "error" in record:
            selected = {"id": key, "retrieved": src["retrieved"], "status": "error", "error": record["error"]}
        else:
            selected = decide(src, old[key], state[key][1], record.get("margins", []))
        rows.append(selected)
        if selected != src:
            changed.append(key)
    gold = klue.load(labels)
    current, previous = grade(rows, gold, docs), grade([reference[q["id"]] for q in qs], gold, docs)
    flips = [(r["answerable"],r["correct"],n["correct"]) for r,n in zip(previous["outcomes"],current["outcomes"],strict=True)
             if r["correct"] != n["correct"]]
    no_loss = not any(answerable and before and not after for answerable,before,after in flips)
    eligible = (no_loss and current["summary"]["unanswerable"]["correct"] > previous["summary"]["unanswerable"]["correct"]
                and current["summary"]["statuses"].get("error",0) <= previous["summary"]["statuses"].get("error",0))
    write_new(OUT / "development.json", {**current, "baseline": previous["summary"], "rows": rows, "changed": changed,
              "registered_inputs_checked": len(cases), "local_windows": sum(len(r.get("margins",[])) for r in measured["rows"].values()),
              "flips": flips, "eligible": eligible, "cache_sha256": file_sha256(cache), "registration_sha256": file_sha256(reg)})
    print(current["summary"]["answerable"], current["summary"]["unanswerable"], flips, eligible)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phase", choices=("register", "measure", "score"))
    run(ap.parse_args().phase)
