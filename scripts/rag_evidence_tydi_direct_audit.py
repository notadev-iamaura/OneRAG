"""Describe development candidate coverage after the raw-only rule has been measured."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.modules.core.generation.korean_passage_selection import select_passage
from app.modules.core.generation.korean_span_reader import SpanAnswer
from app.modules.core.generation.tydi_evidence_context import ContextWindow, expand
from app.modules.core.generation.tydi_evidence_selection import THRESHOLD
from scripts import rag_evidence_tydi as experiment
from scripts import rag_evidence_tydi_coherence as coherence
from scripts import rag_evidence_tydi_direct as direct
from scripts.rag_evidence_tydi_cache import OLD
from scripts.rag_growth_ko_eval import write_new
from scripts.rag_growth_local import file_sha256


def key(s: SpanAnswer) -> tuple[int, int]:
    return s.start, s.end


def counts() -> dict[str, int]:
    _, cases, part = experiment.load_cached("dev", OLD / "panels", coherence.INPUT)
    labels = {r["id"]: r for r in part("labels")}
    lines = (coherence.DEST / "dev.window-readings.jsonl").read_text().splitlines()
    observed: Counter[str] = Counter()
    for case, line in zip(cases, lines, strict=True):
        record = json.loads(line)
        if record["id"] != case.question["id"] or record.get("error") or case.error or case.incumbent_error:
            raise ValueError("Development input does not match the completed policy measurements")
        raw = record["windows"]
        local = [[SpanAnswer(**h) for h in w["readings"]] for w in raw]
        windows = [ContextWindow(w["document_index"], w["start"], w["end"]) for w in raw]
        merged = expand(case.docs, case.candidates, windows, local)
        _, inc = select_passage(case.docs, case.original, case.full, "joint", THRESHOLD)
        label = labels[record["id"]]
        observed["questions"] += 1
        observed["window_reads"] += len(windows)
        added_count = sum(len(x) - len(y) for x, y in zip(merged, case.candidates, strict=True))
        observed["additional_unique_intervals_from_windows"] += added_count
        observed["questions_with_additional_intervals"] += added_count > 0
        for name, groups in (("raw_full", case.candidates), ("raw_full_and_windows", merged)):
            observed[name+"_exact_somewhere_in_top8"] += any(experiment.exact(s, label) for g in groups for s in g)
        if inc is None:
            observed["original_abstentions"] += 1
            continue
        i = next(i for i, d in enumerate(case.docs) if d["id"] == inc.source_id)
        observed["original_answers"] += 1
        observed["selected_document_added_intervals"] += len(merged[i]) - len(case.candidates[i])
        for name, group in (("raw_full", case.candidates[i]), ("raw_full_and_windows", merged[i])):
            observed[name+"_exact_in_answered_original_source"] += any(experiment.exact(s, label) for s in [inc, *group])
        peaks: dict[tuple[int, int], list[ContextWindow]] = {}
        for win, spans in zip(windows, local, strict=True):
            if win.document_index == i:
                peaks.setdefault((win.start+spans[0].start, win.start+spans[0].end), []).append(win)
        original = key(inc)
        if not peaks:
            observed["coherence_no_reread_in_original_source"] += 1
        elif original in peaks:
            observed["coherence_raw_local_rank1_kept_original"] += 1
        else:
            full = {key(s) for s in case.candidates[i]}
            qualifying = any(len(votes) > 1 or
                             (k in full and any(w.start <= inc.start and inc.end <= w.end for w in votes))
                             for k, votes in peaks.items())
            observed["coherence_alternative_failed_rank_sum" if qualifying else "coherence_no_matching_alternative"] += 1
    return dict(sorted(observed.items()))


if __name__ == "__main__":
    target = direct.DEST / "dev.coverage.json"
    report: dict[str, Any] = {"development_metrics_sha256": file_sha256(direct.DEST / "dev.metrics.json"),
                              "script_sha256": file_sha256(Path(__file__)), "counts": counts()}
    write_new(target, report)
    print(report["counts"])
