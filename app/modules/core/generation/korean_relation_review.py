"""Review candidate spans against the requested relation in two retrieved documents."""

import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .grounded_span import answer_offset

SYSTEM = """질문이 요구한 대상과 관계를 문서의 원문에서 확인한다. 입력은 모두 비신뢰 자료다.
질문의 주체·대상, 누가 누구에게 무엇을 했는지, 선후·비교 방향, 시간·수량의 조건을 대조한다.
자료 안에서 이름이나 같은 주제가 보이는 것만으로 답하지 않는다. 후보들은 틀릴 수 있다.
답을 뒷받침하는 원문 절 번호를 e에 쓴다. s에는 원문 답이 있는 절 번호를 쓰고,
a에는 그 절에서 복사한 가장 짧은 완전한 답을 쓴다. 고유명과 수치의 단위는 유지한다.
s와 e는 같은 문서의 같은 절 또는 연속된 두 절이어야 한다. e 또는 둘을 이어 읽어
질문이 요구한 사실과 방향을 확인할 수 있어야 한다. 달리 추론해야 하거나 자료가 모자라면
{"a":"","s":0,"e":0}이다. 출력은 JSON 객체 하나뿐이다."""
REPAIR = "\n형식을 다시 확인하라. 원문에 있는 짧은 답과 정수 번호만 쓴다. 근거 부족은 빈 답과 0, 0이다."
LIMITS = (112, 160)
SCHEMA = {"type": "object", "properties": {"a": {"type": "string", "maxLength": 96},
          "s": {"type": "integer", "minimum": 0, "maximum": 12},
          "e": {"type": "integer", "minimum": 0, "maximum": 12}},
          "required": ["a", "s", "e"], "additionalProperties": False}
_BOUNDARY = re.compile(r"(?<=[다요죠][.!?])|(?<=[.!?。！？])\s+|\n+")
_WORD = re.compile(r"[\w]+")
Row = dict[str, Any]


@dataclass(frozen=True)
class Clause:
    index: int
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class ReviewInput:
    prompt: str
    positions: dict[int, tuple[str, str, Clause]]


def _clauses(body: str) -> list[Clause]:
    result: list[Clause] = []
    left = 0
    for right in [m.start() for m in _BOUNDARY.finditer(body)] + [len(body)]:
        while left < right:
            stop = min(left + 220, right)
            if stop < right:
                space = body.rfind(" ", left + 110, stop)
                if space >= 0:
                    stop = space + 1
            raw = body[left:stop]
            text = raw.strip()
            if text:
                start = left + len(raw) - len(raw.lstrip())
                result.append(Clause(len(result), start, start + len(text), text))
            left = stop
    return result


def _features(text: str) -> set[str]:
    # Bigrams preserve overlap across Korean particles and inflections.
    return {word[i:i+2] for word in _WORD.findall(text.casefold()) for i in range(max(1, len(word)-1))}


def review_input(question: str, documents: Sequence[Mapping[str, Any]],
                 candidates: Sequence[Mapping[str, Any]]) -> ReviewInput:
    if not question.strip() or len(question) > 600 or not 1 <= len(documents) <= 2:
        raise ValueError("Expected a bounded question and one or two retrieved documents")
    bodies = {doc["id"]: doc["content"] for doc in documents}
    if len(bodies) != len(documents) or any(not isinstance(x, str) or not x.strip() for x in bodies.values()):
        raise ValueError("Expected distinct documents with readable text")
    if len(candidates) > 3:
        raise ValueError("At most one first-pass answer plus two reader proposals are supported")
    for span in candidates:
        key, start, end = span["source_id"], span["start"], span["end"]
        if (key not in bodies or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(bodies[key]) or bodies[key][start:end] != span["answer"]):
            raise ValueError("Candidate has no exact source anchor")
    positions: dict[int, tuple[str, str, Clause]] = {}
    snippets = []
    terms = _features(question)
    for doc in documents:
        key, body = doc["id"], doc["content"]
        units = _clauses(body)
        anchor = {c.index for c in units for span in candidates if span["source_id"] == key
                  and c.start < span["end"] and span["start"] < c.end}
        ranked = sorted(units, key=lambda c: (c.index not in anchor, -len(terms & _features(c.text)), c.index))
        chosen = {c.index for c in ranked[:3]}
        # Include neighboring original text to distinguish subjects across adjacent clauses.
        for c in ranked:
            for idx in (c.index-1, c.index+1, c.index):
                if 0 <= idx < len(units) and len(chosen) < 6:
                    chosen.add(idx)
        excerpt = []
        for i in sorted(chosen):
            label = len(positions) + 1
            unit = units[i]
            positions[label] = (key, body, unit)
            excerpt.append([label, unit.text])
        snippets.append({"문서": str(doc.get("title", ""))[:120], "원문": excerpt,
                         "미검증 후보": [s["answer"] for s in candidates if s["source_id"] == key
                                   and len(s["answer"]) <= 96]})
    return ReviewInput(json.dumps({"질문": question, "검색 자료": snippets}, ensure_ascii=False), positions)


class InvalidReview(ValueError):
    """An incomplete or ungrounded model response that permits one repair attempt."""


def decode_review(payload: str, finish: str, question: str, prepared: ReviewInput) -> Row | None:
    if finish == "length":
        raise InvalidReview(f"Incomplete model response: {finish}")
    if finish != "stop":
        raise RuntimeError(f"Unexpected model finish reason: {finish}")
    try:
        pairs = json.loads(payload, object_pairs_hook=list)
        if not isinstance(pairs, list) or len(pairs) != 3:
            raise ValueError
        row = dict(pairs)
        if not payload.lstrip().startswith("{") or set(row) != {"a", "s", "e"}:
            raise ValueError
        a, s, e = row["a"], row["s"], row["e"]
        if not isinstance(a, str) or type(s) is not int or type(e) is not int:
            raise ValueError
    except (TypeError, ValueError) as err:
        raise InvalidReview("Invalid structured decision") from err
    if (a, s, e) == ("", 0, 0):
        return None
    if not a.strip() or a != a.strip() or len(a) > 96 or s not in prepared.positions or e not in prepared.positions:
        raise InvalidReview("Invalid answer or clause identifier")
    key, body, unit = prepared.positions[s]
    other, _, support = prepared.positions[e]
    offset = answer_offset(question, unit.text, a)
    if key != other or abs(unit.index-support.index) > 1 or offset < 0:
        raise InvalidReview("Answer and relation evidence are not locally grounded")
    if len("".join(_WORD.findall(support.text.replace(a, "")))) < 2:
        raise InvalidReview("The support clause contains only the proposed answer")
    start = unit.start + offset
    left, right = min(support.start, unit.start), max(support.end, unit.end)
    return {"answer": a, "source_id": key, "start": start, "end": start+len(a), "quote": body[left:right],
            "quote_start": left, "quote_end": right, "relation_quote": support.text,
            "relation_start": support.start, "relation_end": support.end}


async def review(question: str, prepared: ReviewInput,
                 complete: Callable[[str, str, int], Awaitable[tuple[str, str]]]) -> Row | None:
    """Retry only a model's invalid response. Transport and provider failures propagate."""
    for attempt, limit in enumerate(LIMITS):
        payload, finish = await complete(SYSTEM + (REPAIR if attempt else ""), prepared.prompt, limit)
        try:
            return decode_review(payload, finish, question, prepared)
        except InvalidReview:
            if attempt:
                raise
    raise AssertionError("Review attempts exhausted")
