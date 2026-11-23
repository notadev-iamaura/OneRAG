"""Read evidence windows from one retrieved article and map citations back to the original text."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

from ....lib.evidence_sentences import evidence_terms
from .grounded_span import read_grounded_span
from .korean_adjudication import _sentences

Window = tuple[int, int]


def select_windows(
    question: str, doc: dict[str, Any], score: Callable[[str, Sequence[dict[str, Any]]], Sequence[float]],
) -> list[Window]:
    body = doc["content"][:3600]
    units = _sentences(body)
    if not units:
        return []
    if len(units) <= 3:
        return [(0, len(body))]
    # A sentence plus its neighbour retains local negations, antecedents and contrast clauses.
    windows = _pairs(units)
    candidates = [{**doc, "content": body[left:right]} for left, right in windows]
    scores = [v for i in range(0, len(candidates), 4) for v in score(question, candidates[i:i + 4])]
    if len(scores) != len(windows) or not all(math.isfinite(s) for s in scores):
        raise ValueError("Missing or invalid evidence window scores")
    return _disjoint(windows, scores)


def _pairs(units: list[tuple[int, str]]) -> list[Window]:
    return [(first[0], second[0] + len(second[1])) for first, second in zip(units, units[1:], strict=False)]


def _disjoint(windows: list[Window], scores: Sequence[float]) -> list[Window]:
    chosen: list[Window] = []
    for i in sorted(range(len(windows)), key=lambda j: -scores[j]):
        left, right = windows[i]
        if all(right <= start or end <= left for start, end in chosen):
            chosen.append((left, right))
        if len(chosen) == 3:
            break
    return sorted(chosen)


def select_anchored_windows(
    question: str, doc: dict[str, Any], boundary: dict[str, Any], support: float,
) -> list[Window]:
    """Keep an encoder-supported passage and complementary question evidence without showing candidate answers."""
    body = doc["content"][:3600]
    if not body.strip():
        return []
    units = _sentences(body)
    a, b = boundary["start"], boundary["end"]
    if (boundary["source_id"] != doc["id"] or not math.isfinite(support) or not 0 <= a < b <= len(doc["content"])
            or doc["content"][a:b] != boundary["answer"]):
        raise ValueError("Unverified boundary for retrieved article")
    if support <= 0 or len(units) <= 3 or b > len(body):
        return [(0, len(body))]
    windows = _pairs(units)
    terms = evidence_terms(question)
    window_terms = [evidence_terms(body[left:right]) for left, right in windows]
    weights = {t: 1 + math.log((1 + len(windows)) / (1 + sum(t in part for part in window_terms))) for t in terms}
    total = sum(weights.values()) or 1.
    scores = [
        2 * int(left <= a < b <= right) + sum(weights[t] for t in terms & part) / total
        for (left, right), part in zip(windows, window_terms, strict=True)
    ]
    return _disjoint(windows, scores)


async def read_windows(
    model: Any, question: str, doc: dict[str, Any], windows: Sequence[Window],
) -> dict[str, Any] | None:
    body = doc["content"]
    chunks = []
    previous_end = 0
    if len(windows) > 3:
        raise ValueError("The grounded reader accepts at most three evidence windows")
    for index, (start, end) in enumerate(windows):
        if not (previous_end <= start < end <= min(3600, len(body))):
            raise ValueError("Invalid evidence range in retrieved article")
        previous_end = end
        chunks.append({**doc, "id": str(index), "content": body[start:end]})
    proposal = await read_grounded_span(model, question, chunks)
    if proposal is None:
        return None
    left, right = windows[int(proposal["source_id"])]
    result = {**proposal, "source_id": doc["id"]}
    for field in ("start", "end", "quote_start", "quote_end"):
        result[field] += left
    if (not left <= result["quote_start"] <= result["start"] < result["end"] <= result["quote_end"] <= right
            or body[result["start"]:result["end"]] != result["answer"]
            or body[result["quote_start"]:result["quote_end"]] != result["quote"]):
        raise ValueError("Reader evidence did not map back to the original article")
    return result
