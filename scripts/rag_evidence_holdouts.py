"""Reserve new Korean KLUE and TyDi article-disjoint panels from pinned local files."""

import argparse
import json
import math
import runpy
import sys
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_growth_ko_panels as kp
from scripts import rag_growth_tydi_ko as td
from scripts import rag_growth_tydi_ko_transfer_panels as tr
from scripts.rag_research_inputs import previous_input, research_cache

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "output/rag-growth-03"
DEST = ROOT / "output/rag-evidence-selection/panels"
CACHE = research_cache()
KLUE = CACHE / "onerag-evidence-1121"
TYVAL = CACHE / "onerag-growth03-tydi-validation.parquet"
TYTRAIN = CACHE / "onerag-growth03-tydi-train0.parquet"
TYTRAIN1 = CACHE / "onerag-evidence-tydi-train1.parquet"
TRAIN1_SHA = "669ea731c5beac5e25ce13a05473ff8b5002e2c7cfbbc28384d7a0a8732666c6"
SEED = "onerag-evidence-selection-ko-novel-01"
OLD_KLUE = "04b8885469749168a86cc3546fde0214aa956c72418f47c5a9922b0ca8ec549a"
OLD_TY = "84d12821aaa1ed48dd7af86277de71c01b19dab0a00b7af8c88510edeba41ded"
Row = dict[str, Any]


def load(path: Path) -> Any:
    return json.loads(path.read_bytes())


def verified(path: Path, expected: str) -> None:
    if td.digest(path) != expected:
        raise ValueError(f"Source checksum differs: {path.name}")


def klue_files() -> dict[str, Path]:
    return {"validation": KLUE / "klue.parquet", "train": KLUE / "klue-train.parquet"}


def klue_tables() -> dict[str, list[Row]]:
    import pyarrow.parquet as pq

    files = klue_files()
    verified(files["train"], td.TRAIN_SHA256)
    verified(files["validation"], td.VALIDATION_SHA256)
    return {k: pq.read_table(p).to_pylist() for k, p in files.items()}


def entered(fp: tr.Footprint, row: Row) -> None:
    fp.question.add(td.fingerprint(row["question"]))
    fp.title.add(td.fingerprint(row["title"]))
    fp.article.add(td.fingerprint(row["context"]))


def prev(history: dict[str, str], path: Path) -> Any:
    history[str(path)] = td.digest(path)
    return load(path)


class NearArticles:
    """Exact Jaccard verification after size and sorted common-prefix filtering."""

    def __init__(self) -> None:
        self.bodies: list[str] = []
        self.sizes: list[int] = []
        self.postings: dict[int, list[int]] = defaultdict(list)
        self.seen: set[str] = set()

    @staticmethod
    def grams(text: str) -> set[str]:
        words = kp.identity(text).split()
        return {" ".join(words[i:i+5]) for i in range(max(1, len(words) - 4))}

    @staticmethod
    def prefix(grams: set[str]) -> list[int]:
        # Process-local hash ordering is sufficient: all sets use the same total order,
        # and every candidate pair still receives an exact string comparison.
        return sorted({hash(g) for g in grams})[:len(grams) - math.ceil(4 * len(grams) / 5) + 1]

    def add(self, body: str) -> None:
        key = td.fingerprint(body)
        if key in self.seen:
            return
        self.seen.add(key)
        grams = self.grams(body)
        for g in self.prefix(grams):
            self.postings[g].append(len(self.bodies))
        self.sizes.append(len(grams))
        self.bodies.append(body)

    def contains(self, body: str) -> bool:
        if td.fingerprint(body) in self.seen:
            return True
        gs = self.grams(body)
        ids = {i for g in self.prefix(gs) for i in self.postings.get(g, ())}
        for idx in ids:
            if 5 * min(len(gs), self.sizes[idx]) < 4 * max(len(gs), self.sizes[idx]):
                continue
            old = self.grams(self.bodies[idx])
            if 5 * len(gs & old) >= 4 * len(gs | old):
                return True
        return False


