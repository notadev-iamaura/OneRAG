"""Reserve disjoint Korean TyDi reader development and confirmation panels from official passages."""

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_growth_tydi_ko as td

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "output/rag-growth-03"
SEED = "onerag-03-tydi-ko-retrieval-independent-v1"
TRAIN_SHA = "700742a20446def778bc9a0cbc3b352767e6744a5095cade74916aa4bec8545f"
MIXED_SHA = "4e02ca7f3a9bf708247d9e071f181222b2ac1613d53bdabe0aed90f358540ff1"
FIRST_SHA = "4879a255fb57806aceb6e0a86b8673dd666f584f3a07d9495d039a4cace750f5"
Row = dict[str, Any]


@dataclass
class Footprint:
    question: set[str] = field(default_factory=set)
    title: set[str] = field(default_factory=set)
    article: set[str] = field(default_factory=set)
    passage: set[str] = field(default_factory=set)

    def include(self, other: "Footprint") -> None:
        for key in vars(self):
            getattr(self, key).update(getattr(other, key))

    def overlap(self, other: "Footprint") -> dict[str, int]:
        return {"question": len(self.question & other.question), "title": len(self.title & other.title),
                "full_article": len(self.article & other.article), "passage": len(self.passage & other.passage),
                "article_to_passage": len(self.article & other.passage),
                "passage_to_article": len(self.passage & other.article)}


def qid(row: Row) -> str:
    return hashlib.sha256((row["document_title"] + "\n" + row["question_text"]).encode()).hexdigest()


def signatures(row: Row, docs: list[Row], *, question: bool) -> Footprint:
    return Footprint({td.fingerprint(row["question_text"])} if question else set(),
                     {td.fingerprint(row["document_title"])}, {td.fingerprint(row["document_plaintext"])},
                     {td.fingerprint(d["content"]) for d in docs})


def single(annotations: Row) -> tuple[bool, td.Vote | None] | None:
    votes = list(zip(annotations["passage_answer_candidate_index"], annotations["minimal_answers_start_byte"],
                     annotations["minimal_answers_end_byte"], annotations["yes_no_answer"], strict=True))
    if len(votes) != 1:
        return None
    p, left, right, yn = votes[0]
    if yn != "NONE":
        return None
    if (p, left, right) == (-1, -1, -1):
        return False, None
    if p >= 0 and 0 <= left < right:
        return True, (p, left, right)
    return None


def reserve(split: str, rows: list[Row], blocked: list[Footprint], count: int, backgrounds: int
            ) -> tuple[Row, Row, Footprint]:
    taken = Footprint()
    docs: list[Row] = []
    questions: list[Row] = []
    labels: list[Row] = []
    articles: list[Row] = []
    groups: Counter[bool] = Counter()
    for role in ("question", "background"):
        ranked = sorted(rows, key=lambda r: td.sha(f"{SEED}/{split}/{role}/{qid(r)}".encode()))
        for row in ranked:
            if role == "question" and groups[True] == groups[False] == count:
                break
            if role == "background" and len(articles) == 2 * count + backgrounds:
                break
            if role == "question":
                status = (single if split == "dev" else td.consensus)(row["annotations"])
                if status is None or groups[status[0]] >= count:
                    continue
                positive, vote = status
            else:
                positive, vote = False, None
            # Exclude whole articles. Dropping individual candidate passages would change the retrieval task.
            if td.fingerprint(row["document_title"]) in taken.title:
                continue
            passages, label = td.passages(row, vote)
            fp = signatures(row, passages, question=role == "question")
            if any(any(fp.overlap(other).values()) for other in [*blocked, taken]):
                continue
            taken.include(fp)
            key = qid(row)
            docs.extend(passages)
            articles.append({"role": role, "case_id": key if role == "question" else None,
                             "article_hash": next(iter(fp.article)), "title_hash": next(iter(fp.title)),
                             "question_hash": next(iter(fp.question), None), "passages": len(passages)})
            if role == "question":
                questions.append({"id": key, "question": row["question_text"]})
                labels.append({"id": key, **label})
                groups[positive] += 1
    if groups != {True: count, False: count} or len(articles) != 2 * count + backgrounds:
        raise ValueError(f"Insufficient disjoint {split} articles")
    if len({d["id"] for d in docs}) != len(docs):
        raise ValueError("Duplicate retrieval passage identifiers")
    return ({"questions": questions, "labels": labels, "corpus": sorted(docs, key=lambda d: d["id"])},
            {"questions_per_stratum": count, "question_articles": len(questions), "background_articles": backgrounds,
             "passages": len(docs), "articles": articles}, taken)


