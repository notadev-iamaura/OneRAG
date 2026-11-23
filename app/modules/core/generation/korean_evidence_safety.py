"""Guard optional Korean citation repairs while preserving the original, source-checked response."""

from __future__ import annotations

import math
import re
from typing import Any

from .korean_corroborated_evidence import _verified, corroborate_misplaced_citation

Span = dict[str, Any]
_CLAUSE = re.compile(
    r"[;；\n]|,(?!\d)|(?<=[.!?。！？])(?:\s+|(?=[가-힣]))|"
    r"\s+(?:반면(?:에)?|그러나|하지만|반대로)\s+|(?<=지만)\s+"
)
_AMOUNT = re.compile(
    r"(?<![\d.,])[+−-]?\d+(?:,\d{3})*(?:\.\d+)?"
    r"(?:\s*(?P<unit>퍼센트포인트|%포인트|%p|퍼센트|%|개월|시간|분기|년도|년|월|일|"
    r"(?:억|천만|백만|십만|만|천)\s*원|달러|유로|원|명|개|곳|회|배|건|대|차|위|층|시|분|초|점|km|kg|cm))?",
    re.IGNORECASE,
)
_YEARS = re.compile(r"(?<!\d)(\d{4})\s*년")
_JOINT = re.compile(r"(?:와|과|하고|이며|이고|으며)(?=\s)|\b및\b|각각|모두|함께|둘\s*다|포함하여")
_PERIOD = re.compile(r"주기|빈도|기간|단위|간격|기준|매년|연간|월간|분기별|매월|매달|언제부터|언제까지")
_POLARITY = re.compile(
    r"않[았는을고기다음습]|아니[다었며라고]|아닌|아닙|아닐|아님|"
    r"없[는다었고음습]|못\s*[했하한할]|(?<![가-힣])안\s+(?:된|되|했|한)|"
    r"사실과\s*다르|부인|반박|철회|부정했|오보|허위|거짓|사실무근|금지|불허"
)


def _clause(doc: Span, span: Span) -> str:
    """Find the local clause containing this particular occurrence, using original text offsets."""
    body = doc["content"]
    left = 0
    for match in _CLAUSE.finditer(body):
        if match.start() >= span["end"]:
            return str(body[left:match.start()])
        if match.end() > span["start"]:
            return ""
        left = match.end()
    return str(body[left:])


def _amounts(text: str) -> set[tuple[str, str]]:
    values = set()
    for match in _AMOUNT.finditer(text):
        unit = match.group("unit") or ""
        number = match.string[match.start():match.start("unit")] if unit else match.group()
        normalized = "".join(unit.split()).casefold().replace("퍼센트", "%").replace("%포인트", "%p").replace("년도", "년")
        values.add((number.strip().replace(",", "").replace("−", "-"), normalized))
    return values


def safe_recover(question: str, doc: Span, raw: str | None, proposal: Span, support: float) -> Span | None:
    """Recover a misplaced existing label only if the same literal and numeric conditions are supported."""
    if not math.isfinite(support) or support <= 0:
        return None
    score = proposal.get("score")
    if not isinstance(score, (float, int)) or not math.isfinite(score) or score <= 4.0:
        return None
    recovered: Span | None = corroborate_misplaced_citation(doc, raw, proposal, support)
    if recovered is None:
        return None
    clause = _clause(doc, recovered)
    if not clause:
        return None
    present = _amounts(clause)
    if any(not any(n == value and (not unit or unit == found) for n, found in present)
           for value, unit in _amounts(question)):
        return None
    years = set(_YEARS.findall(question))
    if years and set(_YEARS.findall(clause)) - years:
        return None
    return recovered


def safe_extent(question: str, baseline: Span, selected: Span) -> Span:
    """Retain the baseline extent when the question also asks for attributes, timing or basis."""
    if baseline["answer"] != selected["answer"] and (_JOINT.search(question) or _PERIOD.search(question)):
        return baseline
    return selected


def _inside_identifier(body: str, a: int, b: int) -> bool:
    text = body[a:b]
    if not re.search(r"[A-Za-z0-9]", text):
        return False
    left, right = body[:a], body[b:]
    if re.match(r"[A-Za-z0-9]", text) and re.search(r"[A-Za-z0-9_](?:[./:+−-])?$", left):
        return True
    if text[0].isdigit() and re.search(r"[+−-]$|\d[.,]$", left):
        return True
    return bool(re.search(r"[A-Za-z0-9%]$", text) and
                re.match(r"[A-Za-z0-9_]|[./:+−-][A-Za-z0-9]|,\d", right))


def safe_mention(doc: Span, baseline: Span, selected: Span) -> Span:
    """Allow only a whole repeat of the same answer outside negative or rebuttal contexts."""
    if not _verified(baseline, doc) or not _verified(selected, doc) or baseline["answer"] != selected["answer"]:
        raise ValueError("Mention selection requires two verified occurrences of the same answer")
    if baseline["start"] == selected["start"]:
        return baseline
    body = doc["content"]
    for span in (baseline, selected):
        clause = _clause(doc, span)
        if not clause or _inside_identifier(body, span["start"], span["end"]) or _POLARITY.search(clause):
            return baseline
    return selected
