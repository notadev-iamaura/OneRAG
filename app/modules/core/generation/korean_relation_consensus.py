"""Combine a validated initial answer, an extractive proposal, and a second relation reading."""

from collections.abc import Mapping, Sequence
from typing import Any

Row = Mapping[str, Any]
FIELDS = ("source_id", "answer", "start", "end")
QUOTE = ("quote", "quote_start", "quote_end")


def _anchor(row: Row, sources: Mapping[str, str]) -> tuple[str, str, int, int]:
    key, answer, start, end = (row[k] for k in FIELDS)
    quote, left, right = (row[k] for k in QUOTE)
    if (key not in sources or not isinstance(answer, str) or not answer.strip()
            or not all(type(x) is int for x in (left, start, end, right))
            or not 0 <= left <= start < end <= right <= len(sources[key]) or sources[key][start:end] != answer
            or sources[key][left:right] != quote):
        raise ValueError("Consensus input has an invalid source anchor")
    return key, answer, start, end


def decide(initial: Row, proposals: Sequence[Row], review: Row,
           sources: Mapping[str, str]) -> tuple[Row, str]:
    """Return an existing response; never synthesize a new answer or an implicit abstention."""
    for row in (initial, review):
        if row["status"] not in {"answered", "abstained", "error"}:
            raise ValueError("Invalid input status")
        if row["status"] == "abstained" and any(k in row for k in (*FIELDS, *QUOTE, "citations", "cited_evidence")):
            raise ValueError("An abstention carries answer evidence")
        if row["status"] == "answered" and row["source_id"] not in row["retrieved"]:
            raise ValueError("Unretrieved initial or reviewed source")
    if initial["status"] == "error":
        return initial, "keep_initial_error"
    anchors = {_anchor(s, sources) for s in proposals}
    original = _anchor(initial, sources) if initial["status"] == "answered" else None
    revised = _anchor(review, sources) if review["status"] == "answered" else None
    if original in anchors:
        return initial, "keep_initial_encoder_agreement"
    if review["status"] == "error":
        return (initial, "keep_verified_initial_after_review_error") if original else (review, "keep_review_error")
    if review["status"] == "abstained":
        return review, "accept_explicit_refusal"
    if revised == original:
        return review, "accept_review_initial_agreement"
    if revised in anchors:
        return review, "accept_review_encoder_agreement"
    return initial, "keep_initial_no_agreement"