def old_klue(history: dict[str, str]) -> tuple[tr.Footprint, NearArticles]:
    fp, near = tr.Footprint(), NearArticles()

    def doc(d: Row) -> None:
        fp.title.add(td.fingerprint(d["title"]))
        fp.article.add(td.fingerprint(d["content"]))
        near.add(d["content"])

    reserve = OLD / "ko-confirmation/reservation.json"
    verified(reserve, OLD_KLUE)
    registered = prev(history, reserve)["previous_files"]
    pinned = {previous_input(Path(name)): digest for name, digest in registered.items()}
    paths = set(pinned)
    for directory in (KLUE, CACHE / "onerag-generalization-dfAroNzl"):
        for pattern in ("dev*-ko.json", "holdout*-ko.json"):
            paths.update(directory.glob(pattern))
    paths.add(KLUE / "koreader/calibration.json")
    for path in sorted(paths):
        if path in pinned:
            verified(path, pinned[path])
        data = prev(history, path)
        for d in data.get("documents", data.get("docs", [])):
            doc(d)
        for row in data["cases"]:
            fp.question.add(td.fingerprint(row["question"]))
    for folder, splits in ((OLD / "panels", ("dev", "final")), (OLD / "ko-confirmation", ("final",))):
        spec = prev(history, folder / "reservation.json")
        for split in splits:
            for name in ("questions", "corpus"):
                path = folder / f"{split}.{name}.json"
                verified(path, spec["files"][path.name])
                rows = prev(history, path)
                for row in rows:
                    if name == "corpus":
                        doc(row)
                    else:
                        fp.question.add(td.fingerprint(row["question"]))
    for folder, training_splits in (
        (CACHE / "onerag-growth03-koreader/panels", ["fit", "development", "calibration", "distractors"]),
        (CACHE / "onerag-growth03-koreader/data", ["fit", "development", "calibration"]),
        (CACHE / "onerag-growth03-ko-mixed", ["fit", "calibration"]),
    ):
        for split in training_splits:
            path = folder / (split + ".jsonl")
            history[str(path)] = td.digest(path)
            for line in path.read_bytes().splitlines():
                row = json.loads(line)
                doc({"title": row["title"], "content": row["context"]})
                fp.question.add(td.fingerprint(row["question"]))
    return fp, near


def choose_klue(tables: dict[str, list[Row]], old: tr.Footprint, near: NearArticles, *,
                sizes: tuple[int, ...] = (80, 64, 48, 40, 32, 24), seed: str = SEED) -> tuple[Row, Row]:
    fp = td.fingerprint
    counts = {}
    # Completely unseen validation articles have priority. The fallback excludes even unused validation articles.
    for split in ("validation", "train"):
        eligible = [r for r in tables[split] if fp(r["question"]) not in old.question
                    and fp(r["title"]) not in old.title and fp(r["context"]) not in old.article]
        if split == "train":
            validation = tr.Footprint()
            for r in tables["validation"]:
                entered(validation, r)
                near.add(r["context"])
            eligible = [r for r in eligible if fp(r["question"]) not in validation.question
                        and fp(r["title"]) not in validation.title and fp(r["context"]) not in validation.article]
        prior = {}
        clean = []
        for r in eligible:
            body = r["context"]
            if body not in prior:
                prior[body] = not near.contains(body)
            if prior[body]:
                clean.append(r)
        counts[split] = {str(pos): len({fp(r["context"]) for r in clean if (not r["is_impossible"]) == pos})
                         for pos in (True, False)}
        for n in sizes:
            if min(counts[split].values()) < n:
                continue
            # Bound the retrieval task at the same 512-article scale if enough novel articles exist.
            for size in dict.fromkeys((512, 2*n + 16, 2*n)):
                if len(prior) < size:
                    continue
                try:
                    panels, _ = kp.reserve(clean, (set(), set(), set(), set(), {}), {"final": n}, size, seed=seed)
                except ValueError:
                    continue
                result = panels["final"]
                return result, {"official_split": split, "per_stratum": n, "documents": size,
                                "distinct_article_pool_after_prior_exclusions": counts,
                                "article_nearduplicate_cutoff": "five-word-shingle Jaccard >=0.8",
                                "new_articles_including_background": size, "all_reference_articles_distinct": True}
    raise ValueError(f"Insufficient novel KLUE articles for a 24+24 panel: {counts}")


def rows_ko(path: Path, expected: str) -> list[Row]:
    import pyarrow.parquet as pq

    verified(path, expected)
    records: list[Row] = pq.read_table(path, filters=[("language", "=", "korean")], use_threads=False).to_pylist()
    return records


