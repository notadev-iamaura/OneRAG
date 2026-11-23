"""Select public training articles for within-document Korean evidence ranking."""

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_growth_tydi_ko as td
from scripts import rag_growth_tydi_ko_transfer_panels as transfer


def prepare(data_root: Path, output: Path) -> None:
    import pyarrow.parquet as pq

    old = transfer.ROUND
    train = data_root / "onerag-growth03-tydi-train0.parquet"
    additional_train = data_root / "onerag-evidence-tydi-train1.parquet"
    valid = data_root / "onerag-growth03-tydi-validation.parquet"
    mixed = old / "ko-mixed/data.json"
    reservation = old / "tydi-ko-retrieval/panels/reservation.json"
    inputs = {train: transfer.TRAIN_SHA,
              additional_train: "669ea731c5beac5e25ce13a05473ff8b5002e2c7cfbbc28384d7a0a8732666c6",
              valid: td.PARQUET_SHA, mixed: transfer.MIXED_SHA,
              reservation: "84d12821aaa1ed48dd7af86277de71c01b19dab0a00b7af8c88510edeba41ded"}
    history = json.loads(mixed.read_bytes())["splits"]
    for split in ("fit", "calibration"):
        inputs[data_root / "onerag-growth03-ko-mixed" / f"{split}.jsonl"] = history[split]["sha256"]
    for name, checksum in (("klue-train.parquet", td.TRAIN_SHA256), ("klue.parquet", td.VALIDATION_SHA256)):
        inputs[data_root / "onerag-evidence-1121" / name] = checksum
    for path, expected in inputs.items():
        if td.digest(path) != expected:
            raise ValueError(f"Input changed: {path.name}")
    if output.exists():
        raise FileExistsError(output)

    previous = json.loads(reservation.read_bytes())["panels"]["dev"]["articles"]
    blocked = {key: transfer.Footprint() for key in ("validation", "reader_training", "past_development", "klue")}
    for row in previous:
        footprint = blocked["past_development"]
        footprint.article.add(row["article_hash"])
        footprint.title.add(row["title_hash"])
        if row["question_hash"]:
            footprint.question.add(row["question_hash"])
    for path in inputs:
        if path.suffix == ".jsonl":
            for line in path.read_bytes().splitlines():
                sample = json.loads(line)
                footprint = blocked["reader_training"]
                footprint.question.add(td.fingerprint(sample["question"]))
                footprint.article.add(sample["article"])
                footprint.title.add(td.fingerprint(sample["title"]))
                footprint.passage.add(td.fingerprint(sample["context"]))
        elif path.name.startswith("klue"):
            for batch in pq.ParquetFile(path).iter_batches(batch_size=128, columns=["question", "title", "context"]):
                for sample in batch.to_pylist():
                    footprint = blocked["klue"]
                    footprint.question.add(td.fingerprint(sample["question"]))
                    footprint.title.add(td.fingerprint(sample["title"]))
                    footprint.article.add(td.fingerprint(sample["context"]))

    columns = ["document_title", "document_plaintext", "question_text", "passage_answer_candidates"]
    # No validation annotations are read, even for the exclusion audit.
    validation = pq.read_table(valid, columns=columns, filters=[("language", "=", "korean")], use_threads=False)
    for batch in validation.to_batches(32):
        for row in batch.to_pylist():
            docs, _ = td.passages(row, None)
            blocked["validation"].include(transfer.signatures(row, docs, question=True))
    del validation
    train_rows = [
        row for shard in (train, additional_train)
        for row in pq.read_table(shard, columns=[*columns, "annotations"], filters=[("language", "=", "korean")],
                                 use_threads=False).to_pylist()
    ]
    for row in train_rows:
        article = td.fingerprint(row["document_plaintext"])
        for key in ("reader_training", "past_development"):
            if article in blocked[key].article:
                docs, _ = td.passages(row, None)
                blocked[key].include(transfer.signatures(row, docs, question=True))
    panel, stats, selected = transfer.reserve("dev", train_rows, list(blocked.values()), count=48, backgrounds=16)
    overlap = {k: selected.overlap(v) for k, v in blocked.items()}
    if any(n for counts in overlap.values() for n in counts.values()):
        raise ValueError("Training data overlaps previous supervision or protected validation data")

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as tmp:
        dest = Path(tmp) / "panel"
        dest.mkdir()
        files = {}
        for key, rows in panel.items():
            path = dest / f"fit.{key}.json"
            path.write_bytes(td.encode(rows))
            files[path.name] = td.digest(path)
        manifest = {"dataset": "Google TyDi QA primary task, Korean, official train shards 0 and 1", "revision": td.REV,
                    "purpose": "Evidence selection fit only. Not a test set. Single native training annotation.",
                    "seed": transfer.SEED, "ordering": "Existing dev ordering, excluding previously selected articles.",
                    "files": files, "inputs": {str(p.name): h for p, h in inputs.items()},
                    "panels": {"fit": stats}, "overlap": overlap, "selector_source_sha256": td.digest(Path(__file__)),
                    "upstream_selector_sha256": td.digest(Path(transfer.__file__))}
        (dest / "reservation.json").write_bytes(td.encode(manifest))
        dest.rename(output)
    print(f"{len(panel['questions'])} questions, {len(panel['corpus'])} passages, "
          f"manifest sha256 {td.digest(output / 'reservation.json')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.data_root, args.output)
