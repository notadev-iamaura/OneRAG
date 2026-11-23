"""Change a Korean QA answer only when separate readings reproduce its original offsets."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from fractions import Fraction
from itertools import pairwise
from typing import Any, Protocol

from .korean_passage_selection import select_passage
from .korean_span_reader import SpanAnswer, _cited_span
from .tydi_evidence_context import ContextWindow, windows
from .tydi_evidence_selection import THRESHOLD, valid

Interval = tuple[int, int]


class ReadCase(Protocol):
    question: dict
    docs: list
    candidates: list
    original: list
    full: list
    error: str | None
    incumbent_error: str | None


def _ranked(spans: Sequence[SpanAnswer]) -> dict[Interval, int]:
    result: dict[Interval, int] = {}
    for span in spans:
        result.setdefault((span.start, span.end), len(result) + 1)
    return result


def decide(case: ReadCase, window_readings: Sequence[Mapping[str, Any]]) -> SpanAnswer | None:
    """Keep the original source and answerability decision. Every alternative is a raw QA span."""
    if case.error or case.incumbent_error:
        raise ValueError(case.error or case.incumbent_error)
    _, incumbent = select_passage(case.docs, case.original, case.full, "joint", THRESHOLD)
    expected = windows(case.question["question"], case.docs, case.candidates)
    observed = [ContextWindow(w["document_index"], w["start"], w["end"]) for w in window_readings]
    if expected != observed:
        raise ValueError("Window intervals differ from the query-conditioned evidence plan")
    if incumbent is None:
        return None
    index = next(i for i, d in enumerate(case.docs) if d["id"] == incumbent.source_id)
    doc = case.docs[index]
    original = (incumbent.start, incumbent.end)
    full: list[SpanAnswer] = [incumbent, *case.candidates[index]]
    for span in full:
        valid(doc, span)
    full_ranks = _ranked(full)
    locations = {(s.start, s.end): s for s in reversed(full)}
    ranks_by_window = []
    top_votes: dict[Interval, list[ContextWindow]] = {}
    for window, raw in zip(expected, window_readings, strict=True):
        if window.document_index != index:
            continue
        excerpt = {"id": doc["id"], "content": doc["content"][window.start:window.end]}
        local = [SpanAnswer(**value) for value in raw["readings"]]
        if not local or any(a.score < b.score for a, b in pairwise(local)):
            raise ValueError("Missing or unordered raw QA window readings")
        mapped = []
        for span in local:
            valid(excerpt, span)
            a, b = window.start + span.start, window.start + span.end
            cited = _cited_span(doc["content"], index, doc["id"], a, b, span.score)
            valid(doc, cited)
            locations.setdefault((a, b), cited)
            mapped.append(cited)
        ranking = _ranked(mapped)
        top_votes.setdefault(next(iter(ranking)), []).append(window)
        ranks_by_window.append(ranking)
    if original in top_votes:
        return incumbent

    def rank_sum(key: Interval) -> Fraction:
        return sum((Fraction(1, group[key]) for group in [full_ranks, *ranks_by_window] if key in group), Fraction())

    # One window must have permitted the incumbent and the alternative to compete.
    # Two different windows can also agree on a location outside the full-passage n-best.
    alternatives = [
        key for key, votes in top_votes.items()
        if len(votes) >= 2
        or (key in full_ranks and any(w.start <= original[0] and original[1] <= w.end for w in votes))
    ]
    if not alternatives:
        return incumbent
    ranked = sorted(alternatives, key=rank_sum, reverse=True)
    score = rank_sum(ranked[0])
    if score <= rank_sum(original) or (len(ranked) > 1 and score == rank_sum(ranked[1])):
        return incumbent
    return replace(locations[ranked[0]], document_index=index)
