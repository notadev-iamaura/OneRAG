"""Prioritize question-relevant source sentences without changing the span reader's citation contract."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .grounded_span import _BREAK, read_grounded_span

FEATURES = (
    "word_coverage", "rare_coverage", "bigram_coverage", "last_terms", "entity_coverage",
    "neighbor_coverage", "local_precision", "quantity", "answer_shape", "lead", "length",
)
_WORD = re.compile(r"[가-힣]+|[a-z]+|\d+(?:[.,]\d+)*", re.I)
_PARTICLES = re.compile(r"(?:으로부터|에서는|에게서|으로써|으로서|에서|에게|으로|보다|까지|부터|처럼|에게|들의|은|는|이|가|을|를|의|에|로|와|과|도|만)$")
_ASK = frozenset("누가 누구 언제 어디 어떤 얼마 무엇 몇 무슨 어떻게 왜 어느 것 수 이 그 한 하는 된 있는 있 는".split())


@dataclass(frozen=True)
class Sentence:
    label: str
    start: int
    end: int
    text: str


def sentences(body: str, document_number: int = 1) -> list[Sentence]:
    excerpt = body[:3600]
    left, result = 0, []
    for i, end in enumerate([m.start() for m in _BREAK.finditer(excerpt)] + [len(excerpt)], 1):
        text = excerpt[left:end].strip()
        if text:
            start = excerpt.index(text, left, end)
            result.append(Sentence(f"{document_number}.{i}", start, start + len(text), text))
        left = end
    return result


def _tokens(text: str) -> list[str]:
    tokens = []
    for raw in _WORD.findall(text.casefold()):
        form = _PARTICLES.sub("", raw) if len(raw) >= 3 else raw
        if form and form not in _ASK:
            tokens.append(form)
    return tokens


def _bigrams(words: list[str]) -> set[str]:
    return {w[i:i + 2] for w in words for i in range(max(1, len(w) - 1))}


def _overlap(terms: set[str], other: set[str]) -> float:
    return len(terms & other) / max(1, len(terms))


def features(question: str, lines: list[Sentence]) -> list[list[float]]:
    words = _tokens(question)
    terms, grams = set(words), _bigrams(words)
    anchors = set(re.findall(r"[0-9]+(?:[.,][0-9]+)*|[a-z]+", question.casefold()))
    vectors = [_tokens(line.text) for line in lines]
    sets = [set(v) for v in vectors]
    df = Counter(word for names in sets for word in names)
    weights = {w: math.log1p((len(lines) + 1) / (df[w] + 1)) for w in terms}
    wants_quantity = bool(re.search(r"몇|얼마|수량|시기|언제|어느 해", question))
    rows = []
    for i, words_in_line in enumerate(vectors):
        present = sets[i]
        neighbor = set().union(*sets[max(0, i - 1):i + 2])
        common = terms & present
        rows.append([
            _overlap(terms, present), sum(weights[w] for w in common) / max(1., sum(weights.values())),
            _overlap(grams, _bigrams(words_in_line)), _overlap(set(words[-3:]), present),
            _overlap(anchors, present), _overlap(terms, neighbor), _overlap(present, terms),
            float(bool(anchors) and anchors <= present),
            float(wants_quantity and bool(re.search(r"\d", lines[i].text))),
            1 / (1 + i), min(150, len(lines[i].text)) / 150,
        ])
    return rows


class KoreanEvidenceSelector:
    def __init__(self, mode: str = "lexical", weights_path: str | Path | None = None) -> None:
        if mode not in {"lexical", "trained"}:
            raise ValueError("Unknown evidence selection mode")
        self.mode = mode
        if mode == "trained":
            if weights_path is None:
                raise ValueError("Trained sentence features require a local coefficient file")
            params = json.loads(Path(weights_path).read_bytes())
            if params["features"] != list(FEATURES):
                raise ValueError("Incompatible sentence ranking features")
            self.weights = [float(x) for x in params["coefficients"]]
        else:
            self.weights = [1., 2., 1., .75, .75, 0., .3, .2, 0., 0., 0.]
        if len(self.weights) != len(FEATURES) or not all(map(math.isfinite, self.weights)):
            raise ValueError("Invalid evidence coefficients")

    def rank(self, question: str, lines: list[Sentence]) -> list[int]:
        rows = features(question, lines)
        scores = [sum(w * x for w, x in zip(self.weights, row, strict=True)) for row in rows]
        return sorted(range(len(rows)), key=lambda i: (-scores[i], i))

    async def read(self, model: Any, question: str, documents: list[dict[str, Any]]) -> dict[str, Any] | None:
        if len(documents) != 1:
            raise ValueError("The Korean sentence selector expects exactly one retrieved article")
        lines = sentences(documents[0]["content"])
        order = self.rank(question, lines)
        labels = [lines[i].label for i in order[:3]]
        # Keep all original citations and all natural source order. The short list only guides attention.
        guide = "질문과 관련될 수 있는 원문 문장: " + ", ".join(f"[{v}]" for v in labels)
        guide += "\n이 번호는 검색 추천이다. 원문 전체에서 질문의 대상과 관계를 확인하고 답을 고른다."
        return await read_grounded_span(_EvidencePrompt(model, guide), question, documents)


class _EvidencePrompt:
    def __init__(self, model: Any, guide: str) -> None:
        self.model, self.guide = model, guide

    async def generate_text(self, *, prompt: str, **kwargs: Any) -> str:
        return str(await self.model.generate_text(prompt=self.guide + "\n" + prompt, **kwargs))
