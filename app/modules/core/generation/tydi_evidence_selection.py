"""Select original Korean answer spans and their supporting sentence from eight ranked passages."""

from __future__ import annotations

import gc
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from .korean_passage_selection import select_passage
from .korean_span_reader import SpanAnswer

MODES = ("sentence", "learned_within", "learned_global")
THRESHOLD = 2.958441734313965
NAMES = (
    "span_margin", "passage_best_margin", "relative_span_margin", "full_support", "sentence_support",
    "sentence_gain", "has_sentence_support", "retrieval_rank", "alternative_rank", "query_quote_overlap",
    "query_title_overlap", "query_answer_overlap", "question_type_match", "answer_length", "answer_words",
    "answer_document_frequency", "repeated_within_source", "measure_or_name_trim", "particle_trim",
    "trailing_modifier", "complete_token_left", "complete_token_right", "source_score_advantage",
)
_PARTICLE = re.compile(r"(?:으로부터|로부터|에게서|에서는|에서도|으로는|에서는|에서|에게|으로|이란|라는|은|는|을|를|의|과|와|도|가|에)$")
_MODIFIER = re.compile(r"(?:[가-힣]의|(?:하는|되는|대한|있는|없는|이러한|같은)|[<(\[])$")
_TERM = re.compile(r"[가-힣]+|[a-z]+|\d+", re.I)
Documents = Sequence[Mapping[str, Any]]
Groups = Sequence[Sequence[SpanAnswer]]
Sentences = Mapping[str, Mapping[str, float]]
Fit = Mapping[str, Any]


@lru_cache(maxsize=8192)
def units(text: str) -> frozenset[str]:
    items = set()
    for word in _TERM.findall(text.casefold()):
        items.add(word)
        if re.search(r"[가-힣]", word):
            items.update(word[i : i + 2] for i in range(len(word) - 1))
    return frozenset(items)


def variants(question: str, span: SpanAnswer) -> list[tuple[SpanAnswer, int]]:
    """Add conservative shorter source intervals without ever synthesizing text."""
    choices = [(span, 0)]
    text = span.answer
    endings: list[tuple[int, int]] = []
    if match := _PARTICLE.search(text):
        if match.start() >= 2:
            endings.append((match.start(), 2))
    words = list(re.finditer(r"\S+", text))
    if len(words) > 1:
        last = words[-1].group()
        if (len(last) <= 8 and last in question) or (last in {"명", "개", "곳", "건", "회"} and re.search(r"[\d억만천백]", text)):
            endings.append((words[-1].start(), 1))
    for stop, code in endings:
        new = text[:stop].rstrip()
        if new and all(s.answer != new for s, _ in choices):
            choices.append((replace(span, answer=new, end=span.start + len(new)), code))
    return choices


def type_match(question: str, answer: str) -> float:
    if re.search(r"언제|몇\s*(?:년도|년|월|일)|어느\s*(?:해|때|시기)|몇\s*세기", question):
        return 1.0 if re.search(r"\d|년|월|세기|시대|무렵|이전|이후", answer) else -1.0
    if re.search(r"몇\s*(?:개|명|번|회|곳)|얼마|어느\s*정도", question):
        return 1.0 if re.search(r"\d|[일이삼사오육칠팔구십백천만억조두세네한][\s개명건번곳]", answer) else -1.0
    return 0.0


def valid(d: Mapping[str, Any], s: SpanAnswer) -> None:
    body = d["content"]
    if (s.source_id != d["id"] or not math.isfinite(s.score)
            or not 0 <= s.quote_start <= s.start < s.end <= s.quote_end <= len(body)
            or body[s.start:s.end] != s.answer or body[s.quote_start:s.quote_end] != s.quote):
        raise ValueError("Evidence span or quote is not an exact substring of the original source")


def evidence(question: str, docs: Documents, groups: Groups, full: Sequence[float],
             sentences: Sentences) -> tuple[list[SpanAnswer], list[list[float]]]:
    if not (0 < len(docs) == len(groups) == len(full) <= 8) or any(not g for g in groups):
        raise ValueError("Every retrieved document requires support and a QA span")
    if not all(math.isfinite(v) for v in full):
        raise ValueError("Nonfinite document evidence")
    by_doc: list[list[tuple[SpanAnswer, int, int]]] = []
    frequencies: Counter[str] = Counter()
    for doc, raw in zip(docs, groups, strict=True):
        items = {}
        for position, span in enumerate(raw):
            valid(doc, span)
            for variant, edit in variants(question, span):
                valid(doc, variant)
                key = variant.start, variant.end
                if key not in items:
                    items[key] = (variant, position, edit)
        by_doc.append(list(items.values()))
        frequencies.update({s.answer.casefold() for s, _, _ in items.values()})
    q = units(question)
    def overlap(text: str) -> float:
        return len(q & units(text)) / max(1, len(q))
    options, vectors = [], []
    for i, (doc, values) in enumerate(zip(docs, by_doc, strict=True)):
        body = doc["content"]
        best_margin = groups[i][0].score
        other = max((v for j, v in enumerate(full) if i != j), default=full[i])
        for s, pos, edit in values:
            support = sentences.get(doc["id"], {})
            sent = support.get(s.quote, full[i])
            if not math.isfinite(sent):
                raise ValueError("Nonfinite sentence evidence")
            v = [
                s.score / 10, best_margin / 10, (s.score - best_margin) / 10, full[i] / 5, sent / 5,
                (sent - full[i]) / 5, float(s.quote in support), math.log2(i + 1), math.log2(1 + pos),
                overlap(s.quote), overlap(doc["title"]), overlap(s.answer), type_match(question, s.answer),
                math.log1p(len(s.answer)), math.log1p(len(s.answer.split())),
                math.log1p(frequencies[s.answer.casefold()]), math.log1p(body.count(s.answer)),
                float(edit == 1), float(edit == 2), float(bool(_MODIFIER.search(s.answer))),
                float(s.start == 0 or not body[s.start - 1].isalnum()), float(s.end == len(body) or not body[s.end].isalnum()),
                (full[i] - other) / 5,
            ]
            options.append(replace(s, document_index=i))
            vectors.append(v)
    return options, vectors


