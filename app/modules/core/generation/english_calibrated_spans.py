"""Apply a learned passage/span ranker and a question-level answerability model without new dependencies."""

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from .english_consensus_reader import select_answer
from .korean_span_reader import SpanAnswer

_STOP = set(
    "a an the is was are were of by in to on at what which why where when who how it this as did does do and for with".split()
)
NAMES = (
    "multi_margin",
    "has_multi",
    "old_margin",
    "old_match",
    "old_overlap",
    "rrf_support",
    "retrieval_rank",
    "proposal_rank",
    "margin_from_document_best",
    "margin_from_global_best",
    "word_length",
    "character_length",
    "question_in_quote",
    "question_in_title",
    "question_in_answer",
    "same_answer_documents",
    "numerical",
    "has_original",
)


def tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.casefold())) - _STOP


def features(
    question: str,
    docs: Sequence[Mapping[str, Any]],
    rrf: Sequence[float],
    proposals: Sequence[Sequence[SpanAnswer]],
    original: Sequence[SpanAnswer],
) -> tuple[list[SpanAnswer], list[list[float]]]:
    if (
        not docs
        or len(docs) != len(rrf)
        or len(proposals) != len(docs)
        or not all(math.isfinite(x) and x > 0 for x in rrf)
        or any(not p for p in proposals)
    ):
        raise ValueError("Incomplete retrieval or span evidence")
    q = tokens(question)
    qsize = max(len(q), 1)
    merged = []
    for i, (doc, group) in enumerate(zip(docs, proposals, strict=True)):
        old = original[i] if i < len(original) else None
        options: dict[tuple[int, int], tuple[SpanAnswer, int | None]] = {}
        for position, s in enumerate(group):
            options[(s.start, s.end)] = (s, position)
        if old is not None:
            options.setdefault((old.start, old.end), (old, None))
        for s, rank in options.values():
            if (
                s.source_id != doc["id"]
                or s.document_index != i
                or doc["content"][s.start : s.end] != s.answer
            ):
                raise ValueError("Proposed span/source mismatch")
            display = select_answer(question, [replace(s, document_index=0)], [], "deberta", -1e6)
            if display is None:
                raise ValueError("No valid answer span")
            merged.append((replace(display, document_index=i), rank, old))
    votes: Counter[str] = Counter()
    for group in proposals:
        votes.update({s.answer.casefold().strip() for s in group})
    all_best = max(p[0].score for p in proposals)
    answers, vectors = [], []
    for s, rank, old in merged:
        i = s.document_index
        overlap = 0.0
        exact = old is not None and (old.start, old.end) == (s.start, s.end)
        if old:
            overlap = max(0, min(s.end, old.end) - max(s.start, old.start)) / max(
                1, max(s.end, old.end) - min(s.start, old.start)
            )
        score = s.score if rank is not None else -25.0
        word_count = len(s.answer.split())
        vec = [
            score / 10,
            float(rank is not None),
            (old.score if old else -25) / 10,
            float(exact),
            overlap,
            math.log2(rrf[i] / max(rrf)),
            math.log2(i + 1),
            math.log2((rank if rank is not None else 5) + 1),
            (score - proposals[i][0].score) / 10,
            (score - all_best) / 10,
            math.log1p(word_count),
            math.log1p(len(s.answer)),
            len(q & tokens(s.quote)) / qsize,
            len(q & tokens(str(docs[i].get("title", "")))) / qsize,
            len(q & tokens(s.answer)) / qsize,
            math.log1p(votes[s.answer.casefold().strip()]),
            float(any(c.isdigit() for c in s.answer)),
            float(old is not None),
        ]
        if not all(math.isfinite(x) for x in vec):
            raise ValueError("Nonfinite candidate feature")
        answers.append(s)
        vectors.append(vec)
    return answers, vectors


def linear(model: Mapping[str, Any], vector: Sequence[float]) -> float:
    return float(model["intercept"]) + sum(
        float(w * (x - m) / s)
        for w, x, m, s in zip(model["weights"], vector, model["mean"], model["scale"], strict=True)
    )


def question_evidence(
    answers: Sequence[SpanAnswer],
    vectors: Sequence[Sequence[float]],
    ranker: Mapping[str, Any],
    incumbent: SpanAnswer | None,
) -> tuple[SpanAnswer, list[float]]:
    ranked = sorted(((linear(ranker, v), i) for i, v in enumerate(vectors)), reverse=True)
    best, i = ranked[0]
    v = vectors[i]
    answer = answers[i]
    competitor = next(
        (s for s, j in ranked[1:] if answers[j].answer.casefold() != answer.answer.casefold()),
        best - 5,
    )
    other_doc = next(
        (s for s, j in ranked[1:] if answers[j].source_id != answer.source_id), best - 5
    )
    return answer, [
        best,
        best - competitor,
        best - other_doc,
        v[0],
        v[2],
        v[4],
        v[5],
        v[6],
        v[12],
        v[15],
        incumbent.score / 10 if incumbent else -3.0,
        float(incumbent is not None),
        float(
            incumbent is not None
            and (incumbent.source_id, incumbent.answer) == (answer.source_id, answer.answer)
        ),
    ]


def decide(
    answer: SpanAnswer,
    probability: float,
    incumbent: SpanAnswer | None,
    mode: str,
    threshold: float,
) -> SpanAnswer | None:
    if mode == "guarded" and threshold - 0.15 <= probability <= threshold + 0.15:
        return incumbent
    if mode not in {"learned", "guarded"}:
        raise ValueError("Unknown learned span policy")
    return answer if probability >= threshold else None


def probability(judge: Mapping[str, Any], vector: Sequence[float]) -> float:
    return 1 / (1 + math.exp(-max(-50.0, min(50.0, linear(judge, vector)))))
