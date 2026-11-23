"""Rerank Korean passage candidates and return a source-anchored answer or abstain."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from .korean_span_reader import SpanAnswer

Policy = Literal["verifier", "joint"]


def select_passage(
    documents: Sequence[Mapping[str, Any]],
    spans: Sequence[SpanAnswer],
    sufficiency: Sequence[float],
    policy: Policy,
    span_threshold: float,
) -> tuple[list[str], SpanAnswer | None]:
    """Check offsets before combining passage relevance, span support and original rank."""
    if policy not in ("verifier", "joint") or not math.isfinite(span_threshold):
        raise ValueError("Unknown passage selection policy or invalid threshold")
    if not documents or len(documents) != len(spans) or len(documents) != len(sufficiency):
        raise ValueError("A score and span are required for every retrieved passage")
    scores = []
    for rank, (doc, span, support) in enumerate(zip(documents, spans, sufficiency, strict=True)):
        body = doc["content"]
        if (
            doc["id"] != span.source_id
            or not math.isfinite(span.score)
            or not math.isfinite(support)
            or not 0 <= span.quote_start <= span.start < span.end <= span.quote_end <= len(body)
            or body[span.start : span.end] != span.answer
            or body[span.quote_start : span.quote_end] != span.quote
        ):
            raise ValueError("Invalid source, score or span offsets")
        value = support - 0.5 * math.log2(1 + rank)
        if policy == "joint":
            value += 0.5 * max(-10.0, min(10.0, span.score))
        scores.append(value)
    order = sorted(range(len(spans)), key=lambda i: -scores[i])
    ranked = [spans[i].source_id for i in order]
    if len(set(ranked)) != len(ranked):
        raise ValueError("Repeated source ID in ranking")
    first = order[0]
    answered = sufficiency[first] > 0 and (
        policy == "verifier" or spans[first].score > span_threshold
    )
    return ranked, spans[first] if answered else None
