"""Select a cited extractive answer using one or two local English QA checkpoints."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from .english_span_reader import EnglishSpanReader
from .korean_span_reader import SpanAnswer

_WHEN = re.compile(r"^(?:when\b|(?:what|which|in what|in which) year\b)", re.I)
_YEAR = re.compile(r"(?<![\w.])(?:1[0-9]{3}|20[0-9]{2})(?![\w.])")
_MONTH = re.compile(r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b", re.I)


def _focused_answer(question: str, span: SpanAnswer) -> SpanAnswer:
    # A long explanatory clause can contain the complete date. Preserve dates with month/day precision.
    if not _WHEN.search(question.strip()) or len(span.answer.split()) < 4 or _MONTH.search(span.answer):
        return span
    years = list(_YEAR.finditer(span.answer))
    if len(years) != 1 or re.search(r"\b(?:spring|summer|autumn|fall|winter|before|after|since|until)\b", span.answer, re.I):
        return span
    match = years[0]
    return replace(span, answer=match[0], start=span.start + match.start(), end=span.start + match.end())


def select_answer(question: str, first: Sequence[SpanAnswer], second: Sequence[SpanAnswer],
                  mode: str, threshold: float) -> SpanAnswer | None:
    if mode not in {"deberta", "roberta", "consensus"} or not math.isfinite(threshold):
        raise ValueError("Unknown extractive reader mode or threshold")
    if mode == "consensus":
        if len(first) != len(second):
            raise ValueError("The two readers returned different numbers of passages")
        agreed = []
        for left, right in zip(first, second, strict=True):
            if (left.document_index, left.source_id) != (right.document_index, right.source_id):
                raise ValueError("Paired reader source IDs or passage order differ")
            span = max((left, right), key=lambda s: s.score)
            # Score support for answering this passage across both encoders. Agreement improves its rank.
            overlap = max(0, min(left.end, right.end) - max(left.start, right.start))
            union = max(left.end, right.end) - min(left.start, right.start)
            score = (left.score + right.score) / 2 + (2 * overlap / union if union else 0)
            agreed.append(replace(span, score=score))
        spans: Sequence[SpanAnswer] = agreed
    else:
        spans = first if mode == "deberta" else second
    best = EnglishSpanReader.choose(spans, .5)
    return _focused_answer(question, best) if best is not None and best.score > threshold else None


class EnglishConsensusReader:
    def __init__(self, model_path: str | Path, second_model_path: str | Path, *, device: str = "cpu",
                 threshold: float = 0.0, mode: str = "consensus"):
        if mode not in {"deberta", "roberta", "consensus"} or not math.isfinite(threshold):
            raise ValueError("Unknown extractive reader mode or threshold")
        self.first = EnglishSpanReader(model_path, device=device) if mode != "roberta" else None
        self.second = EnglishSpanReader(second_model_path, device=device) if mode != "deberta" else None
        self.threshold, self.mode = threshold, mode

    def read(self, question: str, documents: Sequence[Mapping[str, Any]]) -> SpanAnswer | None:
        first = self.first.predict_spans(question, documents[:6]) if self.first else []
        second = self.second.predict_spans(question, documents[:6]) if self.second else []
        return select_answer(question, first, second, self.mode, self.threshold)
