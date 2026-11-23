"""Read up to eight Korean search results with local sufficiency and extractive QA models."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from functools import cache
from pathlib import Path
from typing import Any, TypeVar

from .korean_passage_selection import select_passage
from .korean_span_reader import SpanAnswer

Documents = Sequence[Mapping[str, Any]]
T = TypeVar("T")


def _batches(
    provider: Callable[[], Callable[[str, Documents], Sequence[T]]],
    question: str,
    documents: Documents,
) -> list[T]:
    callback = provider()
    results: list[T] = []
    for start in range(0, len(documents), 4):
        batch = documents[start : start + 4]
        values = callback(question, batch)
        if len(values) != len(batch):
            raise ValueError("Missing local reader outputs for retrieved passages")
        results.extend(values)
    return results


class KoreanRerankedPassageReader:
    """Bind PassageSufficiency.scores and KoreanSpanReader.predict_spans to ranked documents."""

    def __init__(
        self,
        score_provider: Callable[[], Callable[[str, Documents], Sequence[float]]],
        span_provider: Callable[[], Callable[[str, Documents], Sequence[SpanAnswer]]],
        *,
        span_threshold: float,
        release: Callable[[], None] | None = None,
    ):
        if not math.isfinite(span_threshold):
            raise ValueError("A finite calibrated span threshold is required")
        self.score_provider = score_provider
        self.span_provider = span_provider
        self.span_threshold = span_threshold
        self.release = release

    @classmethod
    def from_local(
        cls, reader_dir: str, verifier_dir: str, device: str, threshold: float
    ) -> KoreanRerankedPassageReader:
        from .passage_sufficiency import PassageSufficiency
        from .tydi_evidence_spans import KoreanEvidenceProposer

        def scorer() -> Callable[[str, Documents], Sequence[float]]:
            return PassageSufficiency(Path(verifier_dir), device).scores

        def spans() -> Callable[[str, Documents], Sequence[SpanAnswer]]:
            # The direct decoder and windowed decoder must both use valid segment IDs for this checkpoint.
            return KoreanEvidenceProposer(reader_dir, device=device).predict_spans

        if device == "cpu":
            return cls(cache(scorer), cache(spans), span_threshold=threshold)

        def release() -> None:
            import gc

            import torch

            gc.collect()
            if device == "mps":
                torch.mps.empty_cache()
            elif device.startswith("cuda"):
                torch.cuda.empty_cache()

        # The completed stage returns only Python values. Release its accelerator
        # tensors before loading the other model for the same request.
        return cls(scorer, spans, span_threshold=threshold, release=release)

    def read(self, question: str, documents: Documents) -> SpanAnswer | None:
        selected = documents[:8]
        if not question.strip() or not selected:
            raise ValueError("A question and at least one retrieved passage are required")
        try:
            scores = _batches(self.score_provider, question, selected)
        finally:
            if self.release:
                self.release()
        try:
            proposals = _batches(self.span_provider, question, selected)
        finally:
            if self.release:
                self.release()
        spans = [replace(span, document_index=i) for i, span in enumerate(proposals)]
        _, answer = select_passage(selected, spans, scores, "joint", self.span_threshold)
        return answer
