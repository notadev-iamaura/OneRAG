"""Reserve disjoint Korean growth panels from the pinned public KLUE-MRC release."""

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from tempfile import TemporaryDirectory

TRAIN_SHA256 = "45fcfd50b99aed4cd55c8c5856e42aa4a5139808cc36b36994b3c1991aca93dd"
VALIDATION_SHA256 = "f576c924f471702a6fa3369d314bea2e47545c56736f371a2adb90ed15913738"
REVISION = "349481ec73fff722f88e0453ca05c77a447d967c"
PANEL_SIZES = {"dev-a": (8, 4), "dev-b": (8, 4), "final": (24, 12), "replication": (24, 12)}


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def identity(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def fingerprint(documents):
    return digest(json.dumps(documents, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def parquet_rows(path, expected_hash):
    import pyarrow.parquet as parquet

    with path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != expected_hash:
            raise ValueError(f"unexpected KLUE source hash: {path}")
        source.seek(0)
        return parquet.read_table(source).to_pylist()


def build_panels(rows, validation, previous, round_id, sizes=PANEL_SIZES, corpus_size=512):
    """Reserve questions, article titles and article text across all panels, including distractors."""
    used_titles = {identity(row["title"]) for row in validation}
    used_texts = {identity(row["context"]) for row in validation}
    used_questions = {identity(row["question"]) for row in validation}
    for panel in previous:
        docs = panel["documents"] if "documents" in panel else panel["docs"]
        used_titles.update(identity(doc["title"]) for doc in docs)
        used_texts.update(identity(doc["content"]) for doc in docs)
        used_questions.update(identity(case["question"]) for case in panel["cases"])

    ordered = sorted(rows, key=lambda row: digest(f'{round_id}/{row["guid"]}'))
    panels = {}
    for name, (answerable, unanswerable) in sizes.items():
        needs = {False: answerable, True: unanswerable}
        documents, cases = [], []
        for with_questions in (True, False):
            for row in ordered:
                if (with_questions and not any(needs.values())) or len(documents) == corpus_size:
                    break
                question = identity(row["question"])
                impossible = row["is_impossible"]
                if with_questions and (not needs[impossible] or question in used_questions):
                    continue
                title, body = identity(row["title"]), identity(row["context"])
                if not title or not body or title in used_titles or body in used_texts:
                    continue
                doc_id = digest(row["context"])[:20]
                spans = []
                if with_questions and not impossible:
                    for start, text in zip(row["answers"]["answer_start"], row["answers"]["text"], strict=True):
                        if text and start >= 0 and row["context"].startswith(text, start):
                            span = {"document_id": doc_id, "start": start, "text": text}
                            if span not in spans:
                                spans.append(span)
                    if not spans:
                        continue
                used_titles.add(title)
                used_texts.add(body)
                documents.append({"id": doc_id, "title": row["title"], "content": row["context"]})
                if with_questions:
                    used_questions.add(question)
                    needs[impossible] -= 1
                    cases.append({
                        "id": row["guid"], "question": row["question"], "answerable": not impossible,
                        "answers": [] if impossible else sorted(set(row["answers"]["text"])),
                        "source_ids": [] if impossible else [doc_id],
                        "context_source_id": doc_id, "answer_spans": spans,
                    })
        if any(needs.values()) or len(documents) != corpus_size:
            raise ValueError(f"insufficient distinct KLUE articles for {name}")
        # The order in the index must not disclose which articles supplied the labels.
        documents.sort(key=lambda doc: doc["id"])
        panels[name] = {
            "cases": cases, "documents": documents, "corpus_sha256": fingerprint(documents),
            "dataset": f"klue-mrc/{REVISION}/{round_id}/{name}",
            "split": "development" if name.startswith("dev-") else "holdout",
        }
    return panels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", required=True, type=Path)
    parser.add_argument("--validation", required=True, type=Path)
    parser.add_argument("--exclude-panel", action="append", type=Path, default=[],
                        help="Earlier growth manifests or legacy Korean article panels. Repeat as needed.")
    parser.add_argument("--round", required=True, help="Fixed sampling seed and round identifier.")
    parser.add_argument("--model", required=True, help="Model ID served on loopback.")
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path, help="New directory for all four panels.")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{64}", args.model_sha256):
        parser.error("--model-sha256 must be a lowercase SHA-256 digest")
    dest = args.output_dir
    try:
        if dest.exists():
            raise ValueError(f"output directory already exists: {dest}")
        previous = []
        exclusions = []
        for path in args.exclude_panel:
            raw = path.read_bytes()
            previous.append(json.loads(raw))
            exclusions.append(hashlib.sha256(raw).hexdigest())
        panels = build_panels(parquet_rows(args.train, TRAIN_SHA256),
                              parquet_rows(args.validation, VALIDATION_SHA256), previous, args.round)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=dest.parent) as temp:
            stage = Path(temp) / "panels"
            stage.mkdir()
            for name, panel in panels.items():
                manifest = {
                    "schema_version": 1, "trials": 3, "index": "onerag-ko-bm25-linked-v1",
                    "model": args.model, "model_sha256": args.model_sha256, **panel,
                    "reservation": {"train_sha256": TRAIN_SHA256, "validation_sha256": VALIDATION_SHA256,
                                    "excluded_panel_sha256": sorted(exclusions), "round": args.round},
                }
                (stage / f"{name}.json").write_text(json.dumps(manifest, ensure_ascii=False) + "\n",
                                                    encoding="utf-8")
            stage.rename(dest)
    except (OSError, ValueError, KeyError, ImportError) as exc:
        parser.exit(2, f"panel reservation failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
