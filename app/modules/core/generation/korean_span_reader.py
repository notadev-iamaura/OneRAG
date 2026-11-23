"""Offline extractive QA with original passage offsets and a calibrated abstention score."""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SpanAnswer:
    document_index: int
    source_id: str
    answer: str
    start: int
    end: int
    quote: str
    quote_start: int
    quote_end: int
    score: float


def _cited_span(body: str, index: int, source: str, start: int, end: int, score: float) -> SpanAnswer:
    """Use half-open Python character offsets into the unmodified input document."""
    quote_start, quote_end = 0, len(body)
    for match in re.finditer(r"(?<=[.!?。！？])\s+|\n+", body):
        if match.end() <= start:
            quote_start = match.end()
        elif match.start() >= end:
            quote_end = match.start()
            break
    quote_start = max(quote_start, start - 300)
    quote_end = min(quote_end, end + 300)
    return SpanAnswer(index, source, body[start:end], start, end, body[quote_start:quote_end],
                      quote_start, quote_end, score)


def _best_span(
    starts: Any, ends: Any, offsets: list[tuple[int, int]], segment_ids: list[int | None],
    max_tokens: int, body: str | None = None,
) -> tuple[float, int, int] | None:
    """Find the best complete span in a passage; ignore question, CLS and padding tokens."""
    import numpy as np

    if not np.isfinite(starts).all() or not np.isfinite(ends).all():
        raise ValueError("Reader produced nonfinite model logits")
    positions = np.array([i for i, seq in enumerate(segment_ids) if seq == 1 and offsets[i][1] > offsets[i][0]])
    if not len(positions):
        return None
    left = np.arange(len(positions))[:, None]
    right = left + np.arange(min(len(positions), max_tokens))
    scores = starts[positions, None] + ends[positions[np.minimum(right, len(positions) - 1)]]
    scores[right >= len(positions)] = -np.inf
    row, width = np.unravel_index(np.argmax(scores), scores.shape)
    if body is not None and not body[offsets[positions[row]][0]:offsets[positions[row + width]][1]].strip():
        # A byte-level or SentencePiece tokenizer can assign real offsets to a run of blanks.
        # Mask only all-blank complete spans. A valid answer may still start/end in a blank token.
        nonblank = np.array([m.start() for m in re.finditer(r"\S", body)] + [len(body)])
        starts_at = np.array([offsets[i][0] for i in positions])
        ends_at = np.array([offsets[i][1] for i in positions])
        if np.any(starts_at < 0) or np.any(ends_at > len(body)):
            raise ValueError("Reader token offsets outside the source passage")
        first_nonblank = nonblank[np.searchsorted(nonblank, starts_at)]
        scores[ends_at[np.minimum(right, len(positions) - 1)] <= first_nonblank[:, None]] = -np.inf
        if not np.isfinite(scores).any():
            return None
        row, width = np.unravel_index(np.argmax(scores), scores.shape)
    margin = float(scores[row, width]) - float(starts[0] + ends[0])
    if not math.isfinite(margin):
        raise ValueError("Reader produced a nonfinite span margin")
    return margin, offsets[positions[row]][0], offsets[positions[row + width]][1]


