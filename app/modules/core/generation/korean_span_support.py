"""Estimate whether a Korean question's subject, conditions and relation support a cited interval."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

from .korean_adjudication import _sentences

Row = dict[str, Any]
SCAFFOLD = frozenset("누구 어디 언제 얼마 무엇 어느 무슨 어떤 몇 것 수 하 되 있 이 그 때 답 말 관련 경우".split())
RELATIONS = {
    "negation": ("않", "못", "아니", "없", "제외", "금지"),
    "first": ("최초", "처음", "첫", "처음으로"),
    "last": ("마지막", "최종"),
    "max": ("가장", "최대", "최고", "최다"),
    "min": ("최소", "최저", "최소한"),
    "plan": ("계획", "예정", "추진", "예상", "전망", "목표", "예고"),
    "complete": ("완료", "종료", "마치", "확정", "달성"),
    "up": ("증가", "상승", "증대", "늘", "오르"),
    "down": ("감소", "하락", "축소", "줄", "내리"),
    "before": ("이전", "전", "앞서"), "after": ("이후", "후", "뒤"),
    "comparison": ("보다", "비교", "대비", "반면", "달리", "차이"),
}


@lru_cache(maxsize=1)
def analyzer() -> Any:
    from kiwipiepy import Kiwi
    return Kiwi(num_workers=1)


@lru_cache(maxsize=12000)
def tokens(text: str) -> tuple[tuple[str, str], ...]:
    return tuple((t.form.casefold(), t.tag.partition("-")[0]) for t in analyzer().tokenize(text))


def content(ts: Sequence[tuple[str, str]]) -> frozenset[str]:
    return frozenset(w for w,t in ts if t.startswith(("NN", "VV", "VA", "XR", "SL", "SN", "SH", "MAG"))
                     and w not in SCAFFOLD)


def groups(ts: Sequence[tuple[str, str]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {n:set() for n in ("subject","object","predicate","name","number")}
    previous = ""
    for w,t in ts:
        if w in SCAFFOLD:
            previous = ""
            continue
        if t in {"JKS","JX"} and previous:
            out["subject"].add(previous)
        if t == "JKO" and previous:
            out["object"].add(previous)
        if t in {"VV","VA","XR"}:
            out["predicate"].add(w)
        if t in {"NNP","SL","SH"}:
            out["name"].add(w)
        if t == "SN":
            out["number"].add(w)
        previous = w if t.startswith(("NN", "SL", "SN", "SH")) else ""
    return out


def features(q: str, doc: Mapping[str, str], start: int, stop: int, idf: Mapping[str, float]) -> dict[str, float]:
    body = doc["content"]
    if not 0 <= start < stop <= len(body):
        raise ValueError("The proposed interval is outside its source")
    sentences = _sentences(body)
    cover = [i for i,(p,t) in enumerate(sentences) if p < stop and p+len(t) > start]
    if not cover:
        raise ValueError("No original sentence covers the interval")
    left,right = cover[0],cover[-1]
    anchor = body[sentences[left][0]:sentences[right][0]+len(sentences[right][1])]
    before,after = max(0,left-1),min(len(sentences)-1,right+1)
    window = body[sentences[before][0]:sentences[after][0]+len(sentences[after][1])]
    qt, at, wt = tokens(q), tokens(anchor), tokens(window)
    words, nearby, answer = content(qt), content(wt), content(tokens(body[start:stop]))
    signed = words - answer
    local, question_groups, local_groups = content(at), groups(qt), groups(at)
    rarity = sorted(signed,key=lambda k: (-idf.get(k,8.),k))[:3]
    def fraction(a: set[str] | frozenset[str], b: set[str] | frozenset[str]) -> float:
        return len(a & b) / max(1,len(a))
    def weighted(target: frozenset[str]) -> float:
        return sum(idf.get(w,8.) for w in sorted(signed & target)) / max(1.,sum(idf.get(w,8.) for w in sorted(signed)))
    all_surface = {w for w,_ in at}
    q_surface = {w for w,_ in qt}
    result = {"local_overlap": fraction(signed,local), "near_overlap": fraction(signed,nearby),
              "rare_local": weighted(local), "rare_near": weighted(nearby),
              "rarest3_near": fraction(set(rarity),nearby), "rarest3_local": fraction(set(rarity),local),
              "title_overlap": fraction(signed,content(tokens(doc["title"]))),
              "asked_span_terms": fraction(answer,words), "noun_pair_both": float(len(signed & local)>=2)}
    for name, qgroup in question_groups.items():
        terms = qgroup - answer
        result[name+"_same_role"] = fraction(terms,local_groups[name])
        result[name+"_near"] = fraction(terms,nearby)
        result[name+"_missing"] = float(bool(terms - nearby))
    for name, markers in RELATIONS.items():
        asked, present = bool(q_surface.intersection(markers)), bool(all_surface.intersection(markers))
        result[name+"_supported"] = float(asked and present)
        result[name+"_missing"] = float(asked and not present)
        result[name+"_only_in_source"] = float(not asked and present)
    return result


def score(q: str, doc: Mapping[str, str], start: int, stop: int, model: Row) -> float:
    x = features(q,doc,start,stop,model["idf"])
    value = model["intercept"] + sum(x[k]*v for k,v in model["weights"].items())
    if not math.isfinite(value):
        raise ValueError("Nonfinite answer support score")
    return float(value)


def agreement(generated: Row | None, proposal: Row, selected: Row) -> bool:
    if not generated:
        return False
    return bool(generated["source_id"] == proposal["source_id"] == selected["source_id"]
            and generated["answer"] == proposal["answer"] == selected["answer"]
            and generated["start"] == proposal["start"] == selected["start"]
            and generated["end"] == proposal["end"] == selected["end"])
