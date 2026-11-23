"""Offline training and one development comparison for a Korean answer-slot reranker."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))

from app.modules.core.generation import korean_answer_slot as slot
from app.modules.core.generation import tydi_evidence_selection as first
from app.modules.core.generation.korean_passage_selection import select_passage
from scripts import rag_evidence_tydi as shared
from scripts.rag_growth_gate import normalized
from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import file_sha256
from scripts.rag_research_inputs import research_cache

Row = dict[str, Any]
OUT = ROOT / "output/rag-evidence-selection/answer-slot"
CACHE = OUT.parent / "tydi/v3"
FIT = OUT.parent / "tydi-fit"
DEV = ROOT / "output/rag-growth-03/tydi-ko-retrieval/panels"
KLUE = research_cache() / "onerag-growth03-koreader/data/fit.jsonl"
FILES = {
    KLUE: "a085f787e2a8261f49cb3f8165c78288579183035b08894fc3f9d2f8ef3f6e59",
    FIT / "reservation.json": "5da8532f7dc72854fa7f9280ed838f95879b3827c5c850c3846a0d04b1e9e5ea",
    DEV / "reservation.json": "84d12821aaa1ed48dd7af86277de71c01b19dab0a00b7af8c88510edeba41ded",
}


def read(p: Path) -> Any:
    return json.loads(p.read_text())


def registration() -> Row:
    if any(file_sha256(p) != v for p, v in FILES.items()):
        raise ValueError("Changed reserved training/development data")
    paths = [Path(__file__), Path(slot.__file__), Path(first.__file__),
             ROOT / "app/modules/core/generation/korean_passage_selection.py",
             ROOT / "scripts/rag_growth_ko_eval.py", ROOT / "scripts/rag_growth_gate.py"]
    return {
        "schema": 1, "source_sha256": {str(p.relative_to(ROOT)): file_sha256(p) for p in paths},
        "inputs": {str(p): v for p, v in FILES.items()}, "neural_calls": 0,
        "grammar": "One C=1 L2 logistic classifier. Within the official source sentence, contrast one "
                   "annotated interval with up to 12 equal-weight nearby answer-slot and boundary foils, "
                   "using 1536 earlier official KLUE train positives and 48 registered TyDi train positives. "
                   "Surface vocabulary of actual questions/articles is not fitted.",
        "blend": "One C=0.5 L2 pairwise fit on the 96 registered TyDi train query pools. "
                 "Use all exact vs incorrect pairs in the positive reference, equal total weight per query. "
                 "Rank within the joint policy's accepted article by QA margin/10 and grammar logit. "
                 "No threshold tuning, document switching or new text. Ties retain incumbent first.",
        "development": "Evaluate the fixed candidate, QA-only ablation, joint and first selected policy on "
                       "all 16+16 with official occurrence-grounded exact match. Declare development gain "
                       "only with positive gain vs joint, no negative loss, and no added errors. "
                       "Publish both >=80 separately. No confirmation data access.",
    }


def contrast(body: str, start: int, end: int, aliases: set[str]) -> list[tuple[int, int]]:
    lo, hi = max(0, start - 110), min(len(body), end + 110)
    while lo < start and any(p in body[lo:start] for p in ".!?\n。"):
        lo += 1
    while hi > end and any(p in body[end:hi] for p in ".!?\n。"):
        hi -= 1
    words = list(slot.WORD.finditer(body, lo, hi))
    width = max(1, len(slot.WORD.findall(body[start:end])))
    bounds = {(start, end-1), (start+1, end), (start, end+1), (start-1, end)}
    for i, w in enumerate(words):
        j = min(i + width, len(words)) - 1
        stop = words[j].end()
        bounds.add((w.start(), stop))
        stem, role = slot.final_role(words[j].group())
        if role != "none":
            bounds.add((w.start(), words[j].start() + len(stem)))
    valid = [(a, b) for a, b in bounds if lo <= a < b <= hi and body[a:b].strip() == body[a:b]
             and normalized(body[a:b]) not in aliases and normalized(body[a:b])]
    return sorted(valid, key=lambda t: (abs(t[0]-start)+abs(t[1]-end), t))[:12]


def fit_grammar() -> Row:
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.linear_model import LogisticRegression

    examples = []
    for r in map(json.loads, KLUE.read_text().splitlines()):
        if not r["is_impossible"]:
            a = r["answers"]
            examples.append((r["question"], r["context"], a["answer_start"][0], a["text"][0], a["text"]))
    if len(examples) != 1536:
        raise ValueError("KLUE training scope changed")
    hashes = read(FIT / "reservation.json")["files"]
    def fit_part(suffix: str) -> list[Row]:
        key = f"fit.{suffix}.json"
        if file_sha256(FIT / key) != hashes[key]:
            raise ValueError("Unregistered TyDi training material")
        return list(read(FIT / key))
    docs = {d["id"]: d["content"] for d in fit_part("corpus")}
    questions = {q["id"]: q["question"] for q in fit_part("questions")}
    for label in fit_part("labels"):
        if label["answerable"]:
            b, s = docs[label["source_id"]], label["spans"][0]
            examples.append((questions[label["id"]], b, s["start"], b[s["start"]:s["end"]], label["answers"]))
    if len(examples) != 1584:
        raise ValueError("TyDi training scope changed")
    features, labels, weights, used = [], [], [], 0
    for q, body, start, answer, aliases in examples:
        end = start + len(answer)
        if body[start:end] != answer or normalized(answer) not in {normalized(a) for a in aliases}:
            raise ValueError("Invalid official training occurrence")
        foil = contrast(body, start, end, {normalized(a) for a in aliases})
        if foil:
            used += 1
            for a, b in [(start, end), *foil]:
                pos = (a, b) == (start, end)
                features.append(slot.slot_features(q, body, a, b))
                labels.append(pos)
                weights.append(.5 if pos else .5 / len(foil))
    vec = DictVectorizer()
    clf = LogisticRegression(C=1., solver="liblinear", random_state=431).fit(
        vec.fit_transform(features), labels, sample_weight=weights)
    return {"grammar": dict(zip(vec.get_feature_names_out(), clf.coef_[0].tolist(), strict=True)),
            "questions_available": len(examples), "questions_used": used, "intervals_used": len(features)}


def fit_blend(cases: list, labels: dict[str, Row], weights: dict[str, float]) -> Row:
    from sklearn.linear_model import LogisticRegression

    x, y, w, used = [], [], [], 0
    for c in cases:
        label = labels[c.question["id"]]
        if c.error:
            raise ValueError("Incomplete corrected fit cache")
        for d, base, group in zip(c.docs, c.original, c.candidates, strict=True):
            if label["source_id"] != d["id"]:
                continue
            q = c.question["question"]
            options = slot.choices(q, d, base, group)
            positives: list[tuple[float, float]] = []
            negatives: list[tuple[float, float]] = []
            for s in options:
                v = (s.score / 10, slot.grammar_score(q, d["content"], s, weights))
                (positives if shared.exact(s, label) else negatives).append(v)
            if positives and negatives:
                used += 1
                for p in positives:
                    for n in negatives:
                        for sign in (1, -1):
                            x.append([sign*(a-b) for a,b in zip(p, n, strict=True)])
                            y.append(int(sign == 1))
                            w.append(.5 / (len(positives)*len(negatives)))
    if not x:
        raise ValueError("No training queries with exact and incorrect options")
    clf = LogisticRegression(C=.5, fit_intercept=False, solver="liblinear", random_state=431).fit(x,y,sample_weight=w)
    return {"blend": clf.coef_[0].tolist(), "fit_queries": len(cases), "contrast_queries": used, "pairs": len(x)//2}


def predict(cases: list, model: Row, grammar: bool) -> list[Row]:
    rows = []
    for c in cases:
        row: Row = {"id": c.question["id"], "retrieved": [d["id"] for d in c.docs]}
        try:
            if c.error or c.incumbent_error:
                raise ValueError(c.error or c.incumbent_error)
            span = slot.select(c.question["question"], c.docs, c.original, c.candidates, c.full, model, grammar=grammar)
            if span is None:
                row["status"] = "abstained"
            else:
                row.update(status="answered", **asdict(span))
        except (TypeError, ValueError, IndexError, KeyError) as exc:
            row.update(status="error", error=f"{type(exc).__name__}: {exc}"[:200])
        rows.append(row)
    return rows


def paired(base: Row, result: Row) -> Row:
    counts: Row = {}
    for x,y in zip(base["outcomes"], result["outcomes"], strict=True):
        if (x["id"], x["answerable"]) != (y["id"], y["answerable"]):
            raise ValueError("Changed pair ordering")
        group = "positive" if x["answerable"] else "negative"
        k = "gain" if y["correct"] and not x["correct"] else "loss" if x["correct"] and not y["correct"] else "same"
        group_counts = counts.setdefault(group, {"gain": 0, "loss": 0, "same": 0})
        group_counts[k] += 1
    return counts


def run(phase: str) -> None:
    reg = OUT / "registration.json"
    if phase == "register":
        write_new(reg, registration())
        return
    if registration() != read(reg):
        raise ValueError("Answer-slot registration changed")
    gpath, mpath = OUT / "grammar.json", OUT / "model.json"
    if phase == "grammar":
        write_new(gpath, {**fit_grammar(), "registration_sha256": file_sha256(reg)})
        return
    raw = read(gpath)
    if raw["registration_sha256"] != file_sha256(reg):
        raise ValueError("Unregistered grammar fit")
    if phase == "fit":
        _, cases, part = shared.load_cached("fit", FIT, CACHE)
        labels = {label["id"]: label for label in part("labels")}
        if len(cases) != 96 or sum(label["answerable"] for label in labels.values()) != 48:
            raise ValueError("Unbalanced fit panel")
        write_new(mpath, {**fit_blend(cases, labels, raw["grammar"]), "grammar": raw["grammar"],
                          "grammar_sha256": file_sha256(gpath), "registration_sha256": file_sha256(reg),
                          "fit_cache_sha256": file_sha256(CACHE / "fit.cache.json")})
        return
    model = read(mpath)
    if (model["grammar_sha256"] != file_sha256(gpath) or model["registration_sha256"] != file_sha256(reg)
            or model["fit_cache_sha256"] != file_sha256(CACHE / "fit.cache.json")):
        raise ValueError("Registered model inputs changed")
    if phase == "compare":
        previous_report = CACHE / "dev.metrics.json"
        selected = read(CACHE / "selected.json")
        if selected["dev_report_sha256"] != file_sha256(previous_report):
            raise ValueError("Changed first development report")
        own = read(OUT / "dev.json")
        if own["model_sha256"] != file_sha256(mpath) or own["cache_sha256"] != file_sha256(CACHE/"dev.cache.json"):
            raise ValueError("Changed answer-slot development inputs")
        first_graded = read(previous_report)["metrics"][selected["mode"]]
        write_new(OUT / "comparison.json", {"first_selected": selected["mode"], "first_sha256": file_sha256(previous_report),
                  "slot_sha256": file_sha256(OUT / "dev.json"), "first_summary": first_graded["summary"],
                  "slot_summary": own["metrics"]["slot"]["summary"], "paired_first_to_slot": paired(first_graded, own["metrics"]["slot"])})
        return
    docs, cases, part = shared.load_cached("dev", DEV, CACHE)
    baseline = shared.predictions(cases, "baseline", None)
    rows = predict(cases, model, True)
    ablated = predict(cases, model, False)
    labels = part("labels")
    if len(cases) != 32 or sum(label["answerable"] for label in labels) != 16:
        raise ValueError("Unbalanced development panel")
    lm = {label["id"]: label for label in labels}
    ceiling = shared.diagnostics(cases, lm)
    ceiling["incumbent_accepted_source_exact"] = 0
    for c in cases:
        label = lm[c.question["id"]]
        if label["answerable"] and not c.error and not c.incumbent_error:
            _, s = select_passage(c.docs, c.original, c.full, "joint", slot.THRESHOLD)
            if s:
                i = next(i for i,d in enumerate(c.docs) if d["id"] == s.source_id)
                opts = slot.choices(c.question["question"], c.docs[i], s, c.candidates[i])
                ceiling["incumbent_accepted_source_exact"] += any(shared.exact(o,label) for o in opts)
    metrics = {k: grade(r, labels, docs) for k,r in [("joint", baseline), ("slot", rows), ("qa_only", ablated)]}
    current, previous = shared.counts(metrics["slot"]), shared.counts(metrics["joint"])
    write_new(OUT / "dev.json", {"model_sha256": file_sha256(mpath), "cache_sha256": file_sha256(CACHE/"dev.cache.json"),
              "policy": read(reg)["source_sha256"], "metrics": metrics, "rows": rows, "ceiling": ceiling,
              "paired": paired(metrics["joint"], metrics["slot"]), "grammar_ablation": paired(metrics["qa_only"], metrics["slot"]),
              "dev_improved": current[0] > previous[0] and current[1] >= previous[1] and current[2] <= previous[2]})
    print({k: shared.counts(v) for k, v in metrics.items()}, ceiling)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phase", choices=("register", "grammar", "fit", "dev", "compare"))
    run(ap.parse_args().phase)
