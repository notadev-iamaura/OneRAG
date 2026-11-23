"""Locate the mention of a repeated answer that supports the question in a retrieved article."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ....lib.evidence_sentences import evidence_terms
from .korean_adjudication import _sentences

_FACT = re.compile(r"[a-z]{2,}|\d+(?:[.,]\d+)*", re.I)
FEATURES = ("sentence", "immediate", "nearby", "previous", "following", "tail", "anchors", "precision")


@dataclass(frozen=True)
class Mention:
    start: int
    left: int
    right: int
    features: tuple[float, ...]


def mentions(question: str, body: str, answer: str) -> list[Mention]:
    """Score evidence surrounding each literal occurrence, omitting the answer from both sides."""
    excerpt = body[:3600]
    positions = [m.start() for m in re.finditer(re.escape(answer), excerpt)] if answer.strip() else []
    if len(positions) < 2:
        return []
    masked = question.casefold().replace(answer.casefold(), " ")
    terms = evidence_terms(masked)
    tail = evidence_terms(" ".join(masked.split()[-4:]))
    anchors = set(_FACT.findall(masked))
    units = _sentences(excerpt)
    result = []
    for pos in positions:
        end = pos + len(answer)
        for index, (left, sentence) in enumerate(units):
            right = left + len(sentence)
            if not left <= pos < end <= right:
                continue
            before, after = excerpt[left:pos], excerpt[end:right]
            context = (before + " " + after).casefold()
            local = evidence_terms(context)
            def coverage(words: set[str], evidence: set[str]) -> float:
                return len(words & evidence) / max(1, len(words))
            values = (
                coverage(terms, local),
                coverage(terms, evidence_terms(before[-32:] + " " + after[:32])),
                coverage(terms, evidence_terms(before[-72:] + " " + after[:72])),
                coverage(terms, evidence_terms(units[index - 1][1])) if index else 0.,
                coverage(terms, evidence_terms(units[index + 1][1])) if index + 1 < len(units) else 0.,
                coverage(tail, local), coverage(anchors, set(_FACT.findall(context))), coverage(local, terms),
            )
            result.append(Mention(pos, left, right, values))
            break
    return result


def select_mention(
    question: str, doc: dict[str, Any], row: dict[str, Any], coefficients: Sequence[float], margin: float,
) -> dict[str, Any]:
    if len(coefficients) != len(FEATURES) or not all(map(math.isfinite, (*coefficients, margin))) or margin < 0:
        raise ValueError("Invalid evidence mention coefficients or margin")
    source, body = doc["id"], doc["content"]
    start, end = row["start"], row["end"]
    if (row["source_id"] != source or not 0 <= row["quote_start"] <= start < end <= row["quote_end"] <= len(body)
            or body[start:end] != row["answer"] or body[row["quote_start"]:row["quote_end"]] != row["quote"]):
        raise ValueError("Invalid original source span")
    candidates = mentions(question, body, row["answer"])
    original = next((c for c in candidates if c.start == start), None)
    if original is None:
        return row
    def score(c: Mention) -> float:
        return sum(w * x for w, x in zip(coefficients, c.features, strict=True))
    best = max(candidates, key=score)
    if score(best) <= score(original) + margin:
        return row
    return {**row, "start": best.start, "end": best.start + len(row["answer"]),
            "quote": body[best.left:best.right], "quote_start": best.left, "quote_end": best.right}
