"""Transfer the previously selected Korean passage policy unchanged to existing KLUE development articles."""

from __future__ import annotations

import argparse
import gc
import hashlib
from pathlib import Path
from typing import Any

from scripts import rag_growth_tydi_ko_retrieval as runner
from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import ROOT, file_sha256

BASE = ROOT / "output/rag-growth-03"
OUT = BASE / "tydi-ko-retrieval/klue-transfer"
SEED = "onerag-ko-tydi-hybrid-to-klue-transfer-v1/"
Row = dict[str, Any]


def public_part(key: str) -> list[Row]:
    panels = BASE / "panels"
    name = f"dev.{key}.json"
    reserved = runner.load(panels / "reservation.json")
    return list(runner.load(panels / name, reserved["files"][name]))


def registration() -> Row:
    sources = [
        Path(__file__),
        BASE / "panels/reservation.json",
        BASE / "panels/dev.questions.json",
        BASE / "panels/dev.corpus.json",
        BASE / "panels/dev.labels.json",
        BASE / "tydi-ko-retrieval/run/policy-registration.json",
        BASE / "tydi-ko-retrieval/run/selected.json",
        BASE / "tydi-ko-retrieval/run/final.metrics.json",
        BASE / "qwen/rescue-dev.json",
        ROOT / "app/modules/core/generation/korean_reranked_passage_reader.py",
        ROOT / "app/modules/core/agent/extractive_reader.py",
    ]
    selected = runner.load(sources[6])
    if selected["mode"] != "joint" or not selected["eligible"]:
        raise ValueError("Different source development policy")
    labels = public_part("labels")
    # Sampling uses only ID and native answerability, independently of every prediction.
    ordered = sorted(labels, key=lambda x: hashlib.sha256((SEED + x["id"]).encode()).digest())
    first = {
        r["id"]
        for pos in (False, True)
        for r in [x for x in ordered if x["answerable"] is pos][:12]
    }
    questions = public_part("questions")
    if len(first) != 24 or len(questions) != 80:
        raise ValueError("Unexpected registered KLUE development strata")
    return {
        "scope": "Known official KLUE development panel. Transfer from frozen TyDi ranking/QA. No new independent confirmation.",
        "selection": "Read 12+12 first in fixed hash order; remaining 28+28 complete the same registered 80. No policy selection or tuning at either stage.",
        "question_order": [q["id"] for q in questions],
        "first_ids": [q["id"] for q in questions if q["id"] in first],
        "frozen_mode": "joint",
        "fields_read_for_sampling": ["id", "answerable"],
        "files": {str(p.relative_to(ROOT)): file_sha256(p) for p in sources},
    }


def params() -> argparse.Namespace:
    return argparse.Namespace(
        panels=BASE / "tydi-ko-retrieval/panels",
        device="mps",
        reader=ROOT / "models/rag-growth-03/ko-mixed-512",
        verifier=ROOT / "models/rag-growth-03/ko-sufficiency",
        embedding=Path.home()
        / ".cache/huggingface/hub/models--intfloat--multilingual-e5-small/snapshots/614241f622f53c4eeff9890bdc4f31cfecc418b3",
    )


def compare(rows: list[Row], docs: list[Row]) -> Row:
    ids = {r["id"] for r in rows}
    labels = [r for r in public_part("labels") if r["id"] in ids]
    saved = runner.load(BASE / "qwen/rescue-dev.json")
    if (saved["summary"]["answerable"]["correct"], saved["summary"]["unanswerable"]["correct"]) != (
        27,
        33,
    ):
        raise ValueError("Unexpected Qwen development control")
    control = [r for r in saved["rows"] if r["id"] in ids]
    if [r["id"] for r in rows] != [r["id"] for r in control]:
        raise ValueError("Different measurement order")
    return {
        "n": len(rows),
        "candidate": grade(rows, labels, docs),
        "control": grade(control, labels, docs),
    }


def main(operation: str) -> None:
    import torch

    torch.set_num_threads(2)
    reg = registration()
    spec = OUT / "registration.json"
    args = params()
    policy = runner.load(BASE / "tydi-ko-retrieval/run/policy-registration.json")
    if runner.identity(args) != policy:
        raise ValueError("Source policy or model changed")
    if operation == "reserve":
        write_new(spec, reg)
        return
    if runner.load(spec) != reg:
        raise ValueError("KLUE transfer registration changed")
    if operation == "rest" and not (OUT / "first.metrics.json").is_file():
        raise ValueError("First registered stratum block missing")
    write_new(OUT / (operation + ".started.json"), {"registration_sha256": file_sha256(spec)})
    qs, docs = public_part("questions"), public_part("corpus")
    ranks_path = OUT / "rankings.json"
    if operation == "first":
        all_ranks = runner.rank_questions(args, docs, qs)
        write_new(ranks_path, all_ranks)
        gc.collect()
        torch.mps.empty_cache()
    else:
        previous = runner.load(OUT / "first.metrics.json")
        all_ranks = runner.load(ranks_path, previous["ranks_sha256"])
    if [r["id"] for r in all_ranks] != reg["question_order"]:
        raise ValueError("Incomplete full-corpus rankings")
    selected = set(reg["first_ids"])
    block = [q for q in qs if (q["id"] in selected) == (operation == "first")]
    ids = {r["id"] for r in block}
    # The stored generative comparator is independent. Only the hybrid passages need a fresh encoder forward.
    ranks = [{**r, "single": []} for r in all_ranks if r["id"] in ids]
    by_id = {d["id"]: d for d in docs}
    scores = runner.score_questions(args, by_id, block, ranks, support=True)
    write_new(OUT / (operation + ".sufficiency.json"), scores)
    gc.collect()
    torch.mps.empty_cache()
    spans = runner.score_questions(args, by_id, block, ranks, support=False)
    write_new(OUT / (operation + ".spans.json"), spans)
    candidate = runner.predict(ranks, scores, spans, by_id, "hybrid", "joint")
    prediction = OUT / (operation + ".predictions.json")
    write_new(prediction, candidate)
    result = compare(candidate, docs) | {
        "ranks_sha256": file_sha256(ranks_path),
        "predictions_sha256": file_sha256(prediction),
    }
    write_new(OUT / (operation + ".metrics.json"), result)
    print(operation, {k: runner.counts(result[k]) for k in ("candidate", "control")}, flush=True)
    if operation == "rest":
        first = runner.load(
            OUT / "first.predictions.json",
            runner.load(OUT / "first.metrics.json")["predictions_sha256"],
        )
        by_q = {r["id"]: r for r in [*first, *candidate]}
        measured = compare([by_q[k] for k in reg["question_order"]], docs)
        write_new(OUT / "all.metrics.json", measured)
        print("all", {k: runner.counts(measured[k]) for k in ("candidate", "control")}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("reserve", "first", "rest"))
    main(parser.parse_args().operation)
