"""Combine local question-answering evidence with retrieval support and competing document answers."""

import math
from collections.abc import Sequence
from dataclasses import replace

from .english_consensus_reader import select_answer
from .korean_span_reader import SpanAnswer

MODES = ("source_support", "multidomain", "agreement")


def select_evidence(question: str, original: Sequence[SpanAnswer], multidomain: Sequence[SpanAnswer],
                    retrieval_scores: Sequence[float], mode: str, threshold: float) -> SpanAnswer | None:
    if mode not in MODES or not math.isfinite(threshold):
        raise ValueError("Unknown English evidence policy")
    first = multidomain if mode == "multidomain" else original
    if len(first) != len(retrieval_scores) or (mode == "agreement" and len(multidomain) != len(first)):
        raise ValueError("Reader and retrieval evidence must cover identical documents")
    if not first:
        return None
    if not all(math.isfinite(s) and s > 0 for s in retrieval_scores):
        raise ValueError("Expected positive finite reciprocal-rank fusion scores")
    peak = max(retrieval_scores)
    ranked = []
    for i, span in enumerate(first):
        if span.document_index != i or not math.isfinite(span.score):
            raise ValueError("Invalid reader order or score")
        score = span.score
        if mode == "agreement":
            other = multidomain[i]
            if (other.source_id, other.document_index) != (span.source_id, i) or not math.isfinite(other.score):
                raise ValueError("Reader source, order or score differs")
            overlap = max(0, min(span.end, other.end) - max(span.start, other.start))
            union = max(span.end, other.end) - min(span.start, other.start)
            agreement = overlap / union if union else 0.0
            score = .65 * span.score + .35 * other.score + 2 * (agreement - .5)
            if agreement > 0 and other.score > span.score + 2:
                span = other
        score += 3 * math.log2(retrieval_scores[i] / peak) - .5 * math.log2(i + 1)
        ranked.append(replace(span, score=score))
    ranked.sort(key=lambda s: s.score, reverse=True)
    best = ranked[0]
    different = next((v for v in ranked[1:] if v.answer.casefold().strip() != best.answer.casefold().strip()), None)
    if different is not None:
        best = replace(best, score=best.score - max(0.0, 2 - (best.score - different.score)))
    if best.score <= threshold:
        return None
    # Format via the same product function; the rank prior has already been applied.
    formatted = select_answer(question, [replace(best, document_index=0)], [], "deberta", threshold)
    return replace(formatted, document_index=best.document_index) if formatted else None
