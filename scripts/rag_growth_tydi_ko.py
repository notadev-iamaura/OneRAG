"""Reserve the Korean TyDi QA Primary cross-dataset panel without running a reader."""

import argparse
import hashlib
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.rag_growth_prepare import REVISION as KLUE_REV
from scripts.rag_growth_prepare import TRAIN_SHA256, VALIDATION_SHA256
from scripts.rag_growth_transfer_tydi import PARQUET_SHA, REV

SEED = "onerag-03-tydi-korean-transfer-v1"
PROFILE_SHA = "6a337984e39217eae59fb834299c8ff9ac5c6be5f5d01317ec3903d155c36b01"
SOURCE = f"https://huggingface.co/datasets/google-research-datasets/tydiqa/resolve/{REV}/primary_task/validation-00000-of-00001.parquet"
Row = dict[str, Any]
Vote = tuple[int, int, int]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fingerprint(text: str) -> str:
    norm = unicodedata.normalize("NFKC", text).casefold().replace("_", " ")
    return sha(" ".join(norm.split()).encode())


def encode(data: Any) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def consensus(annotations: Row) -> tuple[bool, Vote | None] | None:
    votes = list(zip(annotations["passage_answer_candidate_index"], annotations["minimal_answers_start_byte"],
                     annotations["minimal_answers_end_byte"], annotations["yes_no_answer"], strict=True))
    if len(votes) != 3 or any(yn != "NONE" for _, _, _, yn in votes):
        return None
    if all((p, s, e) == (-1, -1, -1) for p, s, e, _ in votes):
        return False, None
    spans = Counter((p, s, e) for p, s, e, _ in votes if p >= 0 and 0 <= s < e)
    for span, count in spans.items():
        if count >= 2:
            return True, span
    return None


def passages(row: Row, vote: Vote | None) -> tuple[list[Row], Row]:
    raw = row["document_plaintext"].encode()
    article = sha(raw)
    candidates = row["passage_answer_candidates"]
    docs, spans = [], []
    source = None
    for i, (left, right) in enumerate(zip(candidates["plaintext_start_byte"], candidates["plaintext_end_byte"],
                                           strict=True)):
        if not 0 <= left <= right <= len(raw):
            raise ValueError("Official passage outside the article")
        body = raw[left:right].decode("utf-8")
        if not body.strip():
            continue
        doc_id = sha(f"{article}/{i}/{left}/{right}".encode())
        docs.append({"id": doc_id, "title": row["document_title"], "content": body})
        if vote and i == vote[0]:
            start_byte, end_byte = vote[1:]
            if not left <= start_byte < end_byte <= right:
                raise ValueError("Consensus span falls outside its official passage")
            text = raw[start_byte:end_byte].decode("utf-8")
            start = len(raw[left:start_byte].decode("utf-8"))
            end = start + len(text)
            if not text.strip() or body[start:end] != text:
                raise ValueError("UTF-8 minimal span does not round trip")
            source = doc_id
            spans.append({"text": text, "start": start, "end": end})
    if not docs or (vote and not spans):
        raise ValueError("Missing passages or consensus span")
    return docs, {"answerable": vote is not None, "source_id": source,
                  "answers": [s["text"] for s in spans], "spans": spans}


def reserve(rows: list[Row], prior: dict[str, set[str]], per_stratum: int) -> tuple[Row, Row]:
    selected: dict[str, set[str]] = {key: set() for key in prior}
    documents: list[Row] = []
    questions: list[Row] = []
    labels: list[Row] = []
    articles: list[Row] = []
    groups: Counter[bool] = Counter()
    pool = [(sha((r["document_title"] + "\n" + r["question_text"]).encode()), r, consensus(r["annotations"]))
            for r in rows if r["language"] == "korean"]
    for qid, row, agreement in sorted(pool, key=lambda c: sha((SEED + "/" + c[0]).encode())):
        if agreement is None:
            continue
        positive, vote = agreement
        if groups[positive] >= per_stratum:
            continue
        keys = {"question": fingerprint(row["question_text"]), "title": fingerprint(row["document_title"]),
                "article": fingerprint(row["document_plaintext"])}
        if any(key in prior[k] or key in selected[k] for k, key in keys.items()):
            continue
        docs, label = passages(row, vote)
        if any(fingerprint(d["content"]) in prior["article"] for d in docs):
            continue
        for k, key in keys.items():
            selected[k].add(key)
        documents.extend(docs)
        questions.append({"id": qid, "question": row["question_text"]})
        labels.append({"id": qid, **label})
        articles.append({"case_id": qid, "title_hash": keys["title"], "article_hash": keys["article"],
                         "question_hash": keys["question"], "passages": len(docs)})
        groups[positive] += 1
        if groups[True] == groups[False] == per_stratum:
            break
    if groups != {True: per_stratum, False: per_stratum}:
        raise ValueError(f"Insufficient distinct consensus cases for {per_stratum} per stratum")
    documents.sort(key=lambda d: d["id"])
    if len({d["id"] for d in documents}) != len(documents):
        raise ValueError("Duplicate passage ID")
    overlap = {key: len(prior[key] & values) for key, values in selected.items()}
    bodies = {fingerprint(d["content"]) for d in documents}
    overlap["passage_equal_to_klue_context"] = len(bodies & prior["article"])
    counts = Counter(g[0] for _, _, g in pool if g is not None)
    stats = {"korean_rows": len(pool), "eligible_before_exclusions": {"answerable": counts[True],
             "unanswerable": counts[False]}, "per_stratum": per_stratum, "unique_articles": len(articles),
             "passages": len(documents), "distinct_normalized_passage_texts": len(bodies),
             "articles": articles, "klue_hash_overlap": overlap,
             "klue_distinct_hashes_compared": {k: len(v) for k, v in prior.items()}}
    return {"corpus": documents, "questions": questions, "labels": labels}, stats


