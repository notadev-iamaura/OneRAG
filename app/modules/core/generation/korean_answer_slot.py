"""Rank existing answer intervals by their grammatical role in Korean sentences."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

from .korean_passage_selection import select_passage
from .korean_span_reader import SpanAnswer
from .tydi_evidence_selection import THRESHOLD, valid, variants

WORD = re.compile(r"[가-힣a-zA-Z0-9]+")
WH = re.compile(r"누구|누가|어디|언제|무엇|뭐|얼마|몇|어느|어떤|무슨|어떻게|왜")
ROLE = {
    "from": ("으로부터", "로부터", "에게서", "에서"),
    "to": ("에게", "으로", "한테", "에", "로"),
    "object": ("을", "를"), "subject": ("이", "가"), "topic": ("은", "는"),
    "genitive": ("의",), "with": ("하고", "과", "와"),
    "copula": ("이라는", "라고", "이다", "였다", "이었다", "입니다", "이라고", "인가", "인", "이다"),
}
PARTICLES = sorted(((p, kind) for kind, parts in ROLE.items() for p in parts), key=lambda t: -len(t[0]))


def initial_role(word: str) -> str:
    return next((role for particle, role in PARTICLES if word.startswith(particle)), "none")


def final_role(word: str) -> tuple[str, str]:
    return next(((word[:-len(particle)], role) for particle, role in PARTICLES
                 if len(word) > len(particle) and word.endswith(particle)), (word, "none"))


def stems(text: str) -> list[str]:
    return [final_role(word.lower())[0] for word in WORD.findall(text)]


@lru_cache(maxsize=2048)
def question_parts(q: str) -> tuple[str, str, frozenset[str], frozenset[str]]:
    wh = WH.search(q)
    if wh is None:
        return "unknown", "none", frozenset(stems(q)), frozenset()
    suffix = q[wh.end():]
    role = "subject" if wh.group() == "누가" else initial_role(suffix)
    if role == "none" and wh.group() in {"몇", "어느", "어떤", "무슨"}:
        next_word = WORD.match(suffix.lstrip())
        if next_word:
            _, role = final_role(next_word.group())
    return wh.group(), role, frozenset(stems(q[:wh.start()])), frozenset(stems(suffix))


def slot_features(q: str, body: str, start: int, end: int) -> dict[str, float]:
    """Bounded feature vocabulary. Question/article words never become fitted coefficients."""
    if not 0 <= start < end <= len(body):
        raise ValueError("Answer interval outside the passage")
    wh, expected, q_left, q_right = question_parts(q)
    answer = body[start:end]
    left = re.split(r"[.!?。！？\n]", body[max(0, start - 160):start])[-1]
    right = re.split(r"[.!?。！？\n]", body[end:end + 160])[0]
    observed = initial_role(right)
    left_words, right_words = stems(left)[-7:], stems(right)[:7]
    ans_words = WORD.findall(answer)
    _, contained = final_role(ans_words[-1]) if ans_words else ("", "none")
    def proximity(qwords: frozenset[str], words: Sequence[str]) -> float:
        return max((1 / (i + 1) for i, w in enumerate(words) if w in qwords), default=0.)
    return {
        f"wh={wh}/right={observed}": 1., f"expected={expected}/right={observed}": 1.,
        f"wh={wh}/contains_right={contained}": 1., f"right={observed}": 1.,
        "subject_topic_agree": float({expected, observed} <= {"subject", "topic"}),
        "case_agreement": float(expected != "none" and expected == observed),
        "query_left_on_left": proximity(q_left, left_words[::-1]),
        "query_left_on_right": proximity(q_left, right_words),
        "query_right_on_left": proximity(q_right, left_words[::-1]),
        "query_right_on_right": proximity(q_right, right_words),
        "query_repeats_answer": float(any(w in q_left | q_right for w in stems(answer))),
        "left_in_word": float(start > 0 and body[start - 1].isalnum() and body[start].isalnum()),
        "right_in_word_without_particle": float(bool(right and right[0].isalnum() and observed == "none")),
        f"wh={wh}/numeric": float(any(ch.isdigit() for ch in answer)),
        f"wh={wh}/name_shape": float(any(ch.isupper() for ch in answer) or "·" in answer),
        "parenthesis_balanced": float(answer.count("(") == answer.count(")")),
        "answer_chars_log": math.log1p(len(answer)), "answer_words_log": math.log1p(len(ans_words)),
    }


def grammar_score(question: str, body: str, s: SpanAnswer, weights: Mapping[str, float]) -> float:
    return sum(value * weights.get(key, 0.) for key, value in slot_features(question, body, s.start, s.end).items())


def choices(question: str, doc: Mapping[str, Any], original: SpanAnswer, group: Sequence[SpanAnswer]) -> list[SpanAnswer]:
    unique: dict[tuple[int, int], SpanAnswer] = {}
    for raw in (original, *group):
        for span, _ in variants(question, raw):
            valid(doc, span)
            unique.setdefault((span.start, span.end), span)
    return list(unique.values())


def select(question: str, docs: Sequence[Mapping[str, Any]], original: Sequence[SpanAnswer],
           groups: Sequence[Sequence[SpanAnswer]], full: Sequence[float], model: Mapping[str, Any],
           *, grammar: bool = True) -> SpanAnswer | None:
    if len(groups) != len(docs) or any(not group for group in groups):
        raise ValueError("Missing measured passage candidates")
    _, span = select_passage(docs, original, full, "joint", THRESHOLD)
    if span is None:
        return None
    i = next(i for i, doc in enumerate(docs) if doc["id"] == span.source_id)
    options = choices(question, docs[i], span, groups[i])
    qa, slot = model["blend"]
    def score(s: SpanAnswer) -> float:
        value = qa * s.score / 10
        if grammar:
            value += slot * grammar_score(question, docs[i]["content"], s, model["grammar"])
        if not math.isfinite(value):
            raise ValueError("Nonfinite answer-slot score")
        return float(value)
    return max(options, key=score)
