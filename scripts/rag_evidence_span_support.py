"""Fit/calibrate one Korean source-relation check on official train only; score original dev once."""

from __future__ import annotations

import argparse
import asyncio
import math
import re
import sys
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation import grounded_span
from app.modules.core.generation import korean_span_support as reader
from scripts import rag_evidence_klue_run as klue
from scripts import rag_evidence_windows as win
from scripts.rag_growth_ko_eval import checked_span, grade, write_new
from scripts.rag_growth_local import file_sha256
from scripts.rag_research_inputs import research_cache

OUT = klue.OUT.parent / "span-support"
DATA = research_cache() / "onerag-growth03-koreader/data"
THIRD_DEV = klue.OUT.parent / "coverage/development.json"
RAW = klue.OUT / "original/rest.json"
RAW_HASH = {"fit": "a085f787e2a8261f49cb3f8165c78288579183035b08894fc3f9d2f8ef3f6e59",
            "calibration": "2fe20d4755ceb2345e4ed5acaf3800a3dd06f1e84746de3a0ec6a754c78ca1c6"}
Row = dict[str, Any]


def spec() -> Row:
    paths = [Path(__file__), Path(reader.__file__), Path(grounded_span.__file__), Path(win.__file__),
             klue.ROOT/"app/modules/core/generation/korean_adjudication.py", klue.ROOT/"scripts/rag_growth_ko_eval.py",
             THIRD_DEV, RAW, klue.BASE/"panels/reservation.json", *(klue.BASE/n for n in win.DEV_CONTEXT)]
    if any(file_sha256(DATA/(s+".jsonl")) != d for s,d in RAW_HASH.items()):
        raise ValueError("Training or calibration input differs from registered original")
    return {"source_sha256":{str(p.resolve().relative_to(klue.ROOT)):file_sha256(p) for p in paths}, "input_sha256":RAW_HASH,
            "packages": {k:version(k) for k in ["kiwipiepy","kiwipiepy_model","scikit-learn"]},
            "train": "One liblinear C=1 L2 logistic score, original 1536 positive and 1536 impossible questions. "
                     "Normalized semantic roles, weighted question term overlap with local answer sentence/neighbors, "
                     "polarity, quantity, comparison, temporality. IDF from training questions only. The most "
                     "plausible negative locus is nearest the annotated numerical position if that offset is inexact. "
                     "Keep all tied closest loci, train each question at total weight 1.",
            "calibration": "On disjoint 96+96, require at least 99% positive question support (all 96). Select largest "
                           "inclusive evidence threshold maintaining this rate, thus rejecting maximal negative support. "
                           "Questions with tied official anchors need support at any one. Fixed scalar NO_EVIDENCE competitor.",
            "infer": "Only adjudicate already grounded answers. Preserve existing decisions when raw generation, "
                     "independent extractive boundary and selected span exactly match source ID, literal and offsets. "
                     "Otherwise abstain only when the span's score is strictly below the fixed threshold. Errors remain errors.",
            "criterion": "All 32 previously correct positive development answers remain correct, gain at least one strict "
                         "negative vs 33/40 and do not increase execution errors. No developer or final labels used for fitting."}


def load_rows(split: str) -> list[Row]:
    data = klue.load(DATA / (split+".jsonl"))
    counts = Counter(r["is_impossible"] for r in data)
    size = 1536 if split == "fit" else 96
    if counts != {False:size,True:size} or len({r["guid"] for r in data}) != len(data):
        raise ValueError("Missing expected official question strata")
    return list(data)


def anchors(r: Row) -> tuple[list[tuple[int,int]],str]:
    body = r["context"]
    pairs = list(zip(r["answers"]["answer_start"],r["answers"]["text"],strict=True))
    real = {(p,p+len(s)) for p,s in pairs if p>=0 and s.strip() and body[p:p+len(s)] == s}
    if real:
        return sorted(real),"exact"
    if not r["is_impossible"]:
        raise ValueError("An official positive needs an exact annotated interval")
    candidates = [(abs(m.start()-p),m.start(),m.end()) for p,s in pairs if s.strip()
                  for m in re.finditer(re.escape(s),body)]
    if not candidates:
        raise ValueError("Missing plausible original answer")
    best = min(cost for cost,_,_ in candidates)
    return sorted({(a,b) for cost,a,b in candidates if cost==best}),"nearest_literal"


def learn(rows: list[Row]) -> Row:
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.linear_model import LogisticRegression
    df: Counter[str] = Counter()
    for r in rows:
        df.update(reader.content(reader.tokens(r["question"])))
    idf = {w:min(8.,1+math.log((len(rows)+1)/(n+1))) for w,n in sorted(df.items())}
    x,y,weights = [],[],[]
    counts: Counter[str] = Counter()
    for r in rows:
        spans,status = anchors(r)
        counts[status] += 1
        d = {"title":r["title"],"content":r["context"]}
        for a,b in spans:
            x.append(reader.features(r["question"],d,a,b,idf))
            y.append(not r["is_impossible"])
            weights.append(1/len(spans))
    vec = DictVectorizer()
    model = LogisticRegression(C=1.,random_state=431,solver="liblinear",max_iter=150).fit(vec.fit_transform(x),y,sample_weight=weights)
    return {"idf":idf,"intercept":model.intercept_[0].item(),
            "weights":dict(zip(vec.get_feature_names_out(),model.coef_[0].tolist(),strict=True)),
            "train_queries":len(rows),"train_anchors":len(x),"source_offsets":dict(counts)}