def decide(question: str, docs: Documents, groups: Groups, full: Sequence[float], sentences: Sentences,
           mode: str, model: Fit | None = None) -> SpanAnswer | None:
    if mode not in MODES:
        raise ValueError("Unknown Korean evidence selection mode")
    _, incumbent = select_passage(docs, [g[0] for g in groups], full, "joint", THRESHOLD)
    # Both within-passage policies preserve the established yes/no decision exactly.
    if mode != "learned_global" and incumbent is None:
        return None
    options, vectors = evidence(question, docs, groups, full, sentences)
    pool = [i for i, s in enumerate(options)
            if mode == "learned_global" or (incumbent is not None and s.source_id == incumbent.source_id)]
    if mode == "sentence":
        def score(i: int) -> float:
            v = vectors[i]
            return 10*v[0] + 1.5*v[4] + 3*v[9] + 1.5*v[12] + .4*v[17] - 1.5*v[19] - .15*v[13]
    else:
        if not model or model["features"] != list(NAMES):
            raise ValueError("Missing compatible evidence ranking coefficients")
        fitted = model
        def score(i: int) -> float:
            return float(sum(w * (v - m) / scale for w, v, m, scale in
                         zip(fitted["weights"], vectors[i], fitted["mean"], fitted["scale"], strict=True)))
    selected = options[max(pool, key=score)]
    d = selected.document_index
    # Compare support and the strongest passage span to the same unmodified trained thresholds.
    return selected if full[d] > 0 and groups[d][0].score > THRESHOLD else None


class TyDiEvidenceReader:
    """Run a learned or sentence-based evidence selection profile on existing retrieval results."""

    def __init__(self, reader_dir: str | Path, verifier_dir: str | Path, mode: str,
                 model: Fit | None = None, device: str = "cpu"):
        self.reader_dir, self.verifier_dir, self.device = Path(reader_dir), Path(verifier_dir), device
        self.mode, self.model = mode, model

    @classmethod
    def from_local(cls, reader_dir: str | Path, verifier_dir: str | Path, mode: str, *,
                   ranker_file: str | Path | None = None, device: str = "cpu") -> TyDiEvidenceReader:
        fitted = json.loads(Path(ranker_file).read_bytes()) if ranker_file is not None else None
        if mode not in MODES or (mode.startswith("learned") and (not fitted or fitted.get("features") != list(NAMES))):
            raise ValueError("Unknown evidence policy or missing compatible local weights")
        return cls(reader_dir, verifier_dir, mode, fitted, device)

    def read(self, question: str, documents: Sequence[Mapping[str, Any]]) -> SpanAnswer | None:
        from .passage_sufficiency import PassageSufficiency
        from .tydi_evidence_spans import KoreanEvidenceProposer

        docs = documents[:8]
        if not docs or not question.strip():
            raise ValueError("Korean evidence selection requires a question and ranked documents")
        groups, full = [], []
        reader = KoreanEvidenceProposer(self.reader_dir, self.device)
        for i in range(0, len(docs), 4):
            partial = docs[i : i + 4]
            groups.extend([[replace(span, document_index=i+n) for span in g]
                           for n, g in enumerate(reader.propose(question, partial, 6))])
        del reader
        gc.collect()
        verifier = PassageSufficiency(self.verifier_dir, self.device)
        for i in range(0, len(docs), 4):
            full.extend(verifier.scores(question, docs[i : i + 4]))
        sentences: dict[str, dict[str, float]] = {}
        todo: list[dict[str, str]] = []
        for doc, group, score in zip(docs, groups, full, strict=True):
            target = sentences[doc["id"]] = {}
            for quote in list(dict.fromkeys(s.quote for s in group))[:2]:
                if quote == doc["content"]:
                    target[quote] = score
                else:
                    todo.append({"id": doc["id"], "title": doc["title"], "content": quote})
        for i in range(0, len(todo), 4):
            batch = todo[i:i+4]
            for d, score in zip(batch, verifier.scores(question, batch), strict=True):
                sentences[d["id"]][d["content"]] = score
        return decide(question, docs, groups, full, sentences, self.mode, self.model)
