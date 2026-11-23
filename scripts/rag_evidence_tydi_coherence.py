"""Register and replay one exact-location agreement rule on the Korean TyDi development set."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.modules.core.generation import tydi_evidence_coherence as coherence
from scripts import rag_evidence_tydi as experiment
from scripts.rag_evidence_tydi_cache import OLD, OUT, ROOT, read
from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import file_sha256

DEST = OUT / "coherence"
INPUT = OUT / "v3"
WINDOWS = OUT / "sentence-context"
REGISTRATION = DEST / "policy-registration.json"
Row = dict[str, Any]


def registration() -> Row:
    files = [
        Path(__file__), Path(coherence.__file__), ROOT / "scripts/rag_evidence_tydi_windows.py",
        ROOT / "scripts/rag_evidence_tydi.py", ROOT / "scripts/rag_growth_ko_eval.py",
        ROOT / "app/modules/core/generation/tydi_evidence_context.py",
        ROOT / "app/modules/core/generation/korean_passage_selection.py",
        ROOT / "app/modules/core/generation/tydi_evidence_selection.py",
        INPUT / "registration.json", INPUT / "dev.cache.json", WINDOWS / "registration.json",
        WINDOWS / "dev.metrics.json", OLD / "run/policy-registration.json",
    ]
    return {
        "policy": "exact-offset agreement across raw passage/window QA views",
        "hashes": {str(p.relative_to(ROOT)): file_sha256(p) for p in files},
        "design_context": "Previous 32-case development aggregates and previous independent aggregate failure "
                          "direction were known before design. No individual independent answers used.",
        "scope": "One candidate. Same retrieval eight, original joint source, full support > 0 and direct QA "
                 "margin > 2.958441734313965. No learned thresholds or synthetic trimming.",
        "switch": "Keep original if any distinct local view ranks its exact source interval first. "
                  "An alternative must be a local rank-one and occur in the original raw n-best with the "
                  "original answer also visible in that window, or be rank-one in two distinct windows. "
                  "Change only for a unique higher sum of reciprocal ranks across raw full and window lists. "
                  "Identical text at different source offsets gets separate votes. All ties retain original.",
        "test": "32 original development questions. Predict without labels, then score the saved arms. "
                "Do not mutate original gate or use independent questions here.",
    }


def row(case: experiment.Query, raw: Row) -> Row:
    result = {"id": case.question["id"], "retrieved": [d["id"] for d in case.docs]}
    try:
        if raw.get("error"):
            raise ValueError(raw["error"])
        span = coherence.decide(case, raw["windows"])
        if span is None:
            return {**result, "status": "abstained"}
        return {**result, "status": "answered", **asdict(span)}
    except (KeyError, TypeError, ValueError) as exc:
        return {**result, "status": "error", "error": f"{type(exc).__name__}: {exc}"[:200]}


def changes(old: Row, new: Row) -> dict[str, list[str]]:
    pairs = list(zip(old["outcomes"], new["outcomes"], strict=True))
    if any(a["id"] != b["id"] or a["answerable"] != b["answerable"] for a, b in pairs):
        raise ValueError("Unmatched development grading outcomes")
    return {direction: [a["id"] for a, b in pairs if (a["correct"], b["correct"]) == transition]
            for direction, transition in (("gained", (False, True)), ("lost", (True, False)))}


def main(stage: str) -> None:
    cfg = registration()
    if stage == "register":
        write_new(REGISTRATION, cfg)
        return
    if read(REGISTRATION) != cfg:
        raise ValueError("Coherence registration changed")
    raw_path = DEST / "dev.window-readings.jsonl"
    receipt = read(DEST / "dev.replay.json")
    if (file_sha256(raw_path) != receipt["output_sha256"] or receipt["cases_reproduced"] != 32
            or file_sha256(WINDOWS / "dev.spans.jsonl") != receipt["previous_merged_sha256"]):
        raise ValueError("Unverified raw local QA readings")
    docs, cases, part = experiment.load_cached("dev", OLD / "panels", INPUT)
    lines = [json.loads(line) for line in raw_path.read_text().splitlines()]
    if len(lines) != 32 or [c.question["id"] for c in cases] != [r["id"] for r in lines]:
        raise ValueError("Incomplete or mismatched development replay")
    base = experiment.predictions(cases, "baseline", None)
    if base != read(INPUT / "dev.baseline.json"):
        raise ValueError("Original direct reader behavior changed")
    pred = [row(c, r) for c, r in zip(cases, lines, strict=True)]
    write_new(DEST / "dev.baseline.json", base)
    write_new(DEST / "dev.candidate.json", pred)
    labels = part("labels")
    old, new = grade(base, labels, docs), grade(pred, labels, docs)
    fields = ("status", "source_id", "start", "end")
    changed = [a["id"] for a, b in zip(base, pred, strict=True) if any(a.get(k) != b.get(k) for k in fields)]
    report = {
        "registration_sha256": file_sha256(REGISTRATION), "replay_sha256": file_sha256(DEST / "dev.replay.json"),
        "raw_windows_sha256": file_sha256(raw_path), "baseline": old, "candidate": new,
        "predictions": {a: file_sha256(DEST / f"dev.{a}.json") for a in ("baseline", "candidate")},
        "changed_ids": changed, "paired": changes(old, new),
    }
    write_new(DEST / "dev.metrics.json", report)
    print("baseline", experiment.counts(old), "candidate", experiment.counts(new),
          "changed", len(changed), "gained/lost", [len(v) for v in report["paired"].values()])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("register", "dev"))
    main(parser.parse_args().stage)
