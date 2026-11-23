"""Use the existing Korean sentence score only on answers actually emitted by the local QA model."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .korean_passage_selection import select_passage
from .korean_span_reader import SpanAnswer
from .tydi_evidence_coherence import ReadCase
from .tydi_evidence_context import ContextWindow, expand, windows
from .tydi_evidence_selection import _MODIFIER, THRESHOLD, type_match, units, valid


class SentenceCase(ReadCase, Protocol):
    sentences: dict


def sentence_score(question: str, span: SpanAnswer, support: float) -> float:
    """Same frozen sentence heuristic, evaluated at the raw QA interval (edit flags are zero)."""
    if not math.isfinite(support):
        raise ValueError("Nonfinite sentence evidence")
    query = units(question)
    overlap = len(query & units(span.quote)) / max(1, len(query))
    return float(10 * (span.score / 10) + 1.5 * (support / 5) + 3 * overlap + 1.5 * type_match(question, span.answer)
                 - 1.5 * bool(_MODIFIER.search(span.answer)) - .15 * math.log1p(len(span.answer)))


def decide(case: SentenceCase, window_readings: Sequence[Mapping[str, Any]]) -> SpanAnswer | None:
    if case.error or case.incumbent_error:
        raise ValueError(case.error or case.incumbent_error)
    _, original = select_passage(case.docs, case.original, case.full, "joint", THRESHOLD)
    query = case.question["question"]
    expected = windows(query, case.docs, case.candidates)
    observed = [ContextWindow(w["document_index"], w["start"], w["end"]) for w in window_readings]
    if observed != expected:
        raise ValueError("Window intervals differ from the query-conditioned evidence plan")
    readings = [[SpanAnswer(**value) for value in w["readings"]] for w in window_readings]
    groups = expand(case.docs, case.candidates, expected, readings)
    if original is None:
        return None
    doc_index = next(i for i, d in enumerate(case.docs) if d["id"] == original.source_id)
    doc = case.docs[doc_index]
    support = case.sentences.get(doc["id"], {})
    # The original direct extraction wins score ties. No suffix stripping or inferred boundaries.
    best, score = original, sentence_score(query, original, support.get(original.quote, case.full[doc_index]))
    for span in groups[doc_index]:
        valid(doc, span)
        candidate_score = sentence_score(query, span, support.get(span.quote, case.full[doc_index]))
        if candidate_score > score:
            best, score = span, candidate_score
    valid(doc, best)
    return best
