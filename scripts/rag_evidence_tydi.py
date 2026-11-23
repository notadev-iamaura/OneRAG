"""Fit evidence-only rank weights on official TyDi train and measure a frozen candidate beside the baseline."""

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))

from app.modules.core.generation import tydi_evidence_selection as policy
from app.modules.core.generation.korean_passage_selection import select_passage
from app.modules.core.generation.korean_span_reader import SpanAnswer
from scripts.rag_evidence_tydi_cache import OLD, OUT, collect, read
from scripts.rag_growth_gate import normalized
from scripts.rag_growth_ko_eval import grade, write_new
from scripts.rag_growth_local import file_sha256


@dataclass
class Query:
    question: dict
    docs: list
    candidates: list
    original: list
    full: list
    sentences: dict
    error: str | None
    incumbent_error: str | None = None


def register(args):
    code = [
        Path(__file__), ROOT / "scripts/rag_evidence_tydi_cache.py", Path(policy.__file__),
        ROOT / "app/modules/core/generation/tydi_evidence_spans.py",
        ROOT / "app/modules/core/generation/english_span_proposals.py",
        ROOT / "app/modules/core/generation/korean_span_reader.py",
        ROOT / "app/modules/core/generation/korean_passage_selection.py",
        ROOT / "app/modules/core/generation/passage_sufficiency.py",
        ROOT / "app/modules/core/retrieval/retrievers/korean_hybrid_passage.py",
        ROOT / "app/modules/core/retrieval/retrievers/local_span_retriever.py",
        ROOT / "scripts/rag_growth_ko_eval.py", ROOT / "scripts/rag_growth_gate.py",
    ]
    return {
        "code_sha256": {str(p.relative_to(ROOT)): file_sha256(p) for p in code},
        "fit_reservation_sha256": file_sha256(args.fit_panels / "reservation.json"),
        "dev_reservation_sha256": file_sha256(args.dev_panels / "reservation.json"),
        "final_reservation_sha256": file_sha256(args.final_panels / "reservation.json"),
        "common_panels_sha256": file_sha256(args.final_panels.parent / "manifest.json"),
        "previous_product_file_hashes": file_sha256(OLD / "run/policy-registration.json"),
        "dev_prediction_cache_sha256": file_sha256(args.output / "dev.cache.json"),
        "modes": list(policy.MODES), "features": list(policy.NAMES),
        "retrieval_depth": 8, "nbest": 6, "document_support_min": 0, "max_span_margin_min": policy.THRESHOLD,
        "fit": "One L2 logistic evidence ranker, C=0.5; each question has equal total weight before "
               "balancing target classes. Fit on separate 48+48 official training questions. No QA or verifier weights change.",
        "choose": "Rank by highest weaker development stratum, total correct, fewer errors, then order of modes. "
                  "Use exactly one finalist even when the development target is missed. No final tuning.",
    }


def lines(path):
    return {r["id"]: r for r in map(json.loads, path.read_text().splitlines())}


def load_cached(name, panels, out):
    metadata = read(out / (name + ".cache.json"))
    if metadata["panel_sha256"] != file_sha256(panels / "reservation.json") or any(
        file_sha256(out / f) != expected for f, expected in metadata["files"].items()
    ):
        raise ValueError("Changed registered panel or model output")
    def load_part(suffix):
        key = f"{name}.{suffix}.json"
        if file_sha256(panels / key) != read(panels / "reservation.json")["files"][key]:
            raise ValueError("Changed source material")
        return read(panels / key)
    docs, qs = load_part("corpus"), load_part("questions")
    by_id = {d["id"]: d for d in docs}
    ranks = read(out / (name + ".ranks.json"))
    spans = lines(out / (name + ".spans.jsonl"))
    scores = lines(out / (name + ".support.jsonl"))
    previous = ({r["id"]: r["values"] for r in read(OLD / "run/dev.spans.json")} if name == "dev" else {})
    if not (ranks.keys() == spans.keys() == scores.keys() == {q["id"] for q in qs}):
        raise ValueError("Incomplete genuine inference coverage")
    cases = []
    for q in qs:
        qid = q["id"]
        rr, ss, sc = ranks[qid], spans[qid], scores[qid]
        err = ss.get("error") or sc.get("error")
        groups = [[SpanAnswer(**v) for v in g] for g in ss.get("candidates", [])]
        if name == "dev":
            base = [SpanAnswer(**{**previous[qid][k], "document_index": i}) for i, k in enumerate(rr)]
        elif name == "final":
            base = [SpanAnswer(**s) for s in ss.get("incumbent_spans", [])]
        else:
            base = [g[0] for g in groups]
        full = sc.get("full", [])
        cases.append(Query(q, [by_id[k] for k in rr], groups, base, full, sc.get("sentence", {}), err,
                           ss.get("incumbent_error") or (None if len(full) == len(base) == 8 else "Missing direct-arm evidence")))
    return docs, cases, load_part


