"""Freeze the raw-span Korean sentence ranker and compare three arms on development only."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.modules.core.generation import tydi_evidence_direct as policy
from scripts import rag_evidence_tydi as experiment
from scripts import rag_evidence_tydi_coherence as coherence
from scripts.rag_evidence_tydi_cache import OLD, ROOT, read
from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import file_sha256

DEST = coherence.DEST / "raw-sentence"
LOCK = DEST / "registration.json"
Row = dict[str, Any]


def registration() -> Row:
    sources = [
        Path(__file__), Path(policy.__file__), Path(coherence.__file__),
        ROOT / "app/modules/core/generation/tydi_evidence_coherence.py",
        coherence.DEST / "policy-registration.json", coherence.DEST / "dev.replay.json",
        coherence.WINDOWS / "registration.json", coherence.INPUT / "registration.json",
        coherence.INPUT / "dev.cache.json", OLD / "run/policy-registration.json",
        ROOT / "app/modules/core/generation/tydi_evidence_context.py",
        ROOT / "app/modules/core/generation/tydi_evidence_selection.py",
        ROOT / "app/modules/core/generation/korean_passage_selection.py",
        ROOT / "scripts/rag_growth_ko_eval.py",
    ]
    return {
        "source_sha256": {str(p.relative_to(ROOT)): file_sha256(p) for p in sources},
        "change": "Original joint source, answerability and thresholds; rank only native full-passage and local "
                  "raw QA hypotheses under the existing sentence score. Never derive a new interval by editing an answer. "
                  "Deduplicate identical intervals; use the registered local score scale and original on score ties.",
        "weights": "Use the same fixed CPU checkpoints and 8-document ranks. No fitting or new model calls.",
        "context": "Designed after original development and prior independent aggregates. "
                   "The original 48 individual outcomes are not used. The 16+16 independent reserve is sealed.",
        "development": "Measure once on existing 16+16 development; save raw first. "
                       "Compare against both the original direct reader and the first-round sentence ranker. "
                       "Parent chooses one final candidate before independent data.",
    }


def predict(c: experiment.Query, raw: Row) -> Row:
    entry = {"id": c.question["id"], "retrieved": [d["id"] for d in c.docs]}
    try:
        if raw.get("error"):
            raise ValueError(raw["error"])
        span = policy.decide(c, raw["windows"])
        if span is None:
            return {**entry, "status": "abstained"}
        return {**entry, "status": "answered", **asdict(span)}
    except (KeyError, TypeError, ValueError) as exc:
        return {**entry, "status": "error", "error": f"{type(exc).__name__}: {exc}"[:200]}


def main(stage: str) -> None:
    cfg = registration()
    if stage == "register":
        write_new(LOCK, cfg)
        return
    if read(LOCK) != cfg:
        raise ValueError("Raw-span selection sources or input receipts changed")
    raw = coherence.DEST / "dev.window-readings.jsonl"
    reproduced = read(coherence.DEST / "dev.replay.json")
    if file_sha256(raw) != reproduced["output_sha256"] or reproduced["cases_reproduced"] != 32:
        raise ValueError("Incomplete raw-window reproduction")
    docs, cases, part = experiment.load_cached("dev", OLD / "panels", coherence.INPUT)
    lines = [json.loads(line) for line in raw.read_text().splitlines()]
    if len(lines) != 32 or [c.question["id"] for c in cases] != [r["id"] for r in lines]:
        raise ValueError("Mismatched development questions")
    original = experiment.predictions(cases, "baseline", None)
    sentence = experiment.predictions(cases, "sentence", None)
    if original != read(coherence.INPUT / "dev.baseline.json") or sentence != read(coherence.INPUT / "dev.sentence.json"):
        raise ValueError("Existing development predictions differ")
    predictions = [predict(c, r) for c, r in zip(cases, lines, strict=True)]
    write_new(DEST / "dev.candidate.json", predictions)
    labels = part("labels")
    answers = {"original": original, "sentence": sentence, "candidate": predictions}
    metrics = {arm: grade(rows, labels, docs) for arm, rows in answers.items()}
    fields = ("status", "source_id", "start", "end")
    paired = {}
    for arm in ("original", "sentence"):
        paired[arm] = {**coherence.changes(metrics[arm], metrics["candidate"]),
                       "changed": [a["id"] for a, b in zip(answers[arm], predictions, strict=True)
                                   if any(a.get(k) != b.get(k) for k in fields)]}
    report = {"registration_sha256": file_sha256(LOCK), "predictions_sha256": file_sha256(DEST / "dev.candidate.json"),
              "metrics": metrics, "paired": paired}
    write_new(DEST / "dev.metrics.json", report)
    print({arm: experiment.counts(result) for arm, result in metrics.items()},
          {arm: {k: len(v) for k, v in counts.items()} for arm, counts in paired.items()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("register", "dev"))
    main(parser.parse_args().stage)
