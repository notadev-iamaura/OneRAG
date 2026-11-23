"""Check every sealed source passage, annotation and span against official data without model calls."""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_evidence_holdouts as h

Row = dict[str, Any]


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def key(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def labels_klue(qrows: list[Row], labels: list[Row], docs: list[Row], raw: list[Row]) -> None:
    by_id = {r["guid"]: r for r in raw}
    corpus = {r["id"]: r for r in docs}
    sources = {(r["title"], r["context"]) for r in raw}
    require(len(corpus) == len(docs) and all((d["title"], d["content"]) in sources and
            key(d["content"].encode())[:20] == d["id"] for d in docs), "KLUE corpus altered")
    for q, label in zip(qrows, labels, strict=True):
        r = by_id[q["id"]]
        source = key(r["context"].encode())[:20]
        require(q["question"] == r["question"] and q["id"] == label["id"] and
                corpus[source]["title"] == r["title"] and label["source_id"] == source, "KLUE official source mismatch")
        positive = not r["is_impossible"]
        spans = {(i, i + len(s), s) for i, s in zip(r["answers"]["answer_start"], r["answers"]["text"], strict=True)
                 if positive and s and i >= 0 and r["context"][i:i+len(s)] == s}
        actual = {(v["start"], v["end"], v["text"]) for v in label["spans"]}
        require(spans == actual and (bool(spans) is positive is label["answerable"]) and
                {s for _, _, s in spans} == set(label["answers"]), "KLUE official answer mismatch")


def labels_tydi(qrows: list[Row], labels: list[Row], docs: list[Row], spec: Row, raw: list[Row]) -> None:
    by_case = {key((r["document_title"] + "\n" + r["question_text"]).encode()): r for r in raw}
    by_body = {h.td.fingerprint(r["document_plaintext"]): r for r in raw}
    expected = {}
    anchors = {}
    official_articles = {r["case_id"]: r for r in spec["articles"] if r["role"] == "question"}
    for entry in spec["articles"]:
        r = by_body[entry["article_hash"]]
        body = r["document_plaintext"].encode()
        ranges = r["passage_answer_candidates"]
        for i, (left, right) in enumerate(zip(ranges["plaintext_start_byte"], ranges["plaintext_end_byte"], strict=True)):
            s = body[left:right].decode()
            if s.strip():
                doc_id = key(f"{key(body)}/{i}/{left}/{right}".encode())
                expected[doc_id] = (r["document_title"], s)
                anchors[(entry["article_hash"], i)] = (doc_id, left, right)
    require(expected == {r["id"]: (r["title"], r["content"]) for r in docs} and len(expected) == len(docs),
            "TyDi candidate list is not all original nonempty passages")
    for q, lab in zip(qrows, labels, strict=True):
        r = by_case[q["id"]]
        article = h.td.fingerprint(r["document_plaintext"])
        require(lab["id"] == q["id"] and q["question"] == r["question_text"] and
                official_articles[q["id"]]["article_hash"] == article, "TyDi original question or article mismatch")
        ann = r["annotations"]
        votes = list(zip(ann["passage_answer_candidate_index"], ann["minimal_answers_start_byte"],
                         ann["minimal_answers_end_byte"], ann["yes_no_answer"], strict=True))
        require(len(votes) == 3 and all(v[3] == "NONE" for v in votes), "Unexpected official ballot")
        if lab["answerable"]:
            (p, left, right, _), agreements = Counter(votes).most_common(1)[0]
            require(agreements >= 2 and p >= 0 and 0 <= left < right, "TyDi incomplete span consensus")
            doc_id, start, end = anchors[(article, p)]
            require(start <= left < right <= end, "Official byte interval lies outside selected passage")
            raw_bytes = r["document_plaintext"].encode()
            answer = raw_bytes[left:right].decode()
            begin, stop = (len(raw_bytes[start:i].decode()) for i in (left, right))
            require(expected[doc_id][1][begin:stop] == answer and lab["source_id"] == doc_id and
                    lab["answers"] == [answer] and lab["spans"] == [{"start": begin, "end": stop, "text": answer}],
                    "TyDi official Unicode extraction mismatch")
        else:
            require(votes == [(-1, -1, -1, "NONE")] * 3 and lab["source_id"] is None
                    and lab["spans"] == lab["answers"] == [], "Negative was not three all-null native ballots")


def verify(base: Path) -> Row:
    import pyarrow.parquet as pq

    manifest = h.load(base / "manifest.json")
    val = h.rows_ko(h.TYVAL, h.td.PARQUET_SHA)
    klue = pq.read_table(h.klue_files()["train"]).to_pylist()
    scopes, reports = {}, {}
    for name, expected in manifest["panels"].items():
        folder = base / name
        h.verified(folder / "reservation.json", expected["reservation_sha256"])
        for f, sha in expected["files"].items():
            h.verified(folder / f, sha)
        qs, labels, docs = (h.load(folder / ("final." + k + ".json")) for k in ("questions", "labels", "corpus"))
        require(len({r["id"] for r in qs}) == len(qs) == len(labels), "Incorrect case denominator")
        require(Counter(r["answerable"] for r in labels) == {True: len(qs)//2, False: len(qs)//2},
                "Strata are not balanced")
        if name.startswith("tydi"):
            labels_tydi(qs, labels, docs, h.load(folder / "reservation.json"), val)
        else:
            labels_klue(qs, labels, docs, klue)
        scopes[name] = ({h.td.fingerprint(r["question"]) for r in qs},
                        {h.td.fingerprint(r["title"]) for r in docs}, {h.td.fingerprint(r["content"]) for r in docs})
        require(len(scopes[name][0]) == len(qs), "Duplicate normalized question")
        reports[name] = {"audited_cases": len(labels), "audited_articles": len(scopes[name][1]),
                         "audited_full_corpus_documents": len(docs), "positive_cases": len(qs)//2,
                         "negative_cases": len(qs)//2}
    overlap = {}
    for left, right in combinations(sorted(scopes), 2):
        overlap[left + "/" + right] = [len(a & b) for a, b in zip(scopes[left], scopes[right], strict=True)]
        require(not any(overlap[left + "/" + right]), "Overlapping question, title or document across panels")
    return {"manifest_sha256": h.td.digest(base / "manifest.json"), "verification_code_sha256": h.td.digest(Path(__file__)),
            "panels": reports, "overlap_counts_question_title_document": overlap, "inference_calls": 0}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--panels", type=Path, default=h.DEST)
    args = ap.parse_args()
    result = verify(args.panels)
    report = args.panels / ("verification-" + result["verification_code_sha256"][:12] + ".json")
    raw = h.td.encode(result)
    if report.exists():
        require(report.read_bytes() == raw, "The prior provenance report differs")
    else:
        with NamedTemporaryFile(dir=args.panels) as f:
            f.write(raw)
            f.flush()
            os.link(f.name, report)
    print(json.dumps(result["panels"]))
