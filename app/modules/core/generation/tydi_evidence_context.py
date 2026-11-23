"""Reread two query-conditioned Korean sentence windows while retaining original citation offsets."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .korean_span_reader import SpanAnswer, _cited_span
from .tydi_evidence_selection import units, valid

_EDGE = re.compile(r"(?<=[.!?。！？])\s+|\n+|(?<=[다요죠]\.)(?=[가-힣])")


@dataclass(frozen=True)
class ContextWindow:
    document_index: int
    start: int
    end: int


def ranges(body: str) -> list[tuple[int, int]]:
    starts, ends = [0], []
    for split in _EDGE.finditer(body):
        ends.append(split.start())
        starts.append(split.end())
    ends.append(len(body))
    sentences = []
    for a, b in zip(starts, ends, strict=True):
        while a < b and body[a].isspace():
            a += 1
        while a < b and body[b - 1].isspace():
            b -= 1
        if a < b:
            sentences.append((a, b))
    return sentences


def windows(question: str, documents: Sequence[Mapping[str, Any]], groups: Sequence[Sequence[SpanAnswer]]) -> list[ContextWindow]:
    if len(documents) != len(groups):
        raise ValueError("Every ranked passage needs its own original reader evidence")
    results = []
    query = units(question)
    for i, (doc, group) in enumerate(zip(documents, groups, strict=True)):
        if not group:
            raise ValueError("No original QA span in supplied passage")
        valid(doc, group[0])
        body = doc["content"]
        pieces = ranges(body)
        if len(pieces) < 2:
            continue
        bags = [query & units(body[a:b]) for a, b in pieces]
        count = Counter(w for wset in bags for w in wset)
        weights = [sum(math.log((len(pieces) + 1) / (count[w] + .5)) for w in bag)
                   / math.sqrt(1 + (b - a) / 160)
                   for bag, (a, b) in zip(bags, pieces, strict=True)]
        lexical = max(range(len(pieces)), key=lambda k: (weights[k], -k))
        strongest = max(range(len(pieces)), key=lambda k: max(0, min(pieces[k][1], group[0].end)
                                                               - max(pieces[k][0], group[0].start)))
        used = set()
        for anchor in (lexical, strongest):
            neighbors = [j for j in (anchor - 1, anchor + 1) if 0 <= j < len(pieces)]
            neighbor = max(neighbors, key=lambda j: (weights[j], -j))
            a, b = pieces[min(anchor, neighbor)][0], pieces[max(anchor, neighbor)][1]
            # If the two sentences are the entire input, reread just the selected sentence.
            if (a, b) == (pieces[0][0], pieces[-1][1]):
                a, b = pieces[anchor]
            if (a, b) not in used:
                used.add((a, b))
                results.append(ContextWindow(i, a, b))
    return results


def expand(
    docs: Sequence[Mapping[str, Any]],
    groups: Sequence[Sequence[SpanAnswer]],
    contexts: Sequence[ContextWindow],
    readings: Sequence[Sequence[SpanAnswer]],
) -> list[list[SpanAnswer]]:
    """Compare local span margins to their own window, then map the selected text back to its source."""
    if len(contexts) != len(readings):
        raise ValueError("Missing context readings")
    result = [list(group) for group in groups]
    seen = [{(s.start, s.end) for s in g} for g in groups]
    for win, spans in zip(contexts, readings, strict=True):
        i = win.document_index
        doc = docs[i]
        body = doc["content"]
        if not (0 <= win.start < win.end <= len(body)) or not spans:
            raise ValueError("Invalid or unread context window")
        excerpt = {"id": doc["id"], "content": body[win.start:win.end]}
        window_peak = spans[0].score
        for span in spans:
            valid(excerpt, span)
            a, b = win.start + span.start, win.start + span.end
            if (a, b) in seen[i]:
                continue
            score = min(groups[i][0].score, window_peak) - (window_peak - span.score)
            candidate = _cited_span(body, i, doc["id"], a, b, score)
            valid(doc, candidate)
            seen[i].add((a, b))
            result[i].append(candidate)
    # Keep the original full-passage maximum for the unmodified sufficiency gate.
    # Put all other hypotheses on the same within-document ranking scale.
    return [[group[0], *sorted(group[1:], key=lambda s: (-s.score, s.start, s.end))] for group in result]


def reread(model: Any, question: str, documents: Sequence[Mapping[str, Any]],
           groups: Sequence[Sequence[SpanAnswer]]) -> tuple[list[ContextWindow], list[list[SpanAnswer]]]:
    contexts = windows(question, documents, groups)
    readings = []
    for start in range(0, len(contexts), 4):
        batch = []
        for item in contexts[start : start + 4]:
            doc = documents[item.document_index]
            batch.append({"id": doc["id"], "title": doc["title"], "content": doc["content"][item.start:item.end]})
        readings.extend(model.propose(question, batch, 6))
    return contexts, expand(documents, groups, contexts, readings)