def exact(span, label):
    return (label["answerable"] and span.source_id == label["source_id"]
            and normalized(span.answer) in {normalized(a) for a in label["answers"]}
            and any(span.quote_start <= s["start"] < s["end"] <= span.quote_end
                    and span.start < s["end"] and s["start"] < span.end for s in label["spans"]))


def fit_ranker(cases, labels):
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    x, y, weights, positives = [], [], [], 0
    for case in cases:
        if case.error:
            raise ValueError(f"Cannot fit on incomplete measurements: {case.question['id']}")
        label = labels[case.question["id"]]
        opts, features = policy.evidence(case.question["question"], case.docs, case.candidates, case.full, case.sentences)
        targets = [int(exact(o, label)) for o in opts]
        positives += int(any(targets))
        count = sum(targets)
        for vector, v in zip(features, targets, strict=True):
            if count and len(targets) != count:
                w = .5 / (count if v else len(targets) - count)
            else:
                w = 1 / len(targets)
            x.append(vector)
            y.append(v)
            weights.append(w)
    if not positives or set(y) != {0, 1}:
        raise ValueError("Training articles did not provide real positive and negative evidence")
    X, targets, weight = np.asarray(x), np.asarray(y), np.asarray(weights)
    total = weight.sum()
    for value in (0, 1):
        ix = targets == value
        weight[ix] *= .5 * total / weight[ix].sum()
    mean = np.average(X, weights=weight, axis=0)
    scale = np.sqrt(np.average((X-mean)**2, weights=weight, axis=0))
    scale[scale < 1e-6] = 1.
    estimator = LogisticRegression(C=.5, solver="liblinear", random_state=431).fit((X-mean)/scale, targets, sample_weight=weight)
    return {"features": list(policy.NAMES), "weights": estimator.coef_[0].tolist(), "mean": mean.tolist(),
            "scale": scale.tolist(), "logistic_intercept": float(estimator.intercept_[0]), "fit_questions": len(cases),
            "fit_spans": len(y), "questions_with_exact_candidate": positives}


def predictions(cases, mode, fitted):
    rows = []
    for case in cases:
        row = {"id": case.question["id"], "retrieved": [d["id"] for d in case.docs]}
        try:
            error = case.incumbent_error if mode == "baseline" else case.error
            if error:
                raise ValueError(error)
            if mode == "baseline":
                _, span = select_passage(case.docs, case.original, case.full, "joint", policy.THRESHOLD)
            else:
                span = policy.decide(case.question["question"], case.docs, case.candidates, case.full, case.sentences, mode, fitted)
            if span is not None:
                policy.valid(case.docs[span.document_index], span)
                row.update(status="answered", **asdict(span))
            else:
                row["status"] = "abstained"
        except Exception as exc:
            row.update(status="error", error=f"{type(exc).__name__}: {exc}"[:200])
        rows.append(row)
    return rows


def counts(graded):
    s = graded["summary"]
    return s["answerable"]["correct"], s["unanswerable"]["correct"], s["statuses"].get("error", 0)


def selection_key(mode, values):
    a, n, errors = counts(values)
    return min(a, n), a+n, -errors, -policy.MODES.index(mode)


def diagnostics(cases, labels):
    scores = {"reference_in_top8": 0, "gold_doc_support_above_zero": 0,
              "gold_doc_direct_qa_above_fixed_margin": 0, "gold_doc_above_both_fixed_gates": 0,
              "direct_top1_spans": 0, "nbest_exact": 0, "expanded_exact": 0,
              "expanded_exact_and_above_both_fixed_gates": 0, "positive_n": 0}
    for c in cases:
        label = labels[c.question["id"]]
        if not label["answerable"]:
            continue
        scores["positive_n"] += 1
        source_index = next((i for i, d in enumerate(c.docs) if d["id"] == label["source_id"]), None)
        scores["reference_in_top8"] += source_index is not None
        qualified = False
        if source_index is not None and not c.incumbent_error:
            relevant = c.full[source_index] > 0
            supported = c.original[source_index].score > policy.THRESHOLD
            qualified = relevant and supported
            scores["gold_doc_support_above_zero"] += relevant
            scores["gold_doc_direct_qa_above_fixed_margin"] += supported
            scores["gold_doc_above_both_fixed_gates"] += qualified
        if not c.error:
            scores["direct_top1_spans"] += any(exact(s, label) for s in c.original)
            scores["nbest_exact"] += any(exact(s, label) for g in c.candidates for s in g)
            options, _ = policy.evidence(c.question["question"], c.docs, c.candidates, c.full, c.sentences)
            has_exact = any(exact(s, label) for s in options)
            scores["expanded_exact"] += has_exact
            scores["expanded_exact_and_above_both_fixed_gates"] += has_exact and qualified
    return scores