def all_tydi(rows: list[Row], selected: set[str] | None = None) -> tr.Footprint:
    fp = tr.Footprint()
    for row in rows:
        article = td.fingerprint(row["document_plaintext"])
        if selected is not None and article not in selected:
            continue
        fp.question.add(td.fingerprint(row["question_text"]))
        if article not in fp.article:
            docs, _ = td.passages(row, None)
            fp.include(tr.signatures(row, docs, question=False))
    if selected is not None and fp.article != selected:
        raise ValueError("A previously reserved article could not be recovered")
    return fp


def choose_tydi(tables: dict[str, list[Row]], history: dict[str, str]) -> tuple[dict, dict, tr.Footprint]:
    first = OLD / "tydi-ko/reservation.json"
    second = OLD / "tydi-ko-retrieval/panels/reservation.json"
    verified(first, tr.FIRST_SHA)
    verified(second, OLD_TY)
    first_meta = prev(history, first)
    second_meta = prev(history, second)["panels"]
    klue = tr.Footprint()
    for records in tables.values():
        for row in records:
            entered(klue, row)
    blocked = {"entire_klue_train_and_validation": klue}
    fit_path = ROOT / "output/rag-evidence-selection/tydi-fit/reservation.json"
    verified(fit_path, "5da8532f7dc72854fa7f9280ed838f95879b3827c5c850c3846a0d04b1e9e5ea")
    fit = prev(history, fit_path)
    fit_fp = tr.Footprint()
    for article in fit["panels"]["fit"]["articles"]:
        fit_fp.title.add(article["title_hash"])
        fit_fp.article.add(article["article_hash"])
    for kind in ("questions", "corpus"):
        p = fit_path.parent / f"fit.{kind}.json"
        verified(p, fit["files"][p.name])
        for row in prev(history, p):
            if kind == "corpus":
                fit_fp.passage.add(td.fingerprint(row["content"]))
            else:
                fit_fp.question.add(td.fingerprint(row["question"]))
    blocked["registered_fit_96_including_all_candidates"] = fit_fp
    for name, path, expected in (("0", TYTRAIN, tr.TRAIN_SHA), ("1", TYTRAIN1, TRAIN1_SHA)):
        blocked["entire_korean_tydi_train_shard" + name] = all_tydi(rows_ko(path, expected))
    validation = rows_ko(TYVAL, td.PARQUET_SHA)
    blocked["previous_first_48"] = all_tydi(validation, {a["article_hash"] for a in first_meta["articles"]})
    blocked["previous_second_48_plus_16_background"] = all_tydi(
        validation, {a["article_hash"] for a in second_meta["final"]["articles"]})
    data, stats = {}, {}
    for name, n, backgrounds in (("tydi", 24, 16), ("tydi-replication", 16, 8)):
        data[name], meta, used = tr.reserve(SEED + "/" + name, validation, list(blocked.values()), n, backgrounds)
        overlaps = {key: used.overlap(old) for key, old in blocked.items()}
        if any(c for values in overlaps.values() for c in values.values()):
            raise ValueError("TyDi cross-panel leakage")
        stats[name] = {**meta, "official_split": "validation", "normalized_overlaps": overlaps,
                       "seed": tr.SEED + "/" + SEED + "/" + name, "reserve_only": name.endswith("replication")}
        blocked[name] = used
    korean_tydi = all_tydi(validation)
    for name in ("0", "1"):
        korean_tydi.include(blocked["entire_korean_tydi_train_shard" + name])
    return data, stats, korean_tydi


