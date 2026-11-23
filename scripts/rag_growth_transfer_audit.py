"""Classify failures on completed English predictions, separately from policy or threshold selection."""

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.core.generation.english_consensus_reader import select_answer
from scripts import rag_growth_transfer as tr


def audit(phase, docs, cases, output):
    p = output / (phase + ".jsonl")
    summary = tr.load(output / (phase + "-report.json"))
    if tr.file_sha256(p) != summary["measured_sha256"]:
        raise ValueError("Raw predictions changed")
    rows = {r["id"]: r for r in map(json.loads, p.read_text().splitlines())}
    failures, counts = [], Counter()
    for case in cases:
        row = rows[case["id"]]
        p = row["candidate"]
        if tr.grade(case, p, docs):
            continue
        if p["status"] == "error":
            reason = "reader_error"
        elif case["impossible"]:
            reason = "answered_native_unanswerable"
        elif case["source"] not in row["hybrid_ids"]:
            reason = "missing_reference_in_retrieved_six"
        elif p["status"] == "abstained":
            reason = "abstained_despite_retrieving_reference"
        elif p["source_id"] != case["source"]:
            reason = "selected_other_passage"
        elif tr.normalize(p["answer"]) not in {tr.normalize(a["text"]) for a in case["answers"]}:
            reason = "answer_mismatch_on_reference_passage"
        else:
            reason = "official_span_outside_cited_evidence"
        counts[reason] += 1
        failures.append({"id": case["id"], "question": case["question"], "failure": reason,
                         "answer": p.get("answer"), "accepted": list(dict.fromkeys(a["text"] for a in case["answers"])),
                         "source_title": docs[p["source_id"]]["title"] if p.get("source_id") in docs else None,
                         "reference_title": docs[case["source"]]["title"]})
    metrics = summary["arms"]["candidate"]
    if sum(counts.values()) != sum(v["n"] - v["passed"] for v in metrics.values()):
        raise ValueError("Failure bins do not reconcile")
    return {"split": phase, "measured_sha256": summary["measured_sha256"],
            "n": len(cases), "strict_pass": all(v["rate"] >= .8 for v in metrics.values()),
            "candidate": metrics, "baseline": summary["arms"]["baseline"], "oracle": summary["arms"]["oracle"],
            "retrieval_source_positive": summary["retrieval_source_positive"], "failure_counts": dict(counts), "failures": failures}


def audit_tydi(corpus, root):
    if tr.file_sha256(corpus) != tr.load(root / "tydi-preregistration.json")["manifest_sha256"]:
        raise ValueError("Registered TyDi corpus changed")
    dataset = tr.load(corpus)
    docs, cases = dataset["documents"], dataset["cases"]
    dest = root / "minilm"
    report = tr.load(dest / "tydi-report.json")
    path = dest / "tydi.jsonl"
    if tr.file_sha256(path) != report["measured_sha256"]:
        raise ValueError("TyDi predictions changed")
    rows = {r["id"]: r for r in map(json.loads, path.read_text().splitlines())}
    if rows.keys() != {c["id"] for c in cases}:
        raise ValueError("Incomplete TyDi rows")
    titles = {d["title"] for d in docs.values()}
    adopted = report["selected"] == "MiniLM + DeBERTa"
    counts, examples, recall = Counter(), [], 0
    for case in cases:
        row = rows[case["id"]]
        q = case["question"]
        expected_title = next(t for t in titles if tr.key(t + "\n" + q) == case["id"])
        order = row["reranked"][:report["depth"]] if adopted else row["hybrid"][:6]
        evidence = row[str(report["depth"])] if adopted else row["baseline"]
        if isinstance(evidence, dict):
            pred = {"status": "error"}
        else:
            result = select_answer(q, [tr.SpanAnswer(**s) for s in evidence], [], "deberta", report["threshold"])
            pred = {"status": "abstained"} if result is None else {"status": "answered", **asdict(result)}
        if not case["impossible"]:
            recall += case["source"] in order
        if tr.grade(case, pred, docs):
            continue
        output_title = docs[pred["source_id"]]["title"] if pred.get("source_id") in docs else None
        if pred["status"] == "error":
            cause = "reader_error"
        elif case["impossible"]:
            cause = "answered_in_reference_article" if output_title == expected_title else "answered_from_another_article"
        elif case["source"] not in order:
            cause = "reference_not_retrieved"
        elif pred["status"] == "abstained":
            cause = "abstained_with_reference_available"
        elif pred["source_id"] != case["source"]:
            cause = "other_passage_selected"
        else:
            cause = "strict_span_or_citation_mismatch_on_reference"
        counts[cause] += 1
        examples.append({"id": case["id"], "question": q, "failure": cause, "source_title": output_title,
                         "reference_title": expected_title, "prediction": pred.get("answer"),
                         "answers": [a["text"] for a in case["answers"]]})
    if sum(counts.values()) != sum(v["n"] - v["passed"] for v in report["candidate"]["metrics"].values()):
        raise ValueError("TyDi failure bins and official grades differ")
    return {"selected": report["selected"], "sha256": report["measured_sha256"], "positive_source_recall": recall,
            "metrics": report["candidate"]["metrics"], "failure_counts": dict(counts), "failures": examples}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--tydi-corpus", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.tydi_corpus:
        result = audit_tydi(args.tydi_corpus, args.output)
        tr.dump(args.output / "minilm/tydi-failure-audit.json", result)
        print(result["failure_counts"])
        sys.exit(0)
    if args.dataset is None:
        parser.error("--dataset or --tydi-corpus is required")
    if tr.file_sha256(args.dataset) != tr.DATA_SHA:
        raise ValueError("Unexpected official source")
    stages = tr.panels(tr.load(args.dataset)["data"])
    dest = args.output / "independent-arms"
    if not all((dest / (name + "-report.json")).exists() for name in stages):
        raise ValueError("Wait until the entire frozen evaluation completes")
    result = {name: audit(name, docs, cases, dest) for name, (docs, cases) in stages.items()}
    tr.dump(dest / "failure-audit.json", result)
    print({k: v["failure_counts"] for k, v in result.items()})
