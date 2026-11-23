"""Lock and score both arms of the third prospective Korean KLUE experiment."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_evidence_replication_gate as replication
from scripts import rag_evidence_third_klue as third

primary = replication.primary
DOMAIN = "klue-third"
RESERVATION_SHA = "6374416aa98be475c57abe0a7b300d97c9d75581cfe56537e8f33dbf87f4cc14"
TRIAL = third.OUT.parent / "paired-trials" / DOMAIN
Row = dict[str, Any]


def identity() -> Row:
    folder = third.OUT / "panel"
    third.h.verified(third.OUT / "plan.json", third.PLAN_SHA)
    third.h.verified(folder / "reservation.json", RESERVATION_SHA)
    meta = primary.load(folder / "reservation.json")
    if ((meta["domain"], meta["documents"], meta["per_stratum"], meta["plan_sha256"]) !=
            (DOMAIN, 512, 80, third.PLAN_SHA) or meta["previous_four_manifest_sha256"] != third.MANIFEST_SHA):
        raise ValueError("Unexpected third-panel definition")
    for name, expected in meta["files"].items():
        third.h.verified(folder / name, expected)
    for name, expected in meta["code_sha256"].items():
        third.h.verified(third.ROOT / name, expected)
    return {"domain": DOMAIN, "panel": DOMAIN, "manifest_sha256": third.MANIFEST_SHA, "reservation_sha256": RESERVATION_SHA,
            "files": meta["files"], "plan_sha256": third.PLAN_SHA, "n": 160, "per_stratum": 80,
            "scorer_sources": {**primary.scorer_sources(), **primary.sources([Path(__file__), Path(replication.__file__)])}}


def start(control: list[Path], candidate: list[Path], common: list[Path], before: Path, after: Path) -> None:
    record = identity()
    policies = [primary.sources(items) for items in (control, candidate, common)]
    if not all(policies) or sorted(policies[0].values()) == sorted(policies[1].values()):
        raise ValueError("Freeze distinct policies and their common inference driver")
    if (before.resolve() == after.resolve() or (TRIAL/"score.json").exists() or
            any(p.exists() or p.is_symlink() or p.suffix not in {".json", ".jsonl"}
                or p.resolve().is_relative_to(TRIAL.resolve()) for p in (before, after))):
        raise ValueError("Register two distinct empty output paths outside the lock directory")
    lock = TRIAL / "started.json"
    primary.write_once(lock, {**record, "start_unix_ns": time.time_ns(), "control_sources": policies[0],
                              "candidate_sources": policies[1], "common_sources": policies[2],
                              "control_rows": str(before.resolve()), "candidate_rows": str(after.resolve())})
    print("Locked", DOMAIN, primary.digest(lock))


def score() -> None:
    record, lockfile, scorefile = identity(), TRIAL / "started.json", TRIAL / "score.json"
    if scorefile.exists():
        raise FileExistsError("Third panel already scored")
    locked = primary.load(lockfile)
    if any(locked[k] != v for k,v in record.items()):
        raise ValueError("Third-panel scoring or reservation changed")
    replication.check_sources(locked)
    files = [Path(locked[k]) for k in ("control_rows", "candidate_rows")]
    if (files[0].samefile(files[1]) or any(p.resolve() != p or not p.is_file()
            or p.stat().st_mtime_ns < locked["start_unix_ns"] for p in files)):
        raise ValueError("Both registered predictions must have been produced after locking")
    sha = list(map(primary.digest, files))
    before, after = map(primary.prediction_rows, files)
    if not len(before) == len(after) == record["n"]:
        raise ValueError("All 160 questions are required in both arms")
    ranks = [{r["id"]: r["retrieved"] for r in rows} for rows in (before, after)]
    if len(ranks[0]) != record["n"] or ranks[0] != ranks[1]:
        raise ValueError("Both arms must have identical question IDs and ordered retrieval results")
    panel = third.OUT / "panel"
    result = primary.compare(before, after, primary.load(panel / "final.labels.json"), primary.load(panel / "final.corpus.json"))
    if any(result["pairs"][k]["n"] != record["per_stratum"] for k in primary.LABELS):
        raise ValueError("Both strata must contain all 80 reserved questions")
    if sha != list(map(primary.digest, files)):
        raise ValueError("A prediction file changed during scoring")
    replication.check_sources(locked)
    primary.write_once(scorefile, {**record, **result, "start_lock_sha256": primary.digest(lockfile),
                                   "control_rows_sha256": sha[0], "candidate_rows_sha256": sha[1]})
    print("Scored", DOMAIN, primary.digest(scorefile))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="phase", required=True)
    for name in ("start", "score"):
        parser = sub.add_parser(name)
        parser.add_argument("--panel", choices=[DOMAIN], required=True)
        if name == "start":
            for k in ("control", "candidate", "common"):
                parser.add_argument(f"--{k}-file", type=Path, action="append", required=True)
            for k in ("control", "candidate"):
                parser.add_argument(f"--{k}-rows", type=Path, required=True)
    args = p.parse_args()
    if args.phase == "start":
        start(args.control_file, args.candidate_file, args.common_file, args.control_rows, args.candidate_rows)
    else:
        score()
