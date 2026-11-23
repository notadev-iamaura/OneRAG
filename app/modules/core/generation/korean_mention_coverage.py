"""Prefer an unambiguous repeated occurrence whose clause covers all competing question terms."""

import re
from collections.abc import Callable, Sequence
from typing import Any

from .korean_adjudication import _sentences

# Generic question scaffolding contributes no entity or factual condition.
_FUNCTION = frozenset("누구 어디 언제 얼마 무엇 어느 무슨 어떤 몇 것 수 하 되 있 이 그 때 것 사람 시기 이름 때문".split())


def select(
    question: str, document: dict[str, Any], span: dict[str, Any], tokenize: Callable[[str], Sequence[str]],
) -> dict[str, Any]:
    body, answer, original = document["content"], span["answer"], span["start"]
    if (span["source_id"] != document["id"] or not answer or body[original:span["end"]] != answer
            or not 0 <= span["quote_start"] <= original < span["end"] <= span["quote_end"] <= len(body)
            or body[span["quote_start"]:span["quote_end"]] != span["quote"]):
        raise ValueError("Unverified initial source span")
    positions = [m.start() for m in re.finditer(re.escape(answer), body[:3600])]
    if len(positions) < 2 or original not in positions:
        return span
    terms = set(tokenize(question)) - set(tokenize(answer)) - _FUNCTION
    candidates: list[tuple[int, int, int, set[str]]] = []
    for left, sentence in _sentences(body[:3600]):
        right = left + len(sentence)
        included = [a for a in positions if left <= a and a + len(answer) <= right]
        if included:
            covered = terms.intersection(tokenize(sentence.replace(answer, " ")))
            candidates.extend((a, left, right, covered) for a in included)
    first = next((c for c in candidates if c[0] == original), None)
    if first is None:
        return span
    # With ties or competing conditions in different sentences, retain the original attribution.
    selected = [c for c in candidates if len(c[3]) >= 2 and all(
        other[0] == c[0] or c[3] > other[3] for other in candidates)]
    if len(selected) != 1 or selected[0][0] == original:
        return span
    a, left, right, _ = selected[0]
    return {**span, "start": a, "end": a + len(answer), "quote_start": left, "quote_end": right, "quote": body[left:right]}