def prepare(args: argparse.Namespace) -> None:
    import pyarrow.parquet as pq

    if args.output.exists():
        raise ValueError("Choose an unoccupied panel directory")
    for path, expected in ((args.input, PARQUET_SHA), (args.klue_train, TRAIN_SHA256),
                           (args.klue_validation, VALIDATION_SHA256), (args.profile, PROFILE_SHA)):
        if digest(path) != expected:
            raise ValueError(f"Unregistered input: {path.name}")
    prior: dict[str, set[str]] = {key: set() for key in ("question", "title", "article")}
    for path in (args.klue_train, args.klue_validation):
        for batch in pq.ParquetFile(path).iter_batches(columns=["question", "title", "context"], batch_size=256):
            for row in batch.to_pylist():
                for scope, field in (("question", "question"), ("title", "title"), ("article", "context")):
                    prior[scope].add(fingerprint(row[field]))
    rows = pq.read_table(args.input, filters=[("language", "=", "korean")], use_threads=False).to_pylist()
    panel, stats = reserve(rows, prior, 24)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.output.parent) as temp:
        dest = Path(temp) / "reservation"
        dest.mkdir()
        files = {}
        for name, payload in panel.items():
            path = dest / f"final.{name}.json"
            path.write_bytes(encode(payload))
            files[path.name] = digest(path)
        report = {
            "schema_version": 1, "dataset": "Google Research TyDi QA v1 Primary Task Korean validation",
            "dataset_card": "https://github.com/google-research-datasets/tydiqa", "source": SOURCE,
            "revision": REV, "source_sha256": PARQUET_SHA, "seed": SEED, "files": files, **stats,
            "profile": "ko/rescue-profile.json", "profile_sha256": PROFILE_SHA,
            "script_sha256": digest(Path(__file__)), "klue_revision": KLUE_REV,
            "klue_train_sha256": TRAIN_SHA256, "klue_validation_sha256": VALIDATION_SHA256,
            "selection": "Deterministic hash order. Three annotations per case, every yes/no NONE. "
                         "Positives require two identical (passage, start byte, end byte) votes; only that "
                         "consensus span is reference. Negatives require three unanimous (-1,-1,-1) votes. "
                         "Distinct normalized questions, article titles and full bodies.",
            "evaluation": "Once, using the frozen KLUE policy, top-1 against all nonempty official candidate "
                          "passages from 48 articles. Model input is question and retrieved text. "
                          "Use the product's standard grounded exact-span and genuine abstention metrics.",
            "limitations": "Native no-answer applies to the source Wikipedia article, not an exhaustive audit "
                           "of every article in the shared pool. No negative gold passage exists. "
                           "Hash deduplication does not establish semantic uniqueness or exclude pretraining exposure. "
                           "Equal strata and strict consensus differ from the full TyDi validation distribution.",
        }
        registration = dest / "reservation.json"
        registration.write_bytes(encode(report))
        checksum = digest(registration)
        dest.rename(args.output)
    print(f"{checksum} reservation.json; {len(panel['questions'])} questions; {len(panel['corpus'])} passages")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("input", "klue-train", "klue-validation", "profile", "output"):
        parser.add_argument("--" + option, type=Path, required=True)
    prepare(parser.parse_args())