def prepare(dest: Path) -> None:
    if dest.exists():
        raise ValueError("Choose a new panel directory; existing reservations are immutable")
    history: dict[str, str] = {}
    tables = klue_tables()
    panels, stats, korean_tydi = choose_tydi(tables, history)
    exposed, near = old_klue(history)
    exposed.include(korean_tydi)
    exposed.article.update(korean_tydi.passage)
    klue, kmeta = choose_klue(tables, exposed, near)
    for q in klue["questions"]:
        exposed.question.add(td.fingerprint(q["question"]))
    for d in klue["corpus"]:
        exposed.title.add(td.fingerprint(d["title"]))
        exposed.article.add(td.fingerprint(d["content"]))
        near.add(d["content"])
    replication, rmeta = choose_klue(tables, exposed, near, sizes=(32,), seed=SEED + "/replication")
    del near
    panels["klue"], stats["klue"] = klue, kmeta
    panels["klue-replication"] = replication
    stats["klue-replication"] = {**rmeta, "reserve_only": True, "seed": SEED + "/replication"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=dest.parent) as tmp:
        work = Path(tmp) / "panels"
        work.mkdir()
        manifest: Row = {"schema_version": 1, "seed": SEED, "panels": {}, "exposure_input_sha256": history,
                    "source_sha256": {"klue_train": td.TRAIN_SHA256, "klue_validation": td.VALIDATION_SHA256,
                                      "tydi_validation": td.PARQUET_SHA, "tydi_train0": tr.TRAIN_SHA, "tydi_train1": TRAIN1_SHA},
                    "preparation_sha256": {p.name: td.digest(p) for p in (Path(__file__), Path(kp.__file__), Path(tr.__file__), Path(td.__file__))},
                    "legacy_klue_confirmation": {"reservation_sha256": OLD_KLUE, "consumed_in_this_study": False,
                                                "prior_background_only_reference_articles": 155, "n": 160},
                    "legacy_klue_confirmation_disposition": "Reserved for a possible different, second experiment. No compatible confirmation run or start record was present.",
                    "upstream_model_card": {"file": "models/rag-growth-03/ko-sufficiency/README.md",
                        "sha256": td.digest(ROOT / "models/rag-growth-03/ko-sufficiency/README.md"),
                        "disclosed_supervision": "KLUE-MRC 13,813 relevance rows, TyDi QA gold passage 10,519 Korean/English relevance rows. "
                                                  "Article-level training IDs are unavailable. Locally reserved official KLUE train questions may have appeared in upstream supervised training."},
                    "limitations": "Earlier local fine-tuning, evaluation and retrieval corpora were fingerprinted. "
                                   "Public pretraining, unknown upstream supervision and undocumented private exposure cannot be excluded. "
                                   "TyDi native negatives concern the originating article. Balanced strict-consensus samples differ from full official distributions."}
        for name, payload in panels.items():
            folder = work / name
            folder.mkdir()
            files = {}
            for key, values in payload.items():
                p = folder / f"final.{key}.json"
                p.write_bytes(td.encode(values))
                files[p.name] = td.digest(p)
            info = {**stats[name], "files": files}
            (folder / "reservation.json").write_bytes(td.encode(info))
            manifest["panels"][name] = {k: v for k, v in info.items() if k != "articles"}
            manifest["panels"][name]["reservation_sha256"] = td.digest(folder / "reservation.json")
        (work / "manifest.json").write_bytes(td.encode(manifest))
        work.rename(dest)
    print("manifest", td.digest(dest / "manifest.json"))
    for name, info in manifest["panels"].items():
        print(name, info["official_split"], info.get("per_stratum", info.get("questions_per_stratum")),
              info.get("documents", info.get("passages")), info["reservation_sha256"])


def reproduce_registered(dest: Path) -> None:
    """Run the byte-exact preregistered preparer and check the complete historical manifest."""
    manifest = DEST / "manifest.json"
    verified(manifest, "6ba7323cce907d0abd69209825724de9e9aff1feb98305a9ec01ac35bb7fc09b")
    expected = load(manifest)["preparation_sha256"]
    src = DEST / "registered-preparation-source.txt"
    verified(src, expected[Path(__file__).name])
    for mod in (kp, tr, td):
        path = Path(mod.__file__)
        verified(path, expected[path.name])
    with TemporaryDirectory() as scratch:
        snapshot = Path(scratch) / Path(__file__).name
        snapshot.write_bytes(src.read_bytes())
        frozen_prepare = runpy.run_path(str(snapshot))["prepare"]
        # The archived source computes project paths relative to its original repository location.
        frozen_prepare.__globals__.update(ROOT=ROOT, OLD=OLD)
        frozen_prepare(dest)
    verified(dest / "manifest.json", td.digest(manifest))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, default=DEST)
    ap.add_argument("--reproduce-registered", action="store_true")
    args = ap.parse_args()
    (reproduce_registered if args.reproduce_registered else prepare)(args.output)