def calibrate(model: Row, rows: list[Row]) -> Row:
    margins: dict[bool,list[float]] = {False:[],True:[]}
    locations: Counter[str] = Counter()
    for r in rows:
        doc = {"title":r["title"],"content":r["context"]}
        spans,status = anchors(r)
        locations[status] += 1
        margins[not r["is_impossible"]].append(max(reader.score(r["question"], doc,a,b,model) for a,b in spans))
    required = math.ceil(.99 *len(margins[True]))
    threshold = sorted(margins[True],reverse=True)[required-1]
    return {"threshold":threshold,"positive_supported":sum(x>=threshold for x in margins[True]),
            "negative_rejected":sum(x<threshold for x in margins[False]),"per_stratum":len(margins[True]),
            "source_offsets":dict(locations)}


class Recorded:
    def __init__(self, text: str):
        self.text = text

    async def generate_text(self, **_kwargs: Any) -> str:
        return self.text


async def development(model: Row) -> Row:
    qs,docs,cases = win.recorded_context()
    original = {r["id"]:r for r in klue.load(RAW)["rows"]}
    previous = {r["id"]:r for r in klue.load(THIRD_DEV)["rows"]}
    bodies = {d["id"]:d["content"] for d in docs}
    rows,records = [],[]
    for q in qs:
        key = q["id"]
        first,doc = previous[key],cases[key][0]
        decision: Row = {"id":key,"score":None,"compared":False,"agreement":False}
        current = first
        if first["status"] == "answered":
            try:
                if not checked_span(first,bodies) or first["source_id"] != doc["id"]:
                    raise ValueError("Invalid registered initial answer")
                receipt = original[key]["request"]
                if receipt["finish"] != "stop" or receipt["calls"] != 1 or not isinstance(receipt["raw"],str):
                    raise ValueError("No completed original generation")
                try:
                    generated = await grounded_span.read_grounded_span(Recorded(receipt["raw"]),q["question"],[doc])
                except ValueError as err:
                    if str(err) != "Answer is absent from the cited sentence":
                        raise
                    generated = None
                agree = reader.agreement(generated, cases[key][2], first)
                val = reader.score(q["question"],doc,first["start"],first["end"],model)
                decision.update(score=val,compared=not agree,agreement=agree)
                if not agree and val < model["calibration"]["threshold"]:
                    current = {"id":key,"status":"abstained","retrieved":first["retrieved"]}
            except Exception as err:
                current = {"id":key,"status":"error","retrieved":first["retrieved"],"error":f"{type(err).__name__}: {err}"}
        rows.append(current)
        records.append(decision)
    labels = klue.BASE/"panels/dev.labels.json"
    if file_sha256(labels) != klue.load(klue.BASE/"panels/reservation.json")["files"][labels.name]:
        raise ValueError("Changed development labels")
    truth = klue.load(labels)
    new,old = grade(rows,truth,docs),grade([previous[q["id"]] for q in qs],truth,docs)
    if (old["summary"]["answerable"]["correct"],old["summary"]["unanswerable"]["correct"]) != (32,33):
        raise ValueError("Original development baseline differs")
    delta: Counter[str] = Counter()
    for a,b in zip(old["outcomes"],new["outcomes"],strict=True):
        group = "pos" if a["answerable"] else "neg"
        delta[group+"_loss"] += bool(a["correct"] and not b["correct"])
        delta[group+"_gain"] += bool(b["correct"] and not a["correct"])
    return {**new,"old_summary":old["summary"],"changes":dict(delta),"rows":rows,"decisions":records,
            "eligible":not delta["pos_loss"] and delta["neg_gain"]>delta["neg_loss"]
            and new["summary"]["statuses"].get("error",0) <= old["summary"]["statuses"].get("error",0)}


def run(phase: str) -> None:
    reg,output = OUT/"registration.json",OUT/"model.json"
    if phase == "register":
        write_new(reg,spec())
        return
    if klue.load(reg) != spec():
        raise ValueError("The registered inputs or rule changed")
    if phase == "fit":
        fit,cal = load_rows("fit"),load_rows("calibration")
        for key in ("guid","context","question","title"):
            if {r[key] for r in fit}.intersection(r[key] for r in cal):
                raise ValueError("Training/calibration leakage")
        model = learn(fit)
        model["calibration"] = calibrate(model,cal)
        model["registration_sha256"] = file_sha256(reg)
        write_new(output,model)
        print(model["calibration"])
        return
    fitted = klue.load(output)
    if fitted["registration_sha256"] != file_sha256(reg):
        raise ValueError("Changed model registration")
    result = asyncio.run(development(fitted))
    write_new(OUT/"development.json",{**result,"model_sha256":file_sha256(output),"registration_sha256":file_sha256(reg)})
    print(result["changes"],result["eligible"],{s:result["summary"][s]["correct"] for s in ("answerable","unanswerable")})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phase",choices=("register","fit","score"))
    run(ap.parse_args().phase)