def prepare(args: argparse.Namespace) -> None:
    import pyarrow.parquet as pq

    if args.output.exists():
        raise ValueError("Refusing to overwrite a panel directory")
    pins = {args.train: TRAIN_SHA, args.validation: td.PARQUET_SHA, args.klue_train: td.TRAIN_SHA256,
            args.klue_validation: td.VALIDATION_SHA256, args.first: FIRST_SHA, args.mixed_manifest: MIXED_SHA}
    for path, expected in pins.items():
        if td.digest(path) != expected:
            raise ValueError(f"Unregistered source: {path.name}")
    prior: dict[str, Footprint] = {"klue_all": Footprint(), "first_tydi_48": Footprint()}
    for path in (args.klue_train, args.klue_validation):
        for batch in pq.ParquetFile(path).iter_batches(columns=["question", "title", "context"], batch_size=256):
            for row in batch.to_pylist():
                old = prior["klue_all"]
                old.question.add(td.fingerprint(row["question"]))
                old.title.add(td.fingerprint(row["title"]))
                old.article.add(td.fingerprint(row["context"]))
    mixed = json.loads(args.mixed_manifest.read_bytes())["splits"]
    for key, required in (("fit", 512), ("calibration", 64)):
        path = args.mixed_root / (key + ".jsonl")
        if mixed[key]["sha256"] != td.digest(path):
            raise ValueError("Mixed training / calibration input differs from its release")
        pins[path] = mixed[key]["sha256"]
        samples = [json.loads(line) for line in path.read_bytes().splitlines()]
        if len(samples) != mixed[key]["n"] or len(samples) != required:
            raise ValueError("Incomplete mixed training / calibration file")
        old = prior["mixed_" + key] = Footprint()
        for row in samples:
            old.question.add(td.fingerprint(row["question"]))
            old.title.add(td.fingerprint(row["title"]))
            old.article.add(row["article"])
            old.passage.add(td.fingerprint(row["context"]))
    rows = {name: pq.read_table(path, filters=[("language", "=", "korean")], use_threads=False).to_pylist()
            for name, path in (("dev", args.train), ("final", args.validation))}
    # Recover past article text only via registered hashes. No earlier questions, answers or model results are inputs.
    registered = {r["case_id"]: r for r in json.loads(args.first.read_bytes())["articles"]}
    recovered: set[str] = set()
    full_validation = Footprint()
    for row in rows["final"]:
        docs, _ = td.passages(row, None)
        fp = signatures(row, docs, question=True)
        full_validation.include(fp)
        key = qid(row)
        if key in registered:
            meta = registered[key]
            if (meta["title_hash"] not in fp.title or meta["article_hash"] not in fp.article
                    or meta["question_hash"] not in fp.question):
                raise ValueError("First TyDi reservation does not match pinned official source")
            prior["first_tydi_48"].include(fp)
            recovered.add(key)
    if recovered != registered.keys() or len(recovered) != 48:
        raise ValueError("First 48 registered articles were not recovered")
    # Expand every mixed TyDi training article into all its official passages for the overlap audit.
    for row in rows["dev"]:
        article = td.fingerprint(row["document_plaintext"])
        for key in ("mixed_fit", "mixed_calibration"):
            if article in prior[key].article:
                docs, _ = td.passages(row, None)
                prior[key].passage.update(td.fingerprint(d["content"]) for d in docs)
    dev, dev_meta, dev_fp = reserve("dev", rows["dev"], [*prior.values(), full_validation], 16, 16)
    final, final_meta, final_fp = reserve("final", rows["final"], [*prior.values(), dev_fp], 24, 16)
    comparisons = {name: {key: fp.overlap(old) for key, old in prior.items()} for name, fp in
                   (("dev", dev_fp), ("final", final_fp))}
    comparisons["dev"]["entire_korean_tydi_primary_validation"] = dev_fp.overlap(full_validation)
    comparisons["final"]["new_tydi_train_development"] = final_fp.overlap(dev_fp)
    if any(n for scopes in comparisons.values() for values in scopes.values() for n in values.values()):
        raise ValueError("Cross-reservation collision")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.output.parent) as temp:
        dest = Path(temp) / "panels"
        dest.mkdir()
        files = {}
        for split, data in (("dev", dev), ("final", final)):
            for key, payload in data.items():
                filename = f"{split}.{key}.json"
                (dest/filename).write_bytes(td.encode(payload))
                files[filename] = td.digest(dest/filename)
        meta = {"schema_version": 1, "dataset": "Google Research TyDi QA primary_task Korean", "revision": td.REV,
                "seed": SEED, "source_sha256": {p.name: v for p, v in pins.items()}, "files": files,
                "preparation_sha256": {"script": td.digest(Path(__file__)), "shared": td.digest(Path(td.__file__))},
                "panels": {"dev": dev_meta, "final": final_meta}, "normalized_hash_overlaps": comparisons,
                "supervision": {"dev": "Train shard 0, exactly one annotation; negatives are single-rater article-level NULL",
                                "final": "Validation, exactly three no-yes/no annotations; positives need two identical "
                                         "passage/byte span votes; negatives need three unanimous article-level NULL votes"},
                "scope": "Fixed corpus of all nonempty official candidate passages of the selected question and "
                         "background articles. No gold article for runtime. Exclusion uses whole normalized questions, "
                         "article titles, full bodies and candidate passages (SHA-256 after NFKC/casefold, underscore and "
                         "whitespace normalization). Semantic duplicates or pretraining exposure are not ruled out.",
                "development_exposure": "Prepared after the original 48-question TyDi result existed. The preparer "
                                        "read an independent sample of the original result for post-run reporting. "
                                        "New cases are chosen by hash without human inspection, scoring or model calls."}
        (dest/"reservation.json").write_bytes(td.encode(meta))
        checksum = td.digest(dest/"reservation.json")
        dest.rename(args.output)
    print(checksum, {"dev_passages": len(dev["corpus"]), "final_passages": len(final["corpus"])})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg, default in (("train", "/tmp/onerag-growth03-tydi-train0.parquet"),
        ("validation", "/tmp/onerag-growth03-tydi-validation.parquet"), ("mixed-root", "/tmp/onerag-growth03-ko-mixed"),
        ("mixed-manifest", ROUND/"ko-mixed/data.json"), ("first", ROUND/"tydi-ko/reservation.json"),
        ("klue-train", "/tmp/onerag-evidence-1121/klue-train.parquet"),
        ("klue-validation", "/tmp/onerag-evidence-1121/klue.parquet"), ("output", ROUND/"tydi-ko-retrieval/panels")):
        parser.add_argument("--"+arg, type=Path, default=Path(default))
    prepare(parser.parse_args())