class KoreanSpanReader:
    """Load a local Hugging Face QA checkpoint. No downloads or dynamic model code."""

    def __init__(self, model_path: str | Path, *, device: str = "cpu", threshold: float | None = None):
        import torch
        from transformers import AutoModelForQuestionAnswering, AutoTokenizer

        path = Path(model_path)
        config_path = path / "reader_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        self.max_length = int(config.get("max_length", 384))
        self.threshold = float(config.get("threshold", 0.0) if threshold is None else threshold)
        self.rank_penalty = float(config.get("rank_penalty", 0.0))
        if not 128 <= self.max_length <= 512 or not math.isfinite(self.threshold):
            raise ValueError("Invalid reader length or abstention threshold")
        if not math.isfinite(self.rank_penalty) or self.rank_penalty < 0:
            raise ValueError("Invalid retrieval rank penalty")
        self.device = torch.device(device)
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, use_fast=True)
        if not self.tokenizer.is_fast:
            raise ValueError("A fast tokenizer with passage offsets is required")
        self.model = AutoModelForQuestionAnswering.from_pretrained(
            path, local_files_only=True, use_safetensors=True
        ).to(self.device).eval()

    def predict_spans(self, question: str, documents: Sequence[Mapping[str, Any]]) -> list[SpanAnswer]:
        """Return the strongest span per supplied document, with raw span-minus-CLS logits."""
        import torch

        if not question.strip():
            raise ValueError("A nonempty reader question is required")
        if not documents:
            return []
        question_offsets = self.tokenizer(
            question, add_special_tokens=False, truncation=True, max_length=min(96, self.max_length // 3),
            return_offsets_mapping=True,
        )["offset_mapping"]
        if not question_offsets:
            raise ValueError("Question could not be tokenized")
        question = question[:question_offsets[-1][1]]
        docs: list[tuple[int, str, str]] = []
        for index, doc in enumerate(documents):
            content = doc.get("content")
            metadata = doc.get("metadata") or {}
            source = metadata.get("document_id") or doc.get("document_id") or doc.get("id")
            if not isinstance(content, str) or not content.strip() or not source:
                raise ValueError("Reader documents require nonempty content and a source ID")
            docs.append((index, str(source), content))
        batch = self.tokenizer(
            [question] * len(docs), [body for _, _, body in docs], truncation="only_second",
            max_length=self.max_length, stride=min(96, self.max_length // 4), padding=True,
            return_overflowing_tokens=True, return_offsets_mapping=True, return_tensors="pt",
        )
        offsets = batch.pop("offset_mapping").tolist()
        document_rows = batch.pop("overflow_to_sample_mapping").tolist()
        best: dict[int, SpanAnswer] = {}
        with torch.inference_mode():
            for start in range(0, len(document_rows), 4):
                inputs = {k: v[start:start + 4].to(self.device) for k, v in batch.items()}
                output = self.model(**inputs)
                lefts = output.start_logits.float().cpu().numpy()
                rights = output.end_logits.float().cpu().numpy()
                for j, (left, right) in enumerate(zip(lefts, rights, strict=True)):
                    i = start + j
                    index, source, body = docs[document_rows[i]]
                    found = _best_span(left, right, offsets[i], batch.sequence_ids(i), max_tokens=40, body=body)
                    if found is None:
                        continue
                    score, a, b = found
                    if not 0 <= a < b <= len(body):
                        raise ValueError("Reader token offsets outside the source passage")
                    while a < b and body[a].isspace():
                        a += 1
                    while a < b and body[b - 1].isspace():
                        b -= 1
                    if a < b and (index not in best or score > best[index].score):
                        best[index] = _cited_span(body, index, source, a, b, score)
        if len(best) != len(docs):
            raise ValueError("Tokenizer did not produce a usable passage span for every document")
        return [best[i] for i in sorted(best)]

    @staticmethod
    def choose(spans: Sequence[SpanAnswer], rank_penalty: float) -> SpanAnswer | None:
        """Combine the raw model margin with a fixed prior on retrieval rank."""
        return max(
            (replace(s, score=s.score - rank_penalty * math.log2(1 + s.document_index)) for s in spans),
            key=lambda s: s.score, default=None,
        )

    def predict_span(self, question: str, documents: Sequence[Mapping[str, Any]]) -> SpanAnswer | None:
        return self.choose(self.predict_spans(question, documents), self.rank_penalty)

    def read(self, question: str, documents: Sequence[Mapping[str, Any]]) -> SpanAnswer | None:
        chosen = self.predict_span(question, documents)
        return chosen if chosen is not None and chosen.score > self.threshold else None
