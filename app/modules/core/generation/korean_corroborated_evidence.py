"""Choose verified Korean answer occurrences and extent from the existing two readings of an article."""

from __future__ import annotations

import math
import re
from typing import Any

from .grounded_span import _ANSWER
from .korean_evidence_selection import sentences

_MEASURE_QUESTION = re.compile(r"얼마|몇\s*(?:명|개|년|번|회|배|프로|퍼센트)|비율|비중|상승률|하락률|금액|인원")
_MEASURE = re.compile(
    r"(?:약\s*|대략\s*|매년\s+|연간\s+|연\s+|월간\s+|총\s+)?"
    r"(?P<value>\d[\d,]*(?:\.\d+)?\s*(?:퍼센트포인트|%포인트|퍼센트|개월|시간|만\s*원|억\s*원|%|원|명|개|회|배))"
    r"(?:\s*(?:정도|가량|수준))?"
)
_DATE_PREFIX = re.compile(
    r"(?:(?:\d{4}년(?:도)?|지난해|올해|내년)\s+(?:\d{1,2}월\s+)?(?:\d{1,2}일\s+)?|"
    r"(?:지난|오는)\s+\d{1,2}월\s+(?:\d{1,2}일\s+)?)"
)
_CAUSE = re.compile(r"이유|까닭|원인|왜\s")
_TITLE = re.compile(r"경기|대회|작품|영화|행사|단체|이름|책의?\s*제목")
_DATE_QUESTION = re.compile(r"언제|몇\s*년|몇\s*월|몇\s*일|연도|시기|날짜")
_FIELDS = ("source_id", "answer", "start", "end", "quote", "quote_start", "quote_end")


def _verified(span: dict[str, Any], doc: dict[str, Any]) -> bool:
    body = doc["content"]
    if span.get("source_id") != doc["id"] or any(
        type(span.get(key)) is not int for key in ("start", "end", "quote_start", "quote_end")
    ):
        return False
    a, b = span["start"], span["end"]
    left, right = span["quote_start"], span["quote_end"]
    return bool(0 <= left <= a < b <= right <= len(body) and body[a:b] == span.get("answer")
                and body[left:right] == span.get("quote"))


def corroborate_misplaced_citation(
    doc: dict[str, Any], raw: str | None, proposal: dict[str, Any], support: float,
) -> dict[str, Any] | None:
    """Only reconcile an existing sentence label when the second reader independently selected the literal answer."""
    match = _ANSWER.fullmatch((raw or "").strip())
    if not match or not math.isfinite(support) or support <= 0 or match[2].strip() != proposal.get("answer"):
        return None
    if not _verified(proposal, doc) or proposal["end"] > 3600:
        return None
    lines = sentences(doc["content"])
    cited = next((s for s in lines if s.label == match[1]), None)
    if cited is None or proposal["answer"] in cited.text:
        return None
    if not any(s.start <= proposal["start"] < proposal["end"] <= s.end for s in lines):
        return None
    return {k: proposal[k] for k in _FIELDS}


def select_supported_extent(
    question: str, doc: dict[str, Any], initial: dict[str, Any], generated: dict[str, Any] | None,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """Trim incidental date/quantity modifiers while keeping a contiguous, original source span."""
    if not _verified(initial, doc):
        raise ValueError("Invalid initial answer evidence")
    chosen, offset = initial, 0
    answer = initial["answer"]
    measure = _MEASURE.fullmatch(answer) if _MEASURE_QUESTION.search(question) else None
    if measure:
        offset, end = measure.span("value")
    else:
        # The generative reader may have supplied a complete title plus its date; use the second
        # reader to confirm the title nucleus occurs inside that same generated phrase.
        if _DATE_QUESTION.search(question) or not generated or not _verified(generated, doc):
            return initial
        answer = generated["answer"]
        date = _DATE_PREFIX.match(answer)
        if not date:
            return initial
        if not (_CAUSE.search(question) or (
            _TITLE.search(question) and _verified(proposal, doc)
            and generated["start"] + date.end() <= proposal["start"] < proposal["end"] <= generated["end"]
        )):
            return initial
        chosen, offset, end = generated, date.end(), len(answer)
    if offset >= end:
        return initial
    a, b = chosen["start"] + offset, chosen["start"] + end
    return {**initial, **{k: chosen[k] for k in ("quote", "quote_start", "quote_end")},
            "answer": doc["content"][a:b], "start": a, "end": b}
