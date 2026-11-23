"""Reserve the third Korean KLUE panel without opening any previous predictions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_evidence_holdouts as h
from scripts import rag_evidence_holdouts_verify as audit

ROOT = h.ROOT
OUT = h.DEST.parent / "klue-third-reservation"
PLAN_SHA = "480f4c790bd6a59c3c7012ca29be4fa77c4b872c5f0cf48916bb09af82ff200a"
MANIFEST_SHA = "6ba7323cce907d0abd69209825724de9e9aff1feb98305a9ec01ac35bb7fc09b"
Row = dict[str, Any]


def signatures(questions: list[Row], corpus: list[Row]) -> h.tr.Footprint:
    fp = h.tr.Footprint()
    for q in questions:
        fp.question.add(h.td.fingerprint(q["question"]))
    for doc in corpus:
        fp.title.add(h.td.fingerprint(doc["title"]))
        fp.article.add(h.td.fingerprint(doc["content"]))
    return fp


def prepare(dest: Path) -> None:
    import pyarrow.parquet as pq

    if dest.exists():
        raise FileExistsError("Use an unoccupied panel directory")
    plan_path = OUT / "plan.json"
    h.verified(plan_path, PLAN_SHA)
    plan = h.load(plan_path)
    h.verified(h.DEST / "manifest.json", MANIFEST_SHA)
    old_manifest = h.load(h.DEST / "manifest.json")
    history: dict[str, str] = {}
    old, near = h.old_klue(history)
    for path, value in history.items():
        if old_manifest["exposure_input_sha256"].get(path) != value:
            raise ValueError("Prior Korean exposure record changed")
    prior = {"prior_local_klue_and_mixed": old}
    for name, metadata in old_manifest["panels"].items():
        folder = h.DEST / name
        h.verified(folder / "reservation.json", metadata["reservation_sha256"])
        for key in ("final.questions.json", "final.corpus.json"):
            h.verified(folder / key, metadata["files"][key])
        questions = h.load(folder / "final.questions.json")
        corpus = h.load(folder / "final.corpus.json")
        prior[name] = signatures(questions, corpus)
        if name.startswith("klue"):
            for doc in corpus:
                near.add(doc["content"])
        else:
            for article in h.load(folder / "reservation.json")["articles"]:
                prior[name].article.add(article["article_hash"])
                prior[name].title.add(article["title_hash"])
    # Stream only Korean source/question columns to keep the shared CPU/memory footprint small.
    from pyarrow import set_cpu_count, set_io_thread_count
    set_cpu_count(1)
    set_io_thread_count(1)
    for name, file, sha in (("tydi_validation", h.TYVAL, h.td.PARQUET_SHA),
                            ("tydi_train0", h.TYTRAIN, h.tr.TRAIN_SHA), ("tydi_train1", h.TYTRAIN1, h.TRAIN1_SHA)):
        h.verified(file, sha)
        history[str(file)] = sha
        fp = h.tr.Footprint()
        table = pq.ParquetFile(file)
        columns = ["document_plaintext", "document_title", "question_text", "passage_answer_candidates", "language"]
        for batch in table.iter_batches(batch_size=24, columns=columns, use_threads=False):
            for r in batch.to_pylist():
                if r["language"] != "korean":
                    continue
                fp.question.add(h.td.fingerprint(r["question_text"]))
                if h.td.fingerprint(r["document_plaintext"]) not in fp.article:
                    docs, _ = h.td.passages(r, None)
                    fp.include(h.tr.signatures(r, docs, question=False))
        prior[name] = fp
    blocked = h.tr.Footprint()
    for fp in prior.values():
        blocked.include(fp)
        blocked.article.update(fp.passage)
    tables = h.klue_tables()
    payload, metadata = h.choose_klue(tables, blocked, near, sizes=(80,), seed=plan["seed"])
    if (metadata["documents"], metadata["per_stratum"]) != (512, 80):
        raise ValueError("The full 80+80 and 512-article study is required")
    audit.labels_klue(payload["questions"], payload["labels"], payload["corpus"], tables[metadata["official_split"]])
    redacted = signatures(payload["questions"], payload["corpus"])
    overlaps = {k: redacted.overlap(earlier) for k, earlier in prior.items()}
    if len(redacted.article) != 512 or len(redacted.question) != 160 or any(v for group in overlaps.values() for v in group.values()):
        raise ValueError("Repeated questions/articles or overlap with a previous corpus")
    history.update({str(p): h.td.digest(p) for p in h.klue_files().values()})
    dest.parent.mkdir(exist_ok=True, parents=True)
    with TemporaryDirectory(dir=dest.parent) as tmp:
        staged = Path(tmp) / "panel"
        staged.mkdir()
        files = {}
        for key, values in payload.items():
            p = staged / f"final.{key}.json"
            p.write_bytes(h.td.encode(values))
            files[p.name] = h.td.digest(p)
        registration = {"schema_version": 1, "domain": "klue-third", **metadata, "seed": plan["seed"],
                        "files": files, "plan_sha256": PLAN_SHA, "previous_four_manifest_sha256": MANIFEST_SHA,
                        "independent_official_lookup": {"articles": 512, "questions_and_original_occurrences": 160},
                        "prior_overlap": overlaps, "input_sha256": history,
                        "code_sha256": {str(p.relative_to(ROOT)): h.td.digest(p) for p in
                                        (Path(__file__), Path(h.__file__), Path(h.kp.__file__), Path(h.tr.__file__),
                                         Path(h.td.__file__), Path(audit.__file__))},
                        "upstream_limitation": old_manifest["upstream_model_card"]["disclosed_supervision"]}
        (staged / "reservation.json").write_bytes(h.td.encode(registration))
        staged.rename(dest)
    print(metadata["official_split"], metadata["documents"], metadata["per_stratum"], h.td.digest(dest / "reservation.json"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, default=OUT / "panel")
    prepare(ap.parse_args().output)
