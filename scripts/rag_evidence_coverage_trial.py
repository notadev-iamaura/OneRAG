"""Replay the registered local inference driver on separate articles, adding only repeated-mention selection."""

from __future__ import annotations

import argparse
import asyncio
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch

from app.modules.core.generation.korean_mention_coverage import select as choose_mention
from app.modules.core.retrieval.bm25_engine.tokenizer import KoreanTokenizer
from scripts import rag_evidence_corroborate_trial as trial
from scripts.rag_evidence_corroborate import select as corroborate
from scripts.rag_evidence_klue_run import load
from scripts.rag_evidence_mention_coverage import OUT
from scripts.rag_growth_local import file_sha256

PANEL = OUT.parent / "klue-third-reservation/panel"
LOCK = OUT.parent / "paired-trials/klue-third/started.json"
DEST = OUT / "confirmation"


@lru_cache(maxsize=1)
def tokenizer() -> KoreanTokenizer:
    return KoreanTokenizer()


def select(mode, question, doc, support, boundary, row, generated, raw):
    initial = corroborate(mode, question, doc, support, boundary, row, generated, raw)
    if initial["status"] == "answered":
        return choose_mention(question, doc, initial, lambda text: tokenizer().tokenize(text))
    return initial


def inputs():
    lock = load(LOCK)
    if lock["domain"] != "klue-third":
        raise ValueError("Unexpected KLUE registration")
    for key in ("common_sources", "candidate_sources", "control_sources"):
        if any(file_sha256(Path(name)) != digest for name, digest in lock[key].items()):
            raise ValueError("Third-panel source or policy differs from registration")
    for name in ("final.questions.json", "final.corpus.json"):
        if file_sha256(PANEL / name) != lock["files"][name]:
            raise ValueError("The independent public question or document file changed")
    return load(PANEL / "final.questions.json"), load(PANEL / "final.corpus.json"), file_sha256(LOCK)


def run(stage):
    # Reuse the already sealed Qwen driver verbatim, including its one dispatch per case,
    # checks for transport errors and matching control/candidate retrieval, and output receipts.
    with patch.multiple(trial, OUT=DEST, inputs=inputs, select=select):
        if stage == "prepare":
            trial.cache()
        else:
            asyncio.run(trial.measure())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "measure"))
    run(parser.parse_args().stage)
