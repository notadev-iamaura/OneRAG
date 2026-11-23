"""Display learned Korean evidence hints only when the ranking is sufficiently strong."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .grounded_span import read_grounded_span
from .korean_evidence_selection import KoreanEvidenceSelector, features, sentences


def confidence(selector: KoreanEvidenceSelector, question: str, article: str) -> tuple[float, int]:
    scores = [sum(w*x for w, x in zip(selector.weights, feature, strict=True))
              for feature in features(question, sentences(article))]
    if not scores:
        raise ValueError("Missing article sentences")
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    best = scores[order[0]]
    margin = best - scores[order[1]] if len(scores) > 1 else 0.
    return best + margin, order[0]


class KoreanConditionalEvidenceSelector:
    def __init__(self, weights: Path, calibration: Path) -> None:
        self.selector = KoreanEvidenceSelector("trained", weights)
        self.cut = float(json.loads(calibration.read_bytes())["cut"])
        if not math.isfinite(self.cut):
            raise ValueError("Invalid sentence ranking cutoff")

    async def read(self, model: Any, question: str, documents: list[dict[str, Any]]) -> dict[str, Any] | None:
        doc, = documents
        score, _ = confidence(self.selector, question, doc["content"])
        if score >= self.cut:
            return await self.selector.read(model, question, documents)
        return await read_grounded_span(model, question, documents)
