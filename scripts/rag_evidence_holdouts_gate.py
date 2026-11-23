"""Lock one blind trial before inference; score two complete arms on the registered panel."""

import argparse
import json
import os
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.rag_evidence_holdouts import DEST, ROOT, load
from scripts.rag_growth_ko_eval import checked_span, grade
from scripts.rag_growth_tydi_ko import digest, encode

LABELS = ("answerable", "unanswerable")
REGISTERED_SHA = "6ba7323cce907d0abd69209825724de9e9aff1feb98305a9ec01ac35bb7fc09b"
Row = dict[str, Any]


def write_once(path: Path, data: Row) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent) as raw:
        raw.write(encode(data))
        raw.flush()
        os.fsync(raw.fileno())
        os.link(raw.name, path)


def sources(paths: list[Path]) -> dict[str, str]:
    return {str(p.resolve()): digest(p) for p in paths}


def panel_identity(folder: Path, domain: str) -> Row:
    manifest = folder / "manifest.json"
    if digest(manifest) != REGISTERED_SHA:
        raise ValueError("This is not the prospectively registered panel manifest")
    meta = load(manifest)["panels"][domain]
    if domain not in ("klue", "tydi") or meta.get("reserve_only"):
        raise ValueError("Primary trial only; replication requires its own prospective registration")
    selected = folder / domain
    files = {name: digest(selected / name) for name in meta["files"]}
    if files != meta["files"] or digest(selected / "reservation.json") != meta["reservation_sha256"]:
        raise ValueError("Panel changed after it was reserved")
    return {"manifest_sha256": digest(manifest), "domain": domain, "files": files,
            "reservation_sha256": meta["reservation_sha256"]}


def scorer_sources() -> dict[str, str]:
    return sources([Path(__file__), ROOT / "scripts/rag_evidence_holdouts.py", ROOT / "scripts/rag_growth_ko_eval.py",
                    ROOT / "scripts/rag_growth_gate.py", ROOT / "scripts/rag_growth_local.py",
                    ROOT / "scripts/rag_growth_ko_panels.py", ROOT / "scripts/rag_growth_tydi_ko.py"])


def paths(folder: Path, domain: str) -> tuple[Path, Path]:
    # The state directory is fixed per dataset, outside the immutable reservation.
    trial = folder.parent / "paired-trials" / domain
    return trial / "started.json", trial / "score.json"


def start(folder: Path, domain: str, control: list[Path], candidate: list[Path], common: list[Path]) -> None:
    before, after = sources(control), sources(candidate)
    if not before or not after or sorted(before.values()) == sorted(after.values()):
        raise ValueError("Supply distinct control and candidate provenance files")
    lock, _ = paths(folder, domain)
    write_once(lock, {"schema_version": 1, **panel_identity(folder, domain), "scorer_sources": scorer_sources(),
                      "control_sources": before, "candidate_sources": after, "common_sources": sources(common),
                      "start_unix_ns": time.time_ns()})
    print("Locked", domain, digest(lock))


def prediction_rows(path: Path) -> list[Row]:
    if path.suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    else:
        data = load(path)
        rows = data["rows"] if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows:
        raise ValueError("A prediction file needs every case, including errors")
    return rows


def compare(before: list[Row], after: list[Row], labels: list[Row], corpus: list[Row]) -> Row:
    bodies = {d["id"]: d["content"] for d in corpus}
    if any(r["status"] == "answered" and not checked_span(r, bodies) for r in before + after):
        raise ValueError("Answered rows must contain the original range in a retrieved passage; export failed generation as error")
    if any(r["status"] == "abstained" and (not r["retrieved"] or any(r.get(k) for k in
           ("source_id", "answer", "start", "end", "quote", "quote_start", "quote_end", "citations", "cited_evidence")))
           for r in before + after):
        raise ValueError("A refusal must have completed retrieval and carry no answer/citation")
    scored = {name: grade(rows, labels, corpus) for name, rows in (("control", before), ("candidate", after))}
    decided = {name: {r["id"]: r["correct"] for r in report["outcomes"]} for name, report in scored.items()}
    pos = {r["id"]: r["answerable"] for r in labels}
    old, new = ({r["id"]: r for r in arm} for arm in (before, after))
    pairs = {}
    for label, flag in zip(LABELS, (True, False), strict=True):
        ids = sorted(q for q, v in pos.items() if v is flag)
        better = [q for q in ids if decided["candidate"][q] and not decided["control"][q]]
        worse = [q for q in ids if not decided["candidate"][q] and decided["control"][q]]
        pairs[label] = {"n": len(ids), "gained_ids": better, "lost_ids": worse, "same": len(ids)-len(better)-len(worse),
                        "status_transitions": dict(Counter(f"{old[q]['status']}->{new[q]['status']}" for q in ids))}
    summary = {name: v["summary"] for name, v in scored.items()}
    candidate, control = summary["candidate"], summary["control"]
    return {"summaries": summary, "pairs": pairs,
            "identical_retrieval_order": sum(old[q]["retrieved"] == new[q]["retrieved"] for q in pos),
            "n": len(pos), "absolute_both_at_least_80": candidate["both_at_least_80"],
            "candidate_no_loss_vs_control_both": all(candidate[k]["correct"] >= control[k]["correct"] for k in LABELS),
            "candidate_has_no_more_errors": candidate["statuses"].get("error", 0) <= control["statuses"].get("error", 0)}


def score(folder: Path, domain: str, before: Path, after: Path) -> None:
    lockfile, output = paths(folder, domain)
    lock = load(lockfile)
    if output.exists():
        raise FileExistsError("Both arms already scored")
    identity = panel_identity(folder, domain)
    if any(lock[k] != v for k, v in identity.items()) or lock["scorer_sources"] != scorer_sources():
        raise ValueError("Measurement or scorer identity changed")
    for key in ("control_sources", "candidate_sources", "common_sources"):
        if sources([Path(p) for p in lock[key]]) != lock[key]:
            raise ValueError("A frozen policy artifact changed")
    if before.samefile(after) or any(p.stat().st_mtime_ns < lock["start_unix_ns"] for p in (before, after)):
        raise ValueError("Provide separate newly written control and candidate outputs")
    before_rows, after_rows = prediction_rows(before), prediction_rows(after)
    selected = folder / domain
    result = compare(before_rows, after_rows, load(selected / "final.labels.json"), load(selected / "final.corpus.json"))
    write_once(output, {**identity, "start_lock_sha256": digest(lockfile), "control_rows_sha256": digest(before),
                        "candidate_rows_sha256": digest(after), **result})
    print("Scored", domain, digest(output))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    commands = ap.add_subparsers(dest="command", required=True)
    for command in ("start", "score"):
        sub = commands.add_parser(command)
        sub.add_argument("--panels", type=Path, default=DEST)
        sub.add_argument("--panel", choices=("klue", "tydi"), required=True)
        if command == "start":
            for flag in ("control", "candidate", "common"):
                sub.add_argument("--" + flag + "-file", type=Path, action="append", default=[], required=flag != "common")
        else:
            for flag in ("control", "candidate"):
                sub.add_argument("--" + flag + "-rows", type=Path, required=True)
    args = ap.parse_args()
    if args.command == "start":
        start(args.panels, args.panel, args.control_file, args.candidate_file, args.common_file)
    else:
        score(args.panels, args.panel, args.control_rows, args.candidate_rows)
