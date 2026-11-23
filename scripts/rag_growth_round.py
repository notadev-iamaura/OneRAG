"""Compare the registered policies on two development panels before opening either holdout."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import rag_growth_gate as gate
from scripts import rag_growth_local as local
from scripts.rag_growth_prepare import PANEL_SIZES, identity

ROOT = Path(__file__).resolve().parents[1]


def source_digest():
    files = [*ROOT.joinpath("app").rglob("*.py"), *ROOT.joinpath("app/config").rglob("*.yaml"),
             *(ROOT / "scripts" / f"rag_growth_{step}.py" for step in ("gate", "integrity", "local", "round")),
             ROOT / "uv.lock"]
    versions = {str(path.relative_to(ROOT)): local.file_sha256(path) for path in sorted(files)}
    return local.json_sha256(versions)


def reserve(directory):
    hashes, seen = {}, set()
    shared = None
    for name, (positives, negatives) in PANEL_SIZES.items():
        raw = (directory / f"{name}.json").read_bytes()
        manifest = gate.read_manifest(raw)
        local.validate_manifest(manifest)
        expected_split = "development" if name.startswith("dev-") else "holdout"
        n = sum(case["answerable"] for case in manifest["cases"])
        if (manifest["split"] != expected_split or n != positives
                or len(manifest["cases"]) - n != negatives):
            raise ValueError(f"{name}: unexpected split or denominator")
        env = (manifest["model"], manifest["model_sha256"], manifest["index"])
        if shared and env != shared:
            raise ValueError("Model or index configuration differs across panels")
        shared = env
        keys = {("question", identity(c["question"])) for c in manifest["cases"]}
        keys.update(("case_id", c["id"]) for c in manifest["cases"])
        for field in ("id", "title", "content"):
            keys.update((field, identity(d[field])) for d in manifest["documents"])
        if keys & seen:
            raise ValueError(f"{name}: a question or article overlaps a previous panel")
        seen.update(keys)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    return hashes


def run(args):
    panels, output = args.panels, args.output_dir
    hashes = reserve(panels)
    code = source_digest()
    output.mkdir(parents=True, exist_ok=False)
    summary = {"policy_code_sha256": code, "manifests": hashes, "panels": {},
               "decision": "incomplete", "release_certified": False}
    report_path = output / "round.json"

    def save():
        draft = report_path.with_suffix(".tmp")
        draft.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        draft.replace(report_path)

    save()
    for name in PANEL_SIZES:
        if name == "final":
            if not all(summary["panels"][dev]["eligible"] for dev in ("dev-a", "dev-b")):
                summary["decision"] = "rejected_on_development"
                save()
                return 1
            # Record exposure before the first inference, including interrupted attempts.
            with (panels / "holdout-opened.json").open("x", encoding="utf-8") as receipt:
                json.dump({"manifests": hashes, "policy_code_sha256": code}, receipt)
        manifest = panels / f"{name}.json"
        if local.file_sha256(manifest) != hashes[name] or source_digest() != code:
            raise ValueError("Registered inputs or policy code changed during evaluation")
        prefix = output / name
        prefix.mkdir()
        registered = json.loads(manifest.read_bytes())
        provenance = prefix / "provenance.json"
        provenance.write_text(json.dumps({
            "api_model": registered["model"], "agent_sha256": local.agent_sha256(),
            "runner_sha256": local.file_sha256(Path(local.__file__)),
            "index_sha256": local.index_sha256(registered["documents"]),
        }, indent=2) + "\n", encoding="utf-8")
        before, after = prefix / "baseline.jsonl", prefix / "candidate.jsonl"
        subprocess.run([sys.executable, str(ROOT / "scripts/rag_growth_local.py"),
                        "--manifest", str(manifest), "--baseline", str(before), "--candidate", str(after),
                        "--port", str(args.port), "--model-file", str(args.model_file)], check=True)
        if local.file_sha256(manifest) != hashes[name] or source_digest() != code:
            raise ValueError("Registered inputs or policy code changed during inference")
        report = prefix / "comparison.json"
        result = gate.main(["--manifest", str(manifest), "--baseline", str(before), "--candidate",
                            str(after), "--expected-provenance", str(provenance), "--output", str(report)])
        if result not in (0, 1):
            raise ValueError(f"{name}: invalid evidence; see {report}")
        details = json.loads(report.read_bytes())
        summary["panels"][name] = {key: details[key] for key in ("eligible", "decision", "reasons")}
        save()
    passed = all(p["eligible"] for p in summary["panels"].values())
    summary["decision"] = "confirmed_korean_document_policy" if passed else "rejected_on_holdout"
    save()
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panels", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-file", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--propose", action="store_true",
                        help="Draft a local, review-only hypothesis after the development comparisons.")
    try:
        args = parser.parse_args()
        decision = run(args)
        if args.propose:
            from scripts import rag_growth_propose

            draft = args.output_dir / "proposal.json"
            proposal_code = rag_growth_propose.main([
                "--panels", str(args.panels), "--run-dir", str(args.output_dir),
                "--model-file", str(args.model_file), "--port", str(args.port), "--output", str(draft),
            ])
            if proposal_code == 2:
                return 2
        return decision
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"growth round incomplete: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
