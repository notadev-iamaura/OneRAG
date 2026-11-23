"""Offline English extractive QA on the first three retrieved passages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .korean_span_reader import KoreanSpanReader, SpanAnswer


class EnglishSpanReader(KoreanSpanReader):
    """Use a local SQuAD 2.0 checkpoint with the shared source-offset reader."""

    def __init__(self, model_path: str | Path, *, device: str = "cpu", threshold: float | None = None):
        super().__init__(model_path, device=device, threshold=threshold)
        self.max_length = 512
        self.rank_penalty = 0.5
        if self.device.type == "mps":
            self.model.half()

    def read(self, question: str, documents: Sequence[Mapping[str, Any]]) -> SpanAnswer | None:
        return super().read(question, documents[:3])
