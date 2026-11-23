"""Prospectively bind a replication panel, two policy artifacts and two new output paths."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_evidence_holdouts_gate as primary

PANELS = {
    "klue-replication": (32, "db07b39b5e4fde3fc3d04242add95f8ebddc9bca9e57a594ed46543f66be83d3"),
    "tydi-replication": (16, "c37fb2b9e13f3ef5c26e2ed9f7e647fda394c84e4384a91c58b060db37a3851b"),
}
Row = dict[str, Any]


def identity(folder: Path, panel: str) -> Row:
    if panel not in PANELS:
        raise ValueError("Only the two registered replication panels can use this gate")
    n, expected = PANELS[panel]
    manifest = folder / "manifest.json"
    if primary.digest(manifest) != primary.REGISTERED_SHA:
        raise ValueError("Unrecognized panel manifest")
    metadata = primary.load(manifest)["panels"][panel]
    selected = folder / panel
    if (metadata.get("reserve_only") is not True or metadata["reservation_sha256"] != expected
            or primary.digest(selected / "reservation.json") != expected):
        raise ValueError("Changed replication reservation")
    files = {key: primary.digest(selected / key) for key in metadata["files"]}
    if files != metadata["files"]:
        raise ValueError("Reserved replication files changed")
    return {"panel": panel, "domain": panel, "per_stratum": n, "manifest_sha256": primary.REGISTERED_SHA,
            "reservation_sha256": expected, "files": files, "scorer_sources": {
                **primary.scorer_sources(), **primary.sources([Path(__file__)])}}


def start(folder: Path, panel: str, control: list[Path], candidate: list[Path], common: list[Path],
          control_rows: Path, candidate_rows: Path) -> None:
    info = identity(folder, panel)
    lock, score = primary.paths(folder, panel)
    before, after = primary.sources(control), primary.sources(candidate)
    if not before or not after or not common or sorted(before.values()) == sorted(after.values()):
        raise ValueError("Specify distinct policy artifacts and a common inference driver")
    rows = [control_rows.absolute(), candidate_rows.absolute()]
    if (rows[0].resolve() == rows[1].resolve() or score.exists()
            or any(p.exists() or p.is_symlink() or p.suffix not in {".json", ".jsonl"} for p in rows)
            or any(p.resolve() in {lock.resolve(), score.resolve()} for p in rows)):
        raise ValueError("Register two distinct, unoccupied JSON/JSONL output paths")
    primary.write_once(lock, {"schema_version": 1, **info, "start_unix_ns": time.time_ns(),
                              "control_sources": before, "candidate_sources": after, "common_sources": primary.sources(common),
                              "control_rows": str(rows[0].resolve()), "candidate_rows": str(rows[1].resolve())})
    print("Locked", panel, primary.digest(lock))


def check_sources(lock: Row) -> None:
    for key in ("control_sources", "candidate_sources", "common_sources"):
        if primary.sources([Path(p) for p in lock[key]]) != lock[key]:
            raise ValueError("A registered policy or driver changed")


def score(folder: Path, panel: str) -> None:
    info = identity(folder, panel)
    path, destination = primary.paths(folder, panel)
    if destination.exists():
        raise FileExistsError("Replication already scored")
    lock = primary.load(path)
    if any(lock[k] != v for k, v in info.items()):
        raise ValueError("Replication panel or scorer changed")
    check_sources(lock)
    paths = [Path(lock[key]) for key in ("control_rows", "candidate_rows")]
    if (paths[0].samefile(paths[1]) or any(p.resolve() != p or not p.is_file() or
                                           p.stat().st_mtime_ns < lock["start_unix_ns"] for p in paths)):
        raise ValueError("Only newly completed, distinct files at the registered paths are eligible")
    digests = list(map(primary.digest, paths))
    before, after = map(primary.prediction_rows, paths)
    expected = info["per_stratum"]
    if len(before) != 2*expected or len(after) != 2*expected:
        raise ValueError("Both arms must include every reserved question, including errors")
    old, new = ({r["id"]: r["retrieved"] for r in arm} for arm in (before, after))
    if len(old) != len(before) or len(new) != len(after) or old != new:
        raise ValueError("Every query needs identical retrieved document IDs in identical order")
    selected = folder / panel
    result = primary.compare(before, after, primary.load(selected / "final.labels.json"),
                             primary.load(selected / "final.corpus.json"))
    if any(result["pairs"][group]["n"] != expected for group in primary.LABELS):
        raise ValueError("Unexpected stratum size")
    if digests != list(map(primary.digest, paths)):
        raise ValueError("Prediction files changed during scoring")
    check_sources(lock)
    primary.write_once(destination, {**info, "start_lock_sha256": primary.digest(path), "control_rows_sha256": digests[0],
                                     "candidate_rows_sha256": digests[1], **result})
    print("Scored", panel, primary.digest(destination))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "score"):
        sub = commands.add_parser(name)
        sub.add_argument("--panel", choices=tuple(PANELS), required=True)
        sub.add_argument("--panels", type=Path, default=primary.DEST)
        if name == "start":
            for arm in ("control", "candidate", "common"):
                sub.add_argument(f"--{arm}-file", type=Path, action="append", required=True)
            for arm in ("control", "candidate"):
                sub.add_argument(f"--{arm}-rows", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "start":
        start(args.panels, args.panel, args.control_file, args.candidate_file, args.common_file,
              args.control_rows, args.candidate_rows)
    else:
        score(args.panels, args.panel)
