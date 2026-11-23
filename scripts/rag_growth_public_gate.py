"""Regrade the five registered Korean and English panels without starting a model.

Run with python -m scripts.rag_growth_public_gate. Exit 0 passes all ten
observed rates, 1 is a valid miss, and 2 means missing or invalid evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.modules.core.generation.english_consensus_reader import select_answer
from scripts import rag_growth_ko_eval as ko
from scripts import rag_growth_transfer as en
from scripts.rag_growth_local import ROOT, json_sha256

Row = dict[str, Any]
SUITE = ROOT / "output/rag-growth-03/public-suite.json"
SUITE_SHA = "5ec25f08f76e278ad635eda7f817cde3868c8b68d9bca270feddead9471c3d9e"
REQUIRED = {"klue_ko_final": 80, "tydi_ko_final": 24, "squad_en_primary": 32,
            "squad_en_confirmation": 32, "tydi_en_original": 24}
GROUPS = ("answerable", "unanswerable")
EN_GROUPS = ("positive", "negative")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def parse(raw: bytes) -> Any:
    def reject_constant(name: str) -> None:
        raise ValueError(f"Nonfinite JSON value: {name}")

    return json.loads(raw, parse_constant=reject_constant)


class Evidence:
    def __init__(self, root: Path):
        self.root = root
        self.hashes: dict[str, str] = {}

    def load(self, name: str, *, digest: str | None = None, path: Path | None = None) -> Any:
        raw = (path or self.root / name).read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if digest is not None:
            require(actual == digest, f"SHA-256 differs: {name}")
        self.hashes[name] = actual
        return [parse(line) for line in raw.splitlines()] if name.endswith(".jsonl") else parse(raw)


def verify_rows(rows: list[Row], ids: list[str]) -> None:
    require(bool(ids) and all(isinstance(i, str) and i for i in ids) and len(set(ids)) == len(ids)
            and [r["id"] for r in rows] == ids, "Missing, repeated, reordered or unregistered sample ID")


def scoring_source_digest() -> str:
    return json_sha256({
        "english_grader": inspect.getsource(en.grade),
        "english_normalizer": inspect.getsource(en.normalize),
        "english_selector": Path(inspect.getfile(select_answer)).read_text(encoding="utf-8"),
        "span_choice": inspect.getsource(en.EnglishSpanReader.choose),
        "korean_grader": inspect.getsource(ko.grade),
        "korean_normalizer": inspect.getsource(ko.normalized),
        "korean_anchor": inspect.getsource(ko.checked_span),
    })


def shared_policies(regs: Row, hashes: dict[str, str], plans: Row) -> dict[str, str]:
    # Dataset preparation and grader versions are pinned individually. Inference must match.
    identities = []
    for key in ("klue_ko_final", "tydi_ko_final"):
        plan = plans[key]
        frozen = regs[plan["freeze"]]
        require(frozen["reservation_sha256"] == hashes[plan["reservation"]]
                and frozen["model_files"]["profile"] == hashes["ko/rescue-profile.json"],
                f"Korean policy is not bound to the registered profile and panel: {key}")
        shared_files = {k: v for k, v in frozen["policy_files"].items()
                        if Path(k).name not in {"rag_growth_ko_eval.py", "rag_growth_tydi_ko.py"}}
        identities.append({k: frozen[k] for k in ("adapter", "top_k", "device", "model_files", "packages")} |
                          {"shared_files": shared_files})
    require(identities[0] == identities[1], "Korean inference policies differ")
    selection = regs["transfer/selected-for-final.json"]
    two_reader = regs["transfer/two-reader/preregistration.json"]
    squad = regs[plans["squad_en_primary"]["freeze"]]
    tydi = regs[plans["tydi_en_original"]["freeze"]]
    development = regs["transfer/minilm/development-report.json"]
    require(selection["policy_sha256"] == hashes["transfer/two-reader/frozen-policy.json"]
            and squad["development_selection_sha256"] == hashes["transfer/selected-for-final.json"]
            and squad["upstream_registration_sha256"] == hashes["transfer/two-reader/preregistration.json"]
            and development["protocol_sha256"] == hashes[plans["tydi_en_original"]["freeze"]]
            and development["adopt"] is False and squad["use_review"] is False
            and selection["mode"] == squad["mode"] == "deberta"
            and selection["threshold"] == squad["threshold"] == -2
            and all(tydi["inputs"][k] == two_reader["weights"][k] for k in ("deberta", "embedding")),
            "The original English policy is not shared across the three panels")
    return {"ko": json_sha256(identities[0]), "en": selection["policy_sha256"]}


def check_counts(observed: Row, correct: int, n: int, *, korean: bool) -> None:
    key, rate, scale = ("correct", "percent", 100) if korean else ("passed", "rate", 1)
    require(type(observed[key]) is int and observed[key] == correct
            and type(observed["n"]) is int and observed["n"] == n and n > 0
            and math.isclose(observed[rate], scale * correct / n, rel_tol=1e-12, abs_tol=1e-12),
            "Published numerator, denominator or rate differs from independent regrade")


def panel_summary(ids: list[str], strata: list[bool], verdicts: list[bool], errors: Row, n: int) -> Row:
    result: Row = {"sample_ids": ids, "sample_ids_sha256": json_sha256(ids), "errors": errors}
    require(len(ids) == len(strata) == len(verdicts) and set(errors) <= set(ids), "Invalid verdict coverage")
    for group, positive in zip(GROUPS, (True, False), strict=True):
        scores = [passed for observed, passed in zip(strata, verdicts, strict=True) if observed is positive]
        require(len(scores) == n and n > 0, f"Wrong stratum denominator: {group}")
        correct = sum(scores)
        result[group] = {"correct": correct, "n": n, "percent": 100 * correct / n,
                         "passes": 5 * correct >= 4 * n}
    result["passed"] = all(result[g]["passes"] for g in GROUPS)
    return result


def error_reason(pred: Row, field: str) -> str:
    reason = pred.get(field)
    require(isinstance(reason, str) and bool(reason.strip()), "Recorded model error lacks its reason")
    return str(reason)


def grade_korean(files: Evidence, regs: Row, plan: Row) -> Row:
    reservation, frozen = regs[plan["reservation"]], regs[plan["freeze"]]
    receipt = files.load(plan["freeze"] + ".started")
    require(receipt["freeze_sha256"] == files.hashes[plan["freeze"]]
            and Path(receipt["output"]).as_posix().endswith("/" + plan["result"]),
            "Korean final disagrees with its one-run start receipt")
    parts = {}
    for key in ("questions", "corpus", "labels"):
        name = f"final.{key}.json"
        file = str(Path(plan["reservation"]).with_name(name))
        parts[key] = files.load(file, digest=reservation["files"][name])
    data = files.load(plan["result"])
    require(data["split"] == "final" and data["identity"] == frozen, "Wrong Korean policy or split")
    ids = [q["id"] for q in parts["questions"]]
    rows = data["rows"]
    verify_rows(rows, ids)
    corpus_ids = {doc["id"] for doc in parts["corpus"]}
    for row in rows:
        hits = row["tool_retrieved"]
        require(isinstance(hits, list) and len(hits) == len(set(hits)) and set(hits) <= corpus_ids
                and hits[:frozen["top_k"]] == row["retrieved"],
                "Unregistered Korean retrieval depth or order")
        require((row["status"] == "error") == bool(row.get("error")), "Korean error and status conflict")
        if row["status"] == "abstained":
            require(not any(key in row for key in (*ko.SPAN_FIELDS, "citations", "cited_evidence")),
                    "Korean abstention carries an answer or citation")
    graded = ko.grade(rows, parts["labels"], parts["corpus"])
    require(data["outcomes"] == graded["outcomes"] and data["summary"]["statuses"] == graded["summary"]["statuses"],
            "Published Korean case outcomes or statuses differ")
    errors = {r["id"]: error_reason(r, "error") for r in rows if r["status"] == "error"}
    result = panel_summary(ids, [o["answerable"] for o in graded["outcomes"]],
                           [o["correct"] for o in graded["outcomes"]], errors, plan["per_stratum"])
    for group in GROUPS:
        check_counts(data["summary"][group], result[group]["correct"], result[group]["n"], korean=True)
    return result


def check_ranking(ids: list[str], docs: Row, expected: int, *, allow_empty: bool = False) -> None:
    require(isinstance(ids, list) and len(ids) == len(set(ids)) and set(ids) <= docs.keys()
            and (len(ids) == min(expected, len(docs)) or (allow_empty and not ids)),
            "Missing, repeated or unknown document in a registered ranking")


def english_prediction(case: Row, row: Row, docs: Row, tydi: bool) -> tuple[Row, list[str]]:
    if not tydi:
        pred, ranking = row["candidate"], row["hybrid_ids"]
        check_ranking(ranking, docs, 6, allow_empty=pred["status"] == "error")
        return pred, ranking
    ranking = row["hybrid"]
    check_ranking(ranking, docs, 20)
    first = row["baseline"]
    if isinstance(first, dict):
        return {"status": "error", "reason": error_reason(first, "error")}, ranking[:6]
    require([s["source_id"] for s in first] == ranking[:6]
            and [s["document_index"] for s in first] == list(range(len(ranking[:6]))),
            "TyDi baseline did not read the registered top six in order")
    selected = select_answer(case["question"], [en.SpanAnswer(**s) for s in first], [], "deberta", -2)
    return ({"status": "abstained"} if selected is None else {"status": "answered", **asdict(selected)}), ranking[:6]


def grade_english(files: Evidence, regs: Row, plan: Row, docs: Row, cases: list[Row], *,
                  tydi: bool, report_digest: str) -> Row:
    registration = regs[plan["reservation"]]
    spec = registration if tydi else registration["panels"][plan["split"]]
    require(spec["questions_per_stratum"] == plan["per_stratum"], "Panel stratum size differs from registration")
    if not tydi:
        require(json_sha256([docs, cases]) == spec["manifest_sha256"], "SQuAD article and sample manifest changed")
    ids = spec["case_ids"]
    verify_rows(cases, ids)
    report = files.load(plan["report"], digest=report_digest)
    require(report["protocol_sha256"] == files.hashes[plan["freeze"]], "English run protocol changed")
    rows = files.load(plan["result"], digest=report["measured_sha256"])
    verify_rows(rows, ids)
    if tydi:
        require(report["selected"] == "original frozen DeBERTa" and report["depth"] == 6
                and report["threshold"] == -2 and report["candidate"] == report["baseline"],
                "TyDi was not evaluated with the registered original policy")
        metrics = report["baseline"]["metrics"]
    else:
        require(report["split"] == plan["split"], "SQuAD split mismatch")
        metrics = report["arms"]["candidate"]
    verdicts, errors = [], {}
    for case, row in zip(cases, rows, strict=True):
        qid = case["id"]
        pred, ranking = english_prediction(case, row, docs, tydi)
        status = pred["status"]
        require(status in {"answered", "abstained", "error"}, "Unknown candidate status")
        if status == "error":
            errors[qid] = error_reason(pred, "reason")
        elif status == "answered":
            require(pred["source_id"] in ranking, "English answer cites an unread source")
        else:
            require(set(pred) == {"status"} and bool(ranking), "Abstention with answer, citation or empty retrieval")
        verdicts.append(en.grade(case, pred, docs))
    positives = [not case["impossible"] for case in cases]
    result = panel_summary(ids, positives, verdicts, errors, plan["per_stratum"])
    for group, key, pos in zip(GROUPS, EN_GROUPS, (True, False), strict=True):
        check_counts(metrics[key], result[group]["correct"], result[group]["n"], korean=False)
        if not tydi:
            require(metrics[key]["errors"] == sum(i in errors for i, p in zip(ids, positives, strict=True) if p == pos),
                    "SQuAD errors disagree with raw statuses")
    if tydi:
        require(report["baseline"]["errors"] == len(errors), "TyDi errors disagree with raw reader failures")
    return result


def evaluate(root: Path, squad: Path, tydi_en: Path) -> Row:
    files = Evidence(root)
    suite = files.load("public-suite.json", digest=SUITE_SHA)
    plans = suite["panels"]
    require({k: v["per_stratum"] for k, v in plans.items()} == REQUIRED, "Required panel roster changed")
    # Both Korean results are published atomically. Check every file before opening any predictions.
    required = [root / p[k] for p in plans.values() for k in ("result", "report") if k in p]
    required += [root / (p["freeze"] + ".started") for p in plans.values() if p["language"] == "ko"]
    missing = [str(p) for p in [*required, squad, tydi_en] if not p.is_file()]
    require(not missing, "Evidence incomplete: " + ", ".join(missing))
    require(scoring_source_digest() == suite["scoring_source_sha256"], "Registered scoring implementation changed")
    regs = {p: files.load(p, digest=h) for p, h in suite["registrations"].items()}
    policies = shared_policies(regs, files.hashes, plans)
    squad_reg = regs[plans["squad_en_primary"]["reservation"]]
    original = files.load("input/squad.json", path=squad, digest=squad_reg["data_sha256"])
    squad_panels = en.panels(original["data"])
    tydi_reg = regs[plans["tydi_en_original"]["reservation"]]
    tydi = files.load("input/tydi-en.json", path=tydi_en, digest=tydi_reg["manifest_sha256"])
    panels = {}
    for key, p in plans.items():
        if p["language"] == "ko":
            panel = grade_korean(files, regs, p)
        else:
            is_tydi = key == "tydi_en_original"
            docs, cases = (tydi["documents"], tydi["cases"]) if is_tydi else squad_panels[p["split"]]
            panel = grade_english(files, regs, p, docs, cases, tydi=is_tydi,
                                  report_digest=suite["completed_report_sha256"][p["report"]])
        panels[key] = {**panel, "policy_sha256": policies[p["language"]],
                       "freeze_sha256": files.hashes[p["freeze"]], "result_sha256": files.hashes[p["result"]]}
    require(max(Counter(i for p in panels.values() for i in p["sample_ids"]).values()) == 1,
            "Sample ID reused across registered panels")
    passed = all(p["passed"] for p in panels.values())
    return {"version": 1, "gate_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "scope": suite["scope"], "rule": suite["rule"], "passed": passed,
            "panels": panels, "input_sha256": files.hashes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=SUITE.parent, help="Directory with the registered evidence layout")
    parser.add_argument("--squad", type=Path, default=Path("/tmp/onerag-growth03-en-squad.json"))
    parser.add_argument("--tydi-en", type=Path, default=Path("/tmp/onerag-growth03-tydi-fresh.json"))
    parser.add_argument("--receipt", type=Path, help="Write once, or verify an existing complete receipt on replay")
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.root, args.squad, args.tydi_en)
        if args.receipt:
            if args.receipt.exists():
                require(parse(args.receipt.read_bytes()) == report, "Complete suite receipt differs on replay")
            else:
                ko.write_new(args.receipt, report)
        print(json.dumps(report, ensure_ascii=False, allow_nan=False))
        return 0 if report["passed"] else 1
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, ArithmeticError) as exc:
        print(f"Invalid public-suite evidence: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
