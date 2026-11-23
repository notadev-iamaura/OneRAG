"""Retain actual per-window QA outputs and verify exact replay of the original public development run."""

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))

from app.modules.core.generation import tydi_evidence_context as ctx
from app.modules.core.generation.tydi_evidence_spans import KoreanEvidenceProposer
from scripts.rag_evidence_tydi import lines, load_cached
from scripts.rag_evidence_tydi_cache import OLD, OUT, READER
from scripts.rag_growth_ko_eval import write_new
from scripts.rag_growth_local import file_sha256


class Capture:
    def __init__(self, model):
        self.model = model
        self.groups = []

    def propose(self, q, docs, n):
        result = self.model.propose(q, docs, n)
        self.groups.extend(result)
        return result


def read_case(model, case):
    if case.error:
        raise ValueError(case.error)
    capture = Capture(model)
    windows, merged = ctx.reread(capture, case.question["question"], case.docs, case.candidates)
    return [{"document_index": w.document_index, "start": w.start, "end": w.end,
             "readings": [asdict(s) for s in group]}
            for w, group in zip(windows, capture.groups, strict=True)], merged


def reader():
    import torch

    torch.set_num_threads(4)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    return KoreanEvidenceProposer(READER, "cpu")


def recover(out):
    public = OUT / "v3"
    prior = OUT / "sentence-context" / "dev.spans.jsonl"
    old = lines(prior)
    _, cases, _ = load_cached("dev", OLD / "panels", public)
    dest = out / "dev.window-readings.jsonl"
    write_new(out / "dev.replay-started.json", {
        "previous_sha256": file_sha256(prior), "window_implementation": file_sha256(Path(ctx.__file__)),
        "capture_sha256": file_sha256(Path(__file__)), "original_cache_sha256": file_sha256(public / "dev.cache.json"),
        "question_ids": [c.question["id"] for c in cases], "expected_cases": 32})
    if len(cases) != len(old) or len(cases) != 32:
        raise ValueError("Expected every development result")
    model = reader()
    nw = 0
    with dest.open("x") as f:
        for case in cases:
            qid = case.question["id"]
            win, merged = read_case(model, case)
            new = {"id": qid, "windows": [{k: v for k, v in w.items() if k != "readings"} for w in win],
                   "candidates": [[asdict(s) for s in group] for group in merged]}
            if new != old[qid]:
                raise ValueError(f"Public window replay changed signed QA output: {qid}")
            nw += len(win)
            f.write(json.dumps({"id": qid, "windows": win}, ensure_ascii=False) + "\n")
            f.flush()
    write_new(out / "dev.replay.json", {"cases_reproduced": len(cases), "windows": nw,
              "output_sha256": file_sha256(dest), "previous_merged_sha256": file_sha256(prior)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT / "coherence")
    recover(parser.parse_args().output)