def run(args):
    d = args.output
    registration = register(args)
    locked = d / "registration.json"
    if args.phase == "register":
        write_new(locked, registration)
        return
    if read(locked) != registration:
        raise ValueError("Training/selection code, policy or development inputs changed")
    if args.phase == "select":
        _, fit, fitpart = load_cached("fit", args.fit_panels, d)
        docs, dev, devpart = load_cached("dev", args.dev_panels, d)
        train_labels = {label["id"]: label for label in fitpart("labels")}
        labels = devpart("labels")
        if len(fit) != 96 or len(dev) != 32 or sum(label["answerable"] for label in train_labels.values()) != 48:
            raise ValueError("Expected 48+48 train and balanced 32 development questions")
        fitted = fit_ranker(fit, train_labels)
        write_new(d / "ranker.json", fitted)
        graded = {}
        for mode in ("baseline", *policy.MODES):
            rows = predictions(dev, mode, fitted)
            write_new(d / ("dev." + mode + ".json"), rows)
            graded[mode] = grade(rows, labels, docs)
        selected = max(policy.MODES, key=lambda m: selection_key(m, graded[m]))
        report = {"metrics": graded, "ceiling": diagnostics(dev, {label["id"]: label for label in labels}),
                  "selected": selected, "fit_cache_sha256": file_sha256(d / "fit.cache.json"),
                  "fit_reservation_sha256": registration["fit_reservation_sha256"]}
        write_new(d / "dev.metrics.json", report)
        write_new(d / "selected.json", {"mode": selected, "ranker_sha256": file_sha256(d / "ranker.json"),
                  "registration_sha256": file_sha256(locked), "dev_report_sha256": file_sha256(d / "dev.metrics.json"),
                  "final_reservation_sha256": file_sha256(args.final_panels / "reservation.json")})
        print(selected, {m: counts(v) for m, v in graded.items()}, report["ceiling"], flush=True)
        return
    frozen = read(d / "selected.json")
    if (frozen["registration_sha256"] != file_sha256(locked)
            or frozen["ranker_sha256"] != file_sha256(d / "ranker.json")
            or frozen["dev_report_sha256"] != file_sha256(d / "dev.metrics.json")
            or frozen["final_reservation_sha256"] != file_sha256(args.final_panels / "reservation.json")
            or frozen["mode"] != read(d / "dev.metrics.json")["selected"]):
        raise ValueError("Held-out policy or data registration changed")
    paired_lock = read(args.final_panels.parent.parent / "paired-trials/tydi/started.json")
    if (paired_lock["domain"] != "tydi" or paired_lock["reservation_sha256"] != frozen["final_reservation_sha256"]
            or paired_lock["manifest_sha256"] != registration["common_panels_sha256"]):
        raise ValueError("The shared one-shot independent run must be locked first")
    if args.phase == "audit":
        grade_file = args.final_panels.parent.parent / "paired-trials/tydi/score.json"
        if not grade_file.exists():
            raise ValueError("Only audit the independent panel after its paired scores are recorded")
        _, cases, part = load_cached("final", args.final_panels, d)
        labels = {label["id"]: label for label in part("labels")}
        write_new(d / "final.ceiling.json", {"common_score_sha256": file_sha256(grade_file),
                  "selected_sha256": file_sha256(d / "selected.json"), "counts": diagnostics(cases, labels)})
        return
    # The two raw arms are written before any independent label file is read by the common grader.
    collect("final", args.final_panels, d)
    _, cases, _ = load_cached("final", args.final_panels, d)
    if len(cases) < 48:
        raise ValueError("Incomplete reserved confirmation")
    model = read(d / "ranker.json")
    for output_name, mode in (("baseline", "baseline"), ("candidate", frozen["mode"])):
        write_new(d / ("final." + output_name + ".json"), predictions(cases, mode, model))
    print("Independent baseline and candidate complete:", len(cases), frozen["mode"], flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=("register", "select", "final", "audit"))
    p.add_argument("--output", type=Path, default=OUT)
    p.add_argument("--fit-panels", type=Path, default=OUT.parent / "tydi-fit")
    p.add_argument("--dev-panels", type=Path, default=OLD / "panels")
    p.add_argument("--final-panels", "--panels", type=Path, default=OUT.parent / "panels/tydi")
    run(p.parse_args())
